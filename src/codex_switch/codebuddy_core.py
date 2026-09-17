"""CodeBuddy 账号快照核心逻辑。

DSH 的 CodeBuddy 插件（``@shatyuka/dsh-llm-codebuddy``）把登录凭据存在单个
文件里，每次登录都直接覆盖，因此天生只能同时持有一个账号。本模块在该文件
之外维护一个快照库：每个账号存一份凭据，切换时原子地写回凭据文件。

这里只放"业务动作"，不放任何命令行或界面代码：

* :class:`SnapshotStore` —— 快照库的增删查
* :func:`save_current` / :func:`switch_to` / :func:`import_files`
  —— 三个对外动作，返回结构化结果而不是打印文本

命令行（``scripts/codebuddy_accounts.py``）和 CodexSwitch 的 CodeBuddy 插件
都调用这些函数，避免两边各写一份切换逻辑（DRY）。
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# 快照文件里必须存在的字段：与插件 storage.js 的校验保持一致。
REQUIRED_AUTH_FIELDS = ("accessToken", "expiresAt", "refreshToken", "refreshExpiresAt", "domain")

DEFAULT_AUTH_FILE_NAME = "codebuddy-auth.json"

# 目录导入时认这些后缀。`.json` 是本工具和 DSH 插件的格式；
# `.info` 是 codebuddy2api 的账号文件格式（字段与本工具完全兼容）。
# 其余如 .sqlite3 / .lock / .wal 会在校验阶段被自然淘汰。
IMPORT_SUFFIXES = (".json", ".info")

# 保留的历史备份数量上限，避免无限增长。
BACKUP_KEEP = 20


class ToolError(Exception):
    """面向用户的失败，消息可直接展示，不带堆栈。"""


# --------------------------------------------------------------------------
# 路径解析
# --------------------------------------------------------------------------

def resolve_home() -> Path:
    """按 DSH 自己的优先级解析 harness home：DSH_HOME > ~/.dsh。"""
    override = os.environ.get("DSH_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".dsh"


def resolve_auth_path() -> Path:
    """凭据文件绝对路径，尊重插件自身的 DSH_CODEBUDDY_AUTH_FILE 逃生口。"""
    override = os.environ.get("DSH_CODEBUDDY_AUTH_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return resolve_home() / DEFAULT_AUTH_FILE_NAME


def resolve_store_dir() -> Path:
    """快照库目录，跟随 harness home，可用环境变量覆盖（便于测试）。"""
    override = os.environ.get("CODEBUDDY_ACCOUNTS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return resolve_home() / "codebuddy-accounts"


# --------------------------------------------------------------------------
# 凭据读写
# --------------------------------------------------------------------------

def load_credential_file(path: Path) -> dict:
    """读一个凭据文件并校验形状，返回规范化后的 dict。

    用 ``utf-8-sig`` 读取：Windows 上的编辑器和 PowerShell 的
    ``Set-Content -Encoding utf8`` 都会写 UTF-8 BOM，而 BOM 会让
    ``json.loads`` 直接报错。用户从别处导出的凭据文件很可能带 BOM，
    这属于格式噪声而不是真的坏文件，所以在这里一并容忍。
    """
    if not path.exists():
        raise ToolError(f"凭据文件不存在：{path}")
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise ToolError(f"无法读取凭据文件 {path}：{error}") from error
    except UnicodeDecodeError as error:
        raise ToolError(f"{path} 不是 UTF-8 文本：{error}") from error
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ToolError(f"{path} 不是合法 JSON：{error}") from error
    return normalize_credential(payload, source=str(path))


def normalize_credential(payload: object, *, source: str = "") -> dict:
    """校验并裁剪成插件认识的最小形状。

    只保留插件会读的字段，避免把凭据文件以外的东西（例如未来新增的敏感字段）
    复制进快照库；``account`` 的空字符串字段按插件的行为丢弃。
    """
    if not isinstance(payload, dict):
        raise ToolError(f"{source or '凭据'} 顶层不是对象。")

    auth = payload.get("auth")
    account = payload.get("account")
    if not isinstance(auth, dict) or not isinstance(account, dict):
        raise ToolError(f"{source or '凭据'} 缺少 auth 或 account 段。")

    missing = [field for field in REQUIRED_AUTH_FIELDS if not auth.get(field)]
    if missing:
        raise ToolError(f"{source or '凭据'} 的 auth 缺少字段：{', '.join(missing)}")

    uid = str(account.get("uid") or "").strip()
    if not uid:
        raise ToolError(f"{source or '凭据'} 缺少 account.uid。")

    trimmed_account: dict[str, str] = {"uid": uid}
    for field in ("nickname", "uin", "enterpriseId", "enterpriseName",
                  "enterpriseUserName", "departmentFullName"):
        value = account.get(field)
        # 空字符串按“不存在”处理：与插件 trimEmptyAccountFields 一致。
        if isinstance(value, str) and value:
            trimmed_account[field] = value

    return {
        "auth": {
            "accessToken": str(auth["accessToken"]),
            "expiresAt": auth["expiresAt"],
            "refreshToken": str(auth["refreshToken"]),
            "refreshExpiresAt": auth["refreshExpiresAt"],
            "domain": str(auth["domain"]),
        },
        "account": trimmed_account,
    }


def write_credential_file(path: Path, credential: dict) -> None:
    """原子写入凭据文件：先写临时文件再替换，避免半截文件让用户登不进去。

    临时文件名自己拼而不用 ``tempfile.NamedTemporaryFile``：后者在某些受限
    Windows 环境（沙箱、被拦截的临时目录）里会直接卡住不返回。同目录下的
    固定后缀临时文件已经能满足"同卷原子替换"这个唯一要求。
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ToolError(f"无法创建目录 {path.parent}：{error}") from error
    text = json.dumps(credential, ensure_ascii=False, indent=2) + "\n"
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temp_path, path)
    except OSError as error:
        temp_path.unlink(missing_ok=True)
        raise ToolError(
            f"无法写入凭据文件 {path}：{error}\n"
            "       原凭据未被修改。请检查文件权限，或确认该路径可写。"
        ) from error
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    _restrict_permissions(path)


