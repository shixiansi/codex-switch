#!/usr/bin/env python3
"""CodeBuddy 多账号快照切换工具（DSH 插件 @shatyuka/dsh-llm-codebuddy 专用）。

插件把登录凭据存在单个文件里（默认 ``~/.dsh/codebuddy-auth.json``），
每次登录都会直接覆盖它，因此天生只能同时持有一个账号。

本工具在该文件之外维护一个账号快照库：把不同账号的凭据各存一份，
切换时把目标账号原子地写回凭据文件。插件在内存缓存为空时会重新读盘，
所以切换后无需重装插件；正在运行的 DSH 会在下一次请求或重载后生效。

用法::

    python codebuddy_accounts.py list
    python codebuddy_accounts.py save [名称]        # 把当前凭据存为快照
    python codebuddy_accounts.py use <名称|序号>     # 切换账号
    python codebuddy_accounts.py import <文件...>    # 导入外部凭据文件
    python codebuddy_accounts.py remove <名称|序号>
    python codebuddy_accounts.py status
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

# 快照文件里必须存在的字段：与插件 storage.js 的校验保持一致。
REQUIRED_AUTH_FIELDS = ("accessToken", "expiresAt", "refreshToken", "refreshExpiresAt", "domain")

DEFAULT_AUTH_FILE_NAME = "codebuddy-auth.json"


class ToolError(Exception):
    """面向用户的失败，消息直接打印，不带堆栈。"""


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


# --------------------------------------------------------------------------
# 命令实现
# --------------------------------------------------------------------------

def _load_live_credential() -> dict:
    return load_credential_file(resolve_auth_path())


def _backup_live_file(auth_path: Path) -> Path | None:
    """切换前把现有凭据另存为带时间戳的备份，误切了还能捞回来。"""
    if not auth_path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_dir = auth_path.parent / "codebuddy-auth-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{stamp}-{auth_path.name}"
    shutil.copy2(auth_path, target)
    return target


def _prune_backups(backup_dir: Path, keep: int = 20) -> None:
    """只保留最近 N 个备份，避免无限增长。"""
    files = sorted(backup_dir.glob("*.json"), key=lambda item: item.name)
    for path in files[:-keep]:
        path.unlink(missing_ok=True)


def cmd_list(store: SnapshotStore, _args: argparse.Namespace) -> int:
    names = store.list_names()
    try:
        live = _load_live_credential()
        live_uid = live["account"]["uid"]
    except ToolError:
        live_uid = None

    if not names:
        print("快照库为空。")
        print(f"快照目录：{store.root}")
        print("用 `save` 保存当前账号，或 `import <文件>` 导入已有凭据。")
        return 0

    print(f"快照目录：{store.root}")
    print(f"{'序号':<4} {'当前':<4} {'昵称':<14} {'UID':<10} {'刷新令牌到期':<18} 状态")
    print("-" * 78)
    for index, name in enumerate(names, start=1):
        try:
            credential = store.read(name)
        except ToolError as error:
            print(f"{index:<4} {'':<4} {'<损坏>':<14} {'':<10} {'':<18} {error}")
            continue
        info = describe_credential(credential)
        current = "✔" if live_uid and info["uid"] == live_uid else ""
        state = "刷新令牌已过期" if info["refresh_expired"] else "可用"
        print(
            f"{index:<4} {current:<4} {info['nickname']:<14} {info['uid'][:8]:<10} "
            f"{info['refresh_expires_label']:<18} {state}"
        )
    return 0


def cmd_save(store: SnapshotStore, args: argparse.Namespace) -> int:
    credential = _load_live_credential()
    info = describe_credential(credential)
    label = (args.name or info["nickname"] or info["uid"][:8]).strip()
    path = store.add(credential, label)
    print(f"已保存快照：{path.name}")
    print(f"  昵称：{info['nickname']}    UID：{info['uid']}    域名：{info['domain']}")
    return 0


def cmd_import(store: SnapshotStore, args: argparse.Namespace) -> int:
    store.ensure()
    saved = 0
    failed = 0
    for raw in args.files:
        path = Path(raw).expanduser()
        if path.is_dir():
            # 目录导入时递归找 *.json，方便一次吃下一整个导出目录。
            targets = sorted(item for item in path.rglob("*.json") if item.is_file())
            if not targets:
                print(f"[跳过] {path}：目录下没有 JSON 文件。")
                failed += 1
                continue
        else:
            targets = [path]

        for target in targets:
            try:
                credential = load_credential_file(target)
            except ToolError as error:
                print(f"[跳过] {target}：{error}")
                failed += 1
                continue
            info = describe_credential(credential)
            label = info["nickname"] if info["nickname"] != "(无昵称)" else info["uid"][:8]
            stored = store.add(credential, label)
            print(f"[导入] {target}  ->  {stored.name}  ({info['nickname']} / {info['uid'][:8]})")
            saved += 1

    print(f"完成：导入 {saved} 个，跳过 {failed} 个。")
    return 0 if saved else 1


def cmd_use(store: SnapshotStore, args: argparse.Namespace) -> int:
    name = store.resolve(args.key)
    credential = store.read(name)
    info = describe_credential(credential)

    if info["refresh_expired"]:
        # 刷新令牌过期后插件无法自动续期，只有重新浏览器登录才行；
        # 仍然允许切换（用户可能就是想切过去再登），但必须明确警告。
        print(f"警告：`{info['nickname']}` 的刷新令牌已于 {info['refresh_expires_label']} 过期。")
        print("      插件无法自动续期，需要重新执行 `dsh-codebuddy-login` 登录。")

    auth_path = resolve_auth_path()
    backup = _backup_live_file(auth_path)
    write_credential_file(auth_path, credential)
    if backup is not None:
        _prune_backups(backup.parent)

    print(f"已切换到：{info['nickname']}  (UID {info['uid'][:8]})")
    print(f"凭据文件：{auth_path}")
    if backup is not None:
        print(f"原凭据已备份：{backup.name}")
    print()
    print("生效方式：插件在内存缓存为空时会重新读盘。")
    print("  · 若仍显示旧账号，重启 DSH 即可；重启后必定读取新账号。")
    return 0


def cmd_remove(store: SnapshotStore, args: argparse.Namespace) -> int:
    name = store.resolve(args.key)
    credential = store.read(name)
    info = describe_credential(credential)
    store.remove(name)
    print(f"已删除快照：{name}  ({info['nickname']} / {info['uid'][:8]})")
    return 0


def cmd_status(store: SnapshotStore, _args: argparse.Namespace) -> int:
    auth_path = resolve_auth_path()
    print(f"凭据文件：{auth_path}")
    print(f"快照目录：{store.root}")
    print(f"快照数量：{len(store.list_names())}")
    print()
    try:
        credential = _load_live_credential()
    except ToolError as error:
        print(f"当前凭据不可用：{error}")
        return 1

    info = describe_credential(credential)
    print("当前账号：")
    print(f"  昵称：{info['nickname']}")
    print(f"  UID：{info['uid']}")
    if info["uin"]:
        print(f"  UIN：{info['uin']}")
    if info["username"]:
        print(f"  登录名：{info['username']}")
    print(f"  域名：{info['domain']}")
    print(f"  访问令牌到期：{info['expires_label']}"
          f"{'（已过期，将自动续期）' if info['access_expired'] else ''}")
    print(f"  刷新令牌到期：{info['refresh_expires_label']}"
          f"{'（已过期，需重新登录）' if info['refresh_expired'] else ''}")
    return 0


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codebuddy_accounts",
        description="CodeBuddy 多账号快照切换工具（DSH 插件专用）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python codebuddy_accounts.py save 主号\n"
            "  python codebuddy_accounts.py import D:\\exports\\*.json\n"
            "  python codebuddy_accounts.py list\n"
            "  python codebuddy_accounts.py use 2\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出所有账号快照").set_defaults(func=cmd_list)

    save = sub.add_parser("save", help="把当前凭据保存为快照")
    save.add_argument("name", nargs="?", help="快照名称，默认用账号昵称")
    save.set_defaults(func=cmd_save)

    imp = sub.add_parser("import", help="导入外部凭据文件或目录")
    imp.add_argument("files", nargs="+", help="凭据 JSON 文件或包含它们的目录")
    imp.set_defaults(func=cmd_import)

    use = sub.add_parser("use", help="切换到指定账号")
    use.add_argument("key", help="序号或名称")
    use.set_defaults(func=cmd_use)

    remove = sub.add_parser("remove", help="删除一个快照")
    remove.add_argument("key", help="序号或名称")
    remove.set_defaults(func=cmd_remove)

    sub.add_parser("status", help="显示当前凭据状态").set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = SnapshotStore(resolve_store_dir())
    try:
        return args.func(store, args)
    except ToolError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
