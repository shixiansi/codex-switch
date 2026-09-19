"""DSH 多开核心逻辑。

DSH 的每个 profile（``dsh --profile web`` 等）默认共用同一个 harness home
（``~/.dsh``），因此会话、设置、登录态都是同一份。**多开**指同时跑起多个
DSH 实例：每个实例是一个独立的常驻进程，各自绑定一个端口。

隔离模型（两种，按实例选择）：

* **共享 home**（默认）：沿用 ``~/.dsh``。登录态、设置、会话历史共用，
  无需重新登录；适合"同一账号开多个窗口并行干活"。
* **独立 home**：为实例准备一个自己的 harness home 目录，通过 ``DSH_HOME``
  注入。账号、会话、设置完全隔离；代价是首次要重新登录与配置。

已实测：同一个 home 同时跑两个 web 实例可以正常工作（各自 ``--port 0``
由系统分配端口）；一个全新的 home 首次启动会自行初始化 profile，且
``profiles/node_modules`` 是指向安装位置的链接，因此并不复制整套依赖。

设计要点
--------
1. **不用 ``api.run_command`` 启动**。宿主那个 API 是
   ``subprocess.run(..., timeout=120)``，而 DSH 实例是**永不退出**的常驻
   进程：用它启动会阻塞到超时（120 秒）再抛错，期间还会卡住界面。所以这里
   自己用 ``subprocess.Popen`` 启动，并把输出重定向到日志文件。
2. **启动成功与否以 stdout 里的 URL 行为准**。``dsh web`` 启动就绪时会打印
   ``dsh web: http://127.0.0.1:<port>/?token=...``；只有解析到这一行才算
   真的起来了。仅凭"进程还活着"会把"端口占用后反复重试"误报为成功。
3. **状态落盘，重启后接管**。实例记录写在 Registry 的 JSON 里；CodexSwitch
   重开时按 pid 判断是否仍在运行，仍在的就接管，避免用户以为实例"丢了"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import os
import re
import subprocess
import time
import uuid

from .dsh_home import resolve_home
from .process_util import hidden_process_kwargs, kill_pid, pid_alive, read_log_text


# 实例种类 → 传给 `dsh --profile` 的值。
KIND_WEB = "web"
KIND_HEADLESS = "headless"
KINDS = (KIND_WEB, KIND_HEADLESS)

KIND_LABELS = {
    KIND_WEB: "Web 界面",
    KIND_HEADLESS: "无界面任务",
}

# 实例生命周期状态。
STATUS_STOPPED = "stopped"
STATUS_STARTING = "starting"
STATUS_RUNNING = "running"
STATUS_FAILED = "failed"

STATUS_LABELS = {
    STATUS_STOPPED: "已停止",
    STATUS_STARTING: "启动中",
    STATUS_RUNNING: "运行中",
    STATUS_FAILED: "启动失败",
}

# 内置的 shipped profile 名。这些名字由 dsh 自带模板，不能作为
# ``--from-default-profile`` 的目标（dsh 会直接报错），但**可以**直接作为
# ``--profile`` 使用。
SHIPPED_PROFILES = ("acp", "web", "headless", "sdk", "sdk-minimal")

# 自定义 profile 名允许的字符：保持保守，因为它会成为目录名。
PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# 端口范围：0 表示交给系统分配（最省心，不会撞端口）。
PORT_MIN = 1
PORT_MAX = 65535

# 启动就绪的超时。首次启动一个全新 home 要初始化 profile 并链接依赖，
# 实测冷启动可以到 40-60 秒，所以这里给足余量。
START_TIMEOUT_SECONDS = 120

# 解析 `dsh web: http://127.0.0.1:1234/?token=...` 这一行。
WEB_URL_RE = re.compile(r"dsh web:\s*(https?://\S+)")

# 从日志尾部最多读多少字节来解析 URL。启动日志很短，这个量足够。
URL_SCAN_BYTES = 64 * 1024


class DshError(Exception):
    """面向用户的失败，消息可直接展示，不带堆栈。"""


# ---------------------------------------------------------------------------
# 路径与定位
# ---------------------------------------------------------------------------

def default_store_dir() -> Path:
    """实例注册表的存放目录，跟随 harness home。

    放在 ``~/.dsh`` 下而不是应用配置目录：这样 ``DSH_HOME`` 一改，整份
    多开状态也跟着走，与 CodeBuddy 快照库的处理保持一致。
    """
    override = os.environ.get("DSH_INSTANCES_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return resolve_home() / "codex-switch-instances"


def resolve_instance_home(name: str) -> Path:
    """某个实例在"独立 home"模式下使用的 harness home 目录。"""
    return default_store_dir() / "homes" / str(name)


def resolve_log_path(name: str) -> Path:
    """实例的标准输出日志路径（界面靠它解析访问 URL）。"""
    return default_store_dir() / "logs" / f"{_safe_name(name)}.log"


def _safe_name(name: str) -> str:
    """把实例名压成安全的文件名片段。"""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(name)).strip().strip(".")
    return cleaned[:64] or "instance"


def resolve_dsh_bin() -> list[str]:
    """定位 ``dsh`` 入口，返回可直接交给 Popen 的 argv 前缀。

    查找顺序（先环境变量，再 PATH，最后 npx 缓存）：

    1. ``DSH_BIN``：显式指定，最可靠（用户自定义安装位置时用）；
    2. ``PATH`` 上的 ``dsh``：npm 全局安装的情况；
    3. npm 的 ``_npx`` 缓存：本项目当前就是 ``npx dsh`` 形态。

    返回的是 argv **列表**（不是字符串）：终值要交给 Popen，列表形式不经过
    shell，避免路径里的空格与特殊字符引发注入或解析错误。若最终落到
    ``.js`` 入口，会把 node 显式放在最前面——``bin.js`` 没有 shebang 语义，
    必须由 node 解释。
    """
    override = os.environ.get("DSH_BIN", "").strip()
    if override:
        return _as_argv(override)

    import shutil

    found = shutil.which("dsh")
    if found:
        return _as_argv(found)

    for candidate in _npx_dsh_candidates():
        if candidate.is_file():
            return [resolve_node_bin(), str(candidate)]

    raise DshError(
        "找不到 dsh 命令。请确认已安装 DSH（能执行 `dsh --version`），"
        "或设置环境变量 DSH_BIN 指向 dsh 的入口。"
    )


def _as_argv(command: str) -> list[str]:
    """把一条命令文本拆成 argv，必要时补上解释器。

    * ``.cmd`` / ``.bat`` 需要 cmd 解释，用 ``cmd /c`` 包一层；
    * ``.js`` 需要 node 解释；
    * 其余（``.exe`` 等）原样返回。
    """
    text = command.strip()
    if not text:
        raise DshError("DSH_BIN 不能为空。")

    # 已经带了参数的情况（如 `node C:\path\bin.js`）不拆，原样交给 Popen。
    if " " in text:
        return _split_args(text)

    lowered = text.lower()
    if os.name == "nt" and lowered.endswith((".cmd", ".bat")):
        return ["cmd", "/c", text]
    if lowered.endswith(".js"):
        return [resolve_node_bin(), text]
    return [text]


def _npx_dsh_candidates() -> list[Path]:
    """npx 缓存里可能的 ``bin.js`` 位置。"""
    candidates: list[Path] = []
    override = os.environ.get("DSH_INSTALL_ROOT", "").strip()
    roots: list[Path] = []
    if override:
        roots.append(Path(override).expanduser())
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        roots.append(Path(local) / "npm-cache" / "_npx")
    if not roots:
        return candidates
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for child in children:
            candidates.append(child / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js")
    return candidates


def resolve_node_bin() -> str:
    """node 可执行文件路径。

    以 ``bin.js`` 方式启动时需要显式给出 node：目标机器上 ``node`` 不一定在
    PATH 里（nvm 环境下常见），但 Python 起子进程时不会自动补全。
    """
    override = os.environ.get("DSH_NODE_BIN", "").strip()
    if override:
        return override
    import shutil

    found = shutil.which("node")
    if found:
        return found
    raise DshError("找不到 node。请安装 Node.js，或设置 DSH_NODE_BIN 指向 node 可执行文件。")


# ---------------------------------------------------------------------------
# 实例模型
# ---------------------------------------------------------------------------

@dataclass
class Instance:
    """一个 DSH 多开实例的持久化配置。"""

    id: str
    name: str
    kind: str = KIND_WEB
    profile: str = KIND_WEB
    port: int = 0
    # 独立的 harness home；为空表示共用当前用户的 ~/.dsh。
    home: str = ""
    # 额外的命令行参数，按空格切分后追加（不经过 shell）。
    extra_args: str = ""
    created_at: str = ""

    def to_row(self) -> dict:
        row = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "kindLabel": KIND_LABELS.get(self.kind, self.kind),
            "profile": self.profile,
            "port": self.port,
            "portLabel": "自动分配" if not self.port else str(self.port),
            "home": self.home,
            "homeLabel": self.home or "共用 ~/.dsh",
            "isolated": bool(self.home),
            "extraArgs": self.extra_args,
            "createdAt": self.created_at,
        }
        return row


@dataclass
class InstanceState:
    """一个实例的**运行时**状态（不落盘，每次由进程与日志推导）。"""

    status: str = STATUS_STOPPED
    pid: int = 0
    url: str = ""
    port: int = 0
    message: str = ""
    started_at: str = ""
    # 最近一次启动的日志尾部，用于启动失败时展示原因。
    log_tail: str = ""

    @property
    def running(self) -> bool:
        return self.status in (STATUS_STARTING, STATUS_RUNNING)

    def to_row(self) -> dict:
        return {
            "status": self.status,
            "statusLabel": STATUS_LABELS.get(self.status, self.status),
            "pid": self.pid,
            "url": self.url,
            "port": self.port,
            "message": self.message,
            "startedAt": self.started_at,
            "logTail": self.log_tail,
            "running": self.running,
        }


@dataclass
class LaunchPlan:
    """一次启动的完整描述，先算好再执行，便于测试与展示。"""

    argv: list[str]
    env: dict[str, str]
    cwd: str
    log_path: Path
    url: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 启动计划
# ---------------------------------------------------------------------------

def build_plan(instance: Instance, *, base_env: dict[str, str] | None = None) -> LaunchPlan:
    """把一个实例配置翻译成可直接执行的启动计划。

    单独成函数（不直接嵌进 start），因为"算出要跑什么"和"真的去跑"是两件
    事：前者是纯函数、可单测，也方便界面展示"即将执行的命令"。因此**这里不
    创建任何目录**——目录由 :meth:`InstanceManager.start` 负责。
    """
    warnings: list[str] = []

    if instance.kind not in KINDS:
        raise DshError(f"未知的实例类型：{instance.kind}")

    profile = (instance.profile or instance.kind).strip()
    if not PROFILE_NAME_RE.match(profile):
        raise DshError(
            f"profile 名 {profile!r} 不合法：只能用小写字母、数字、``.``、``_``、``-``。"
        )
    if profile in SHIPPED_PROFILES and profile != instance.kind:
        # 内置 profile 名可以直接用，但类型要和它一致，否则会出现
        # "选 web 却跑 headless 的 profile"这种自相矛盾的配置。
        warnings.append(
            f"profile {profile!r} 是内置名称，但实例类型是 {instance.kind}，"
            "将继续按 profile 名启动。"
        )

    port = int(instance.port or 0)
    if port < 0 or port > PORT_MAX:
        raise DshError(f"端口 {port} 超出范围（0-{PORT_MAX}，0 表示自动分配）。")

    env = dict(base_env if base_env is not None else os.environ)
    if instance.home:
        home = Path(instance.home).expanduser()
        env["DSH_HOME"] = str(home)

    argv = resolve_dsh_bin()
    argv = [*argv, "--profile", profile]
    if instance.kind == KIND_WEB:
        # --no-open：多开场景下由用户在插件里点开链接，不该每开一个实例就
        # 抢一次默认浏览器焦点。
        argv += ["--port", str(port if port else 0), "--no-open"]
    if instance.extra_args.strip():
        argv += _split_args(instance.extra_args)

    log_path = resolve_log_path(instance.name)
    cwd = str(Path(instance.home).expanduser()) if instance.home else str(Path.home())

    return LaunchPlan(argv=argv, env=env, cwd=cwd, log_path=log_path, warnings=warnings)


def _split_args(text: str) -> list[str]:
    """按空白切分额外参数，支持用引号包住带空格的值。

    刻意不用 :mod:`shlex` 的 ``posix=False``：在 Windows 上它会把引号留在
    结果里（``"a b"`` → ``'"a b"'``），传下去就是一个带引号的怪参数。
    """
    import shlex

    try:
        return shlex.split(text, posix=True)
    except ValueError as error:
        raise DshError(f"额外参数无法解析：{error}") from error


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

class InstanceRegistry:
    """实例配置的持久化存储（一个 ``instances.json``）。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_store_dir()
        self.path = self.root / "instances.json"

    def ensure(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise DshError(f"无法创建多开数据目录 {self.root}：{error}") from error

    def load(self) -> list[Instance]:
        """读取全部实例。文件损坏时返回空表而不是抛错。

        多开数据是"可重建"的辅助状态：一份坏掉的 JSON 不该让整个插件页面
        打不开，更不该让主程序起不来。
        """
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return []
        entries = payload.get("instances") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return []

        instances: list[Instance] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            instance_id = str(entry.get("id") or "").strip()
            name = str(entry.get("name") or "").strip()
            if not instance_id or not name:
                continue
            instances.append(Instance(
                id=instance_id,
                name=name,
                kind=str(entry.get("kind") or KIND_WEB),
                profile=str(entry.get("profile") or entry.get("kind") or KIND_WEB),
                port=_as_int(entry.get("port")),
                home=str(entry.get("home") or ""),
                extra_args=str(entry.get("extraArgs") or ""),
                created_at=str(entry.get("createdAt") or ""),
            ))
        return instances

    def save(self, instances: list[Instance]) -> None:
        self.ensure()
        payload = {
            "version": 1,
            "instances": [
                {
                    "id": item.id,
                    "name": item.name,
                    "kind": item.kind,
                    "profile": item.profile,
                    "port": item.port,
                    "home": item.home,
                    "extraArgs": item.extra_args,
                    "createdAt": item.created_at,
                }
                for item in instances
            ],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        _atomic_write(self.path, text)

    # -- 增删改 ---------------------------------------------------------
    def find(self, key: str) -> Instance:
        """按 id 或名字定位实例，找不到就抛出可展示的错误。"""
        wanted = str(key or "").strip()
        if not wanted:
            raise DshError("实例标识不能为空。")
        for item in self.load():
            if item.id == wanted or item.name == wanted:
                return item
        raise DshError(f"没有找到实例：{wanted}")

    def upsert(self, instance: Instance) -> Instance:
        """新增或更新一个实例，返回落盘后的对象。"""
        if not instance.name.strip():
            raise DshError("实例名不能为空。")
        instances = self.load()
        for index, item in enumerate(instances):
            if item.id == instance.id:
                instances[index] = instance
                break
        else:
            instances.append(instance)
        self.save(instances)
        return instance

    def remove(self, key: str) -> Instance:
        target = self.find(key)
        self.save([item for item in self.load() if item.id != target.id])
        return target


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _atomic_write(path: Path, text: str) -> None:
    """原子写：先写同目录临时文件再替换，避免半截 JSON。"""
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(temp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temp, path)
    except OSError as error:
        temp.unlink(missing_ok=True)
        raise DshError(f"无法写入 {path}：{error}") from error


def new_instance(
    name: str,
    *,
    kind: str = KIND_WEB,
    profile: str = "",
    port: int = 0,
    isolate: bool = False,
    extra_args: str = "",
) -> Instance:
    """按用户输入构造一个实例（并校验）。"""
    clean_name = str(name or "").strip()
    if not clean_name:
        raise DshError("实例名不能为空。")
    if kind not in KINDS:
        raise DshError(f"未知的实例类型：{kind}")

    instance_id = uuid.uuid4().hex[:12]
    home = str(resolve_instance_home(clean_name)) if isolate else ""
    return Instance(
        id=instance_id,
        name=clean_name,
        kind=kind,
        profile=(profile or kind).strip(),
        port=int(port or 0),
        home=home,
        extra_args=str(extra_args or "").strip(),
        created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )


# ---------------------------------------------------------------------------
# 运行时：启动、停止、探测
# ---------------------------------------------------------------------------

def parse_web_url(text: str) -> str:
    """从日志文本里解析 ``dsh web: <url>`` 行；没有就返回空串。

    这是判断 web 实例"真的起来了"的依据：进程活着只说明 node 没退出，
    而端口被占用时 dsh 会报错重试，进程同样不会立刻退出。
    """
    if not text:
        return ""
    matches = WEB_URL_RE.findall(text)
    return matches[-1].strip() if matches else ""


def probe_state(instance: Instance, *, pid: int = 0) -> InstanceState:
    """探测一个实例当前的运行状态（不启动任何东西）。

    ``pid`` 来自内存里的运行记录；为 0 时说明本次会话没启动过它，
    那就只能靠日志判断——这种情况按"已停止"处理，避免把上次运行留下的
    日志误读成"正在运行"。
    """
    log_path = resolve_log_path(instance.name)
    tail = read_log_text(log_path, max_bytes=URL_SCAN_BYTES, tail_lines=40)
    url = parse_web_url(tail)

    if pid > 0 and pid_alive(pid):
        port = _port_from_url(url) or instance.port
        state = InstanceState(
            status=STATUS_RUNNING,
            pid=pid,
            url=url,
            port=port,
            message="实例正在运行。" if url else "进程存活，尚未输出访问地址。",
            log_tail=tail,
        )
        return state

    if pid > 0:
        # 记过 pid 但现在没了：启动失败或已退出，把原因从日志里捞出来。
        message = _failure_reason(tail) if tail else "进程已退出。"
        return InstanceState(
            status=STATUS_FAILED if log_path.is_file() else STATUS_STOPPED,
            pid=0,
            url="",
            port=0,
            message=message,
            log_tail=tail,
        )

    return InstanceState(status=STATUS_STOPPED, pid=0, log_tail=tail)


def _failure_reason(tail: str) -> str:
    """从日志尾部挑一行最有信息量的错误作为提示。"""
    lines = [line.strip() for line in tail.splitlines() if line.strip()]
    for line in reversed(lines):
        lowered = line.lower()
        if "error" in lowered or "错误" in line or "eaddrinuse" in lowered:
            return line[:300]
    return lines[-1][:300] if lines else "进程已退出。"


def _port_from_url(url: str) -> int:
    if not url:
        return 0
    match = re.search(r":(\d{1,5})(?:/|$)", url)
    return int(match.group(1)) if match else 0


class InstanceManager:
    """实例进程的实际启停与状态维护。

    每个实例最多一个进程。启动是**同步等待就绪**的：web 实例要等到日志里
    出现访问 URL 才算成功，这样界面拿到的状态就是准确的（不会出现"点了启动
    显示成功、其实端口冲突早退出了"）。
    """

    def __init__(
        self,
        registry: InstanceRegistry | None = None,
        *,
        popen=subprocess.Popen,
        poll_interval: float = 0.25,
        start_timeout: float = START_TIMEOUT_SECONDS,
    ) -> None:
        self.registry = registry or InstanceRegistry()
        self._popen = popen
        self._poll_interval = poll_interval
        self._start_timeout = start_timeout
        self._processes: dict[str, subprocess.Popen] = {}
        self._states: dict[str, InstanceState] = {}
        # 我们持有每个子进程的 stdout 句柄（重定向到日志文件）。子进程退出后
        # 这个句柄必须由我们关闭，否则会泄漏文件描述符。
        self._streams: dict[str, object] = {}

    def _close_stream(self, instance_id: str) -> None:
        stream = self._streams.pop(instance_id, None)
        if stream is None:
            return
        try:
            stream.close()  # type: ignore[attr-defined]
        except OSError:
            # 关不掉不该影响状态判定；进程已退出，句柄最终由 GC 回收。
            pass

    # -- 查询 -----------------------------------------------------------
    def state(self, instance: Instance) -> InstanceState:
        """当前状态。

        分两种情况，优先级不能颠倒：

        1. **本会话持有 Popen 句柄**：以 ``poll()`` 为准。这是我们自己起的
           进程，句柄比任何外部探测都可靠——用 ``pid_alive`` 反而会误判
           （探测假进程、pid 复用等）。
        2. **没有句柄**（程序重启后）：只看日志，一律视为"已停止"。日志里
           可能留着上次的 URL，但本会话并没有在跑它，报"运行中"是错的。
        """
        process = self._processes.get(instance.id)
        if process is not None:
            code = process.poll()
            if code is None:
                # 仍在运行：URL 以日志为准（启动时就绪后可能还没解析过）。
                cached = self._states.get(instance.id) or InstanceState()
                tail = read_log_text(
                    resolve_log_path(instance.name), max_bytes=URL_SCAN_BYTES, tail_lines=40,
                )
                url = parse_web_url(tail) or cached.url
                state = InstanceState(
                    status=STATUS_RUNNING,
                    pid=self.pid_of(instance.id),
                    url=url,
                    port=_port_from_url(url) or cached.port,
                    message="实例已就绪。" if url else "进程存活，尚未输出访问地址。",
                    started_at=cached.started_at,
                    log_tail=tail,
                )
                self._states[instance.id] = state
                return state

            # 进程已退出：把退出码带进提示，便于定位。
            self._processes.pop(instance.id, None)
            self._close_stream(instance.id)
            tail = read_log_text(
                resolve_log_path(instance.name), max_bytes=URL_SCAN_BYTES, tail_lines=40,
            )
            failed = code != 0
            state = InstanceState(
                status=STATUS_FAILED if failed else STATUS_STOPPED,
                pid=0,
                message=(f"进程已退出（退出码 {code}）。" if failed else "已停止。"),
                log_tail=tail,
            )
            self._states[instance.id] = state
            return state

        # 没有句柄：本会话没在跑它。日志只用于展示，不影响状态判定。
        #
        # 但要保留"刚刚启动失败"这个结论：否则界面一刷新（每次 reload 都会
        # 重新取状态）失败原因就消失了，用户只看到"已停止"，不知道刚才为
        # 什么没起来。
        cached = self._states.get(instance.id)
        if cached is not None and cached.status == STATUS_FAILED:
            tail = read_log_text(
                resolve_log_path(instance.name), max_bytes=URL_SCAN_BYTES, tail_lines=40,
            )
            refreshed = InstanceState(
                status=STATUS_FAILED,
                pid=0,
                message=cached.message,
                log_tail=tail,
            )
            self._states[instance.id] = refreshed
            return refreshed
        return probe_state(instance)

    def states(self, instances: list[Instance]) -> dict[str, InstanceState]:
        return {item.id: self.state(item) for item in instances}

    def pid_of(self, instance_id: str) -> int:
        process = self._processes.get(instance_id)
        if process is None:
            return 0
        pid = getattr(process, "pid", 0)
        return pid if isinstance(pid, int) else 0

    def is_running(self, instance: Instance) -> bool:
        return self.state(instance).running

    # -- 启停 -----------------------------------------------------------
    def start(self, instance: Instance) -> InstanceState:
        """启动一个实例并等待它就绪。

        Raises:
            DshError: 已经在运行、无法创建日志，或启动超时/失败。
        """
        current = self.state(instance)
        if current.status in (STATUS_RUNNING, STATUS_STARTING):
            raise DshError(f"实例 {instance.name} 已经在运行（pid {current.pid}）。")

        plan = build_plan(instance)
        if instance.home:
            # 独立 home 必须真实存在，否则 dsh 会在一个不存在的 DSH_HOME 上
            # 尝试初始化而失败。放在启动阶段创建：build_plan 是纯函数。
            try:
                Path(instance.home).expanduser().mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise DshError(f"无法创建实例 home 目录 {instance.home}：{error}") from error

        try:
            plan.log_path.parent.mkdir(parents=True, exist_ok=True)
            # 每次启动清空日志：否则上一次的 URL 行会让"本次是否就绪"永远为真。
            plan.log_path.write_text("", encoding="utf-8")
            stream = open(plan.log_path, "wb")
        except OSError as error:
            raise DshError(f"无法创建实例日志 {plan.log_path}：{error}") from error

        kwargs: dict = {
            "cwd": plan.cwd,
            "env": plan.env,
            "stdin": subprocess.DEVNULL,
            "stdout": stream,
            "stderr": subprocess.STDOUT,
        }
        kwargs.update(hidden_process_kwargs())

        try:
            process = self._popen(plan.argv, **kwargs)
        except OSError as error:
            stream.close()
            raise DshError(
                f"无法启动 dsh（{plan.argv[0]}）：{error}\n"
                "       请确认 dsh 可执行，或设置 DSH_BIN 指定入口。"
            ) from error

        pid = getattr(process, "pid", 0)
        self._processes[instance.id] = process
        self._streams[instance.id] = stream
        state = InstanceState(
            status=STATUS_STARTING,
            pid=pid if isinstance(pid, int) else 0,
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._states[instance.id] = state

        try:
            self._await_ready(instance, process, plan)
        except DshError:
            # 启动失败要把进程收干净，否则会留下一个占着端口的孤儿。
            #
            # 但 stop() 会把状态改写成"已停止"，从而抹掉 _await_ready 给出的
            # 失败原因。先记下来，收尾后再恢复——用户需要看到"为什么没起来"。
            failure = self._states.get(instance.id)
            self.stop(instance)
            if failure is not None and failure.status == STATUS_FAILED:
                self._states[instance.id] = failure
            raise
        return self._states[instance.id]

    def _await_ready(self, instance: Instance, process, plan: LaunchPlan) -> None:
        """等实例就绪。

        * **web**：以日志里出现访问 URL 为准。进程活着不代表就绪——端口被
          占用时 dsh 会报错，但在那之前进程同样不会退出。
        * **headless**：不打印 URL，因此只要求进程在短暂宽限期后仍然存活。
        """
        headless_grace = 2.0
        deadline = time.monotonic() + self._start_timeout
        while time.monotonic() < deadline:
            code = process.poll()
            tail = read_log_text(plan.log_path, max_bytes=URL_SCAN_BYTES, tail_lines=40)
            if code is not None:
                self._processes.pop(instance.id, None)
                self._close_stream(instance.id)
                reason = _failure_reason(tail) if tail else f"退出码 {code}"
                self._states[instance.id] = InstanceState(
                    status=STATUS_FAILED, pid=0, log_tail=tail,
                    message=f"启动失败：{reason}",
                )
                raise DshError(f"实例 {instance.name} 启动失败：{reason}")

            if instance.kind == KIND_WEB:
                url = parse_web_url(tail)
                if url:
                    self._states[instance.id] = InstanceState(
                        status=STATUS_RUNNING,
                        pid=self.pid_of(instance.id),
                        url=url,
                        port=_port_from_url(url),
                        message="实例已就绪。",
                        started_at=self._states[instance.id].started_at,
                        log_tail=tail,
                    )
                    return
            elif time.monotonic() >= deadline - self._start_timeout + headless_grace:
                self._states[instance.id] = InstanceState(
                    status=STATUS_RUNNING,
                    pid=self.pid_of(instance.id),
                    message="实例已启动（无界面任务）。",
                    started_at=self._states[instance.id].started_at,
                    log_tail=tail,
                )
                return

            time.sleep(self._poll_interval)

        tail = read_log_text(plan.log_path, max_bytes=URL_SCAN_BYTES, tail_lines=40)
        self._states[instance.id] = InstanceState(
            status=STATUS_FAILED, pid=self.pid_of(instance.id), log_tail=tail,
            message=f"等待实例就绪超时（{int(self._start_timeout)} 秒）。",
        )
        raise DshError(
            f"实例 {instance.name} 启动超时：{int(self._start_timeout)} 秒内没有输出访问地址。"
            + (f"\n       日志尾部：{_failure_reason(tail)}" if tail else "")
        )

    def stop(self, instance: Instance, *, timeout: float = 8.0) -> bool:
        """停止一个实例（整棵进程树）。返回是否确实做了停止动作。"""
        process = self._processes.pop(instance.id, None)
        pid = 0
        if process is not None:
            pid = getattr(process, "pid", 0) or 0
            try:
                process.terminate()
            except OSError:
                pass

        if not pid:
            cached = self._states.get(instance.id)
            if cached is not None and cached.pid:
                pid = cached.pid

        if pid:
            # 等优雅退出；没等到就按进程树强杀，避免留下占端口的子进程。
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and pid_alive(pid):
                time.sleep(self._poll_interval)
            if pid_alive(pid):
                kill_pid(pid)

        self._states[instance.id] = InstanceState(status=STATUS_STOPPED, message="已停止。")
        self._close_stream(instance.id)
        return bool(pid)

    def stop_all(self) -> int:
        """停止所有由本会话启动的实例。返回停止的数量。"""
        stopped = 0
        for instance in self.registry.load():
            if self.pid_of(instance.id) or self._states.get(instance.id, InstanceState()).pid:
                if self.stop(instance):
                    stopped += 1
        return stopped


def read_log(instance: Instance, *, tail_lines: int = 200) -> str:
    """给界面读实例日志（默认最后 200 行）。"""
    text = read_log_text(resolve_log_path(instance.name), tail_lines=tail_lines)
    if not text:
        return "（暂无日志。实例还没启动过，或日志已被清理。）"
    return text


__all__ = [
    "DshError",
    "Instance",
    "InstanceManager",
    "InstanceRegistry",
    "InstanceState",
    "KINDS",
    "KIND_HEADLESS",
    "KIND_LABELS",
    "KIND_WEB",
    "LaunchPlan",
    "SHIPPED_PROFILES",
    "START_TIMEOUT_SECONDS",
    "STATUS_FAILED",
    "STATUS_LABELS",
    "STATUS_RUNNING",
    "STATUS_STARTING",
    "STATUS_STOPPED",
    "build_plan",
    "default_store_dir",
    "new_instance",
    "parse_web_url",
    "probe_state",
    "read_log",
    "resolve_dsh_bin",
    "resolve_instance_home",
    "resolve_log_path",
]