def _restrict_permissions(path: Path) -> None:
    """POSIX 下把凭据收紧到 0600；Windows 上没有等价的 POSIX mode。

    在 Windows 上 ``os.chmod`` 只能表达只读位，把文件标成只读反而会让后续
    覆盖和临时目录清理失败，所以这里直接跳过——插件自身的 ``storage.js``
    也做了同样的平台判断。
    """
    if os.name == "nt":
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        # 不支持 POSIX mode 的文件系统（部分网络挂载）不应让写入失败。
        pass


# --------------------------------------------------------------------------
# Token 解读（只用于展示与过期提示，不做任何校验以外的用途）
# --------------------------------------------------------------------------

def decode_jwt_claims(token: str) -> dict:
    """尽力解析 JWT 载荷；失败返回空 dict（展示用，不是安全边界）。"""
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + padding)
        claims = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return claims if isinstance(claims, dict) else {}


def _millis_to_local(value: object) -> str:
    try:
        timestamp = float(value) / 1000.0
    except (TypeError, ValueError):
        return "未知"
    if timestamp <= 0:
        return "未知"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def describe_credential(credential: dict) -> dict:
    """汇总一个凭据的展示信息与可用性。"""
    auth = credential["auth"]
    account = credential["account"]
    claims = decode_jwt_claims(auth["accessToken"])

    now_ms = datetime.now().timestamp() * 1000
    try:
        expires_at = float(auth["expiresAt"])
    except (TypeError, ValueError):
        expires_at = 0.0
    try:
        refresh_expires_at = float(auth["refreshExpiresAt"])
    except (TypeError, ValueError):
        refresh_expires_at = 0.0

    return {
        "uid": account["uid"],
        "nickname": account.get("nickname") or "(无昵称)",
        "uin": account.get("uin", ""),
        "username": str(claims.get("preferred_username") or ""),
        "domain": auth["domain"],
        # 访问令牌过期不影响使用：插件会用 refreshToken 自动续期。
        "access_expired": expires_at <= now_ms,
        "refresh_expired": refresh_expires_at <= now_ms,
        "expires_label": _millis_to_local(auth["expiresAt"]),
        "refresh_expires_label": _millis_to_local(auth["refreshExpiresAt"]),
    }


# --------------------------------------------------------------------------
# 快照库
# --------------------------------------------------------------------------

def slugify(value: str) -> str:
    """把账号名压成安全的文件名片段，保留中文。"""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", value).strip().strip(".")
    cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned[:64] or "account"


class SnapshotStore:
    """快照库：一个账号一个 JSON 文件，外加一个 index.json 维护展示顺序。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.index_path = root / "index.json"

    def ensure(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ToolError(
                f"无法创建快照目录 {self.root}：{error}\n"
                "       如果这是权限问题，可用 CODEBUDDY_ACCOUNTS_DIR 指定一个可写目录。"
            ) from error

    def load_index(self) -> list[str]:
        """返回按展示顺序排列的快照文件名列表。"""
        if not self.index_path.exists():
            return []
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        entries = payload.get("snapshots") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return []
        # 只保留仍然存在的文件，顺带自愈被手工删掉快照的索引。
        return [name for name in (str(item) for item in entries) if (self.root / name).exists()]

    def save_index(self, names: list[str]) -> None:
        self.ensure()
        payload = {"version": 1, "snapshots": names}
        self.index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )

    def snapshot_path(self, name: str) -> Path:
        return self.root / name

    def read(self, name: str) -> dict:
        return load_credential_file(self.snapshot_path(name))

    def list_names(self) -> list[str]:
        """索引顺序优先；未被索引的散落文件补在后面，避免静默丢失。"""
        indexed = self.load_index()
        discovered = sorted(
            path.name for path in self.root.glob("*.json")
            if path.name != self.index_path.name
        )
        return indexed + [name for name in discovered if name not in indexed]

    def add(self, credential: dict, label: str) -> Path:
        """写入或覆盖一个快照，文件名以 uid 为前缀保证唯一。"""
        self.ensure()
        info = describe_credential(credential)
        filename = f"{slugify(label)}--{info['uid'][:8]}.json"
        path = self.snapshot_path(filename)
        write_credential_file(path, credential)
        names = [name for name in self.list_names() if name != filename]
        self.save_index(names + [filename])
        return path

    def remove(self, name: str) -> None:
        self.snapshot_path(name).unlink()
        self.save_index([item for item in self.list_names() if item != name])

    def resolve(self, key: str) -> str:
        """把用户输入的序号、快照名或账号昵称解析为唯一的快照文件名。

        匹配依次尝试：序号 → 文件名全等 → 去掉扩展名全等 → 昵称全等 →
        文件名/昵称/UID 子串。``list`` 显示的是昵称，所以昵称必须能直接命中，
        否则用户看到什么就得先猜出文件名。
        """
        names = self.list_names()
        if not names:
            raise ToolError("快照库是空的。先执行 `save` 或 `import`。")
        if key.isdigit():
            index = int(key) - 1
            if 0 <= index < len(names):
                return names[index]
            raise ToolError(f"序号 {key} 超出范围（1-{len(names)}）。")

        wanted = key.casefold()

        def nickname_of(name: str) -> str:
            try:
                return str(self.read(name)["account"].get("nickname") or "")
            except ToolError:
                # 损坏的快照不该让整个解析失败，它只是不参与匹配。
                return ""

        if key in names:
            return key

        for predicate in (
            lambda name: Path(name).stem == key,
            lambda name: nickname_of(name) == key,
            lambda name: wanted in name.casefold(),
            lambda name: wanted in nickname_of(name).casefold(),
            lambda name: wanted in str(self.read(name).get("account", {}).get("uid", "")).casefold()
            if self._readable(name) else False,
        ):
            matches = [name for name in names if predicate(name)]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise ToolError(
                    f"`{key}` 匹配到多个快照：{', '.join(matches)}。请用序号或更完整的名称。"
                )
        raise ToolError(f"没有匹配 `{key}` 的快照。用 `list` 查看现有账号。")

    def _readable(self, name: str) -> bool:
        try:
            self.read(name)
        except ToolError:
            return False
        return True

    def rows(self) -> list[dict]:
        """列出全部快照，并标注哪个是当前账号。

        这是给界面用的：一次读盘把展示需要的字段都算好，
        避免界面为每个账号重复读文件。
        """
        live_uid = read_live_uid()
        rows: list[dict] = []
        for position, name in enumerate(self.list_names(), start=1):
            try:
                info = describe_credential(self.read(name))
            except ToolError as error:
                # 坏快照照样列出来，但标明不可用——静默跳过会让用户
                # 以为账号丢了，而其实只是文件坏了。
                rows.append({
                    "seq": position,
                    "name": name,
                    "nickname": name,
                    "uid": "",
                    "uidShort": "",
                    "domain": "",
                    "refreshExpiresLabel": "",
                    "refreshExpired": False,
                    "current": False,
                    "broken": True,
                    "error": str(error),
                })
                continue
            rows.append({
                "seq": position,
                "name": name,
                "nickname": info["nickname"],
                "uid": info["uid"],
                "uidShort": info["uid"][:8],
                "domain": info["domain"],
                "refreshExpiresLabel": info["refresh_expires_label"],
                "refreshExpired": info["refresh_expired"],
                "current": bool(live_uid) and info["uid"] == live_uid,
                "broken": False,
                "error": "",
            })
        return rows


# --------------------------------------------------------------------------
# 面向动作的高层接口（CLI 与插件共用）
# --------------------------------------------------------------------------

@dataclass
class OperationResult:
    """一次操作的结果。

    用结构化返回值而不是打印文本，这样命令行和界面能各自决定怎么展示
    （CLI 打一行，插件返回给界面做提示）。
    """

    ok: bool
    message: str
    detail: dict = field(default_factory=dict)


def read_live_uid() -> str:
    """读当前凭据文件里的 uid；读不到返回空串（例如尚未登录）。"""
    try:
        return str(load_credential_file(resolve_auth_path())["account"]["uid"])
    except ToolError:
        return ""


def backup_live_file(auth_path: Path | None = None) -> Path | None:
    """切换前把现有凭据另存为带时间戳的备份，误切了还能捞回来。"""
    path = auth_path or resolve_auth_path()
    if not path.exists():
        return None
    try:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_dir = path.parent / "codebuddy-auth-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"{stamp}-{path.name}"
        shutil.copy2(path, target)
        prune_backups(backup_dir)
        return target
    except OSError:
        # 备份只是保险，失败不该阻断切换本身。
        return None


def prune_backups(backup_dir: Path, keep: int = BACKUP_KEEP) -> None:
    """只保留最近 N 个备份，避免无限增长。"""
    files = sorted(backup_dir.glob("*.json"), key=lambda item: item.name)
    for path in files[:-keep]:
        path.unlink(missing_ok=True)


def save_current(label: str = "") -> OperationResult:
    """把当前生效的凭据存为快照。"""
    credential = load_credential_file(resolve_auth_path())
    info = describe_credential(credential)
    store = SnapshotStore(resolve_store_dir())
    path = store.add(credential, label or info["nickname"])
    return OperationResult(
        ok=True,
        message=f"已保存快照：{info['nickname']}（{info['uid'][:8]}）",
        detail={"name": path.name, "nickname": info["nickname"], "uid": info["uid"]},
    )


def switch_to(key: str) -> OperationResult:
    """切换到指定账号（序号 / 快照名 / 昵称）。"""
    store = SnapshotStore(resolve_store_dir())
    name = store.resolve(key)
    credential = store.read(name)
    info = describe_credential(credential)

    auth_path = resolve_auth_path()
    backup = backup_live_file(auth_path)
    previous = read_live_uid()
    write_credential_file(auth_path, credential)

    message = f"已切换到：{info['nickname']}（{info['uid'][:8]}）"
    if previous and previous == info["uid"]:
        message = f"当前已经是：{info['nickname']}（{info['uid'][:8]}）"
    return OperationResult(
        ok=True,
        message=message,
        detail={
            "name": name,
            "nickname": info["nickname"],
            "uid": info["uid"],
            "domain": info["domain"],
            "backup": str(backup) if backup else "",
        },
    )


def import_credential_file(path: Path, label: str = "") -> OperationResult:
    """导入一个凭据文件为快照。"""
    credential = load_credential_file(path)
    info = describe_credential(credential)
    store = SnapshotStore(resolve_store_dir())
    target = store.add(credential, label or info["nickname"] or path.stem)
    return OperationResult(
        ok=True,
        message=f"已导入：{info['nickname']}（{info['uid'][:8]}）",
        detail={"name": target.name, "nickname": info["nickname"], "uid": info["uid"]},
    )


def collect_import_files(directory: Path) -> list[Path]:
    """列出一个目录里像凭据的文件；坏文件留给导入阶段逐个报错。"""
    if not directory.is_dir():
        raise ToolError(f"不是目录：{directory}")
    return sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMPORT_SUFFIXES
    )


def import_files(paths: list[Path], label: str = "") -> dict:
    """批量导入，逐个报错但不中断——一个坏文件不该让其余账号都进不来。"""
    imported: list[str] = []
    failed: list[str] = []
    for path in paths:
        try:
            result = import_credential_file(path, label)
        except ToolError as error:
            failed.append(f"{path.name}：{error}")
            continue
        imported.append(result.detail.get("nickname") or path.name)
    return {"imported": imported, "failed": failed}


__all__ = [
    "BACKUP_KEEP",
    "DEFAULT_AUTH_FILE_NAME",
    "IMPORT_SUFFIXES",
    "OperationResult",
    "REQUIRED_AUTH_FIELDS",
    "SnapshotStore",
    "ToolError",
    "backup_live_file",
    "collect_import_files",
    "decode_jwt_claims",
    "describe_credential",
    "import_credential_file",
    "import_files",
    "load_credential_file",
    "normalize_credential",
    "prune_backups",
    "read_live_uid",
    "resolve_auth_path",
    "resolve_home",
    "resolve_store_dir",
    "save_current",
    "slugify",
    "switch_to",
    "write_credential_file",
]
