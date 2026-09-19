"""DSH 插件安装的核心逻辑。

管理"给哪个 DSH 环境装插件"。一个 DSH **环境**由 ``(harness home, profile)``
唯一确定——因为 ``dsh plugin`` 就是在 ``$DSH_HOME/profiles/<profile>/`` 下跑
pnpm，所以 home 是隔离边界，profile 是安装目标。

三种安装范围，覆盖用户的所有诉求：

* **单个环境**：只给某一个实例（或共用 home）安装；
* **全部环境**：遍历所有不同的 ``(home, profile)`` 逐个安装；
* **共用 home**：给主 DSH（``~/.dsh``）安装。

它们共用同一条实现，只是目标列表不同（DRY）。

机制（已实测确认）
------------------
``dsh plugin --profile <名> add <包>`` 会在 ``$DSH_HOME/profiles/<名>/`` 下
调用 pnpm，然后**按包声明的 ``dsh.bundle`` 自动回填**
``dsh.profile.bundles``。因此：

* 装到哪个环境完全由 ``DSH_HOME`` 决定，不需要改 dsh 自身；
* ``remove`` 会同时把它移出 ``bundles``；
* profile 首次使用时会被自动初始化，无需预先创建；
* 包可以是 npm 包名、本地目录、tarball 或 git 地址。

设计取舍
--------
1. **不经过 ``api.run_command``**。它是 ``subprocess.run``，只返回 stdout 且带
   120 秒超时；而 pnpm **把进度与结果写在 stderr**（成功时也是），用它安装会
   丢掉全部有用信息。所以这里自己起子进程，把两路输出都写进日志文件。
2. **安装必须异步**。QML 调插件方法是同步执行在 UI 线程上的，而网络安装可能
   要几十秒；直接同步会把界面冻住。因此这里用后台工作线程执行，界面轮询进度。
3. **任务串行**。pnpm 会写同一个 profile 目录，并发安装会互相踩踏。用一个
   工作线程顺序执行即可——装插件不是高频操作，换来的是无并发缺陷。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid

from .dsh_home import resolve_home
from .dsh_instances import DshError, Instance, resolve_dsh_bin
from .process_util import hidden_process_kwargs, read_log_text


# 任务状态。
JOB_RUNNING = "running"
JOB_SUCCESS = "success"
JOB_FAILED = "failed"

JOB_LABELS = {
    JOB_RUNNING: "进行中",
    JOB_SUCCESS: "已完成",
    JOB_FAILED: "失败",
}

ACTION_INSTALL = "install"
ACTION_UNINSTALL = "uninstall"

ACTION_LABELS = {
    ACTION_INSTALL: "安装",
    ACTION_UNINSTALL: "卸载",
}

# pnpm 安装可能要下载不少东西；给足时间，但必须有上限，否则任务会永远挂着。
INSTALL_TIMEOUT_SECONDS = 900

# 日志保留上限（字符）。安装日志可能很长，界面只需要尾部。
LOG_KEEP_CHARS = 200_000

# 目标 id 的分隔符。``::`` 不会出现在 Windows 路径或 profile 名里。
TARGET_SEPARATOR = "::"

SHARED_TARGET_LABEL = "共用 ~/.dsh"

# profile 名允许的字符（与 dsh 自身对目录名的要求一致）。
PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class PluginError(DshError):
    """插件安装相关的失败。继承 DshError，调用方可以统一处理。"""


# ---------------------------------------------------------------------------
# 环境（目标）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PluginTarget:
    """一个可安装的 DSH 环境：``(harness home, profile)``。

    ``home`` 为空字符串表示"共用的 harness home"（即 ``~/.dsh``）。存成空串
    而不是当时的绝对路径：``DSH_HOME`` 可能在运行期变化，空串的语义才是
    "跟随当前解析结果"。
    """

    home: str
    profile: str
    label: str = ""
    # 该环境是哪个实例的（共用环境为空）。
    instance_name: str = ""
    isolated: bool = False

    @property
    def id(self) -> str:
        return f"{self.home or 'shared'}{TARGET_SEPARATOR}{self.profile}"

    @property
    def resolved_home(self) -> Path:
        return Path(self.home).expanduser() if self.home else resolve_home()

    @property
    def display_label(self) -> str:
        if self.label:
            return self.label
        return f"{SHARED_TARGET_LABEL} · profile {self.profile}"

    def to_row(self) -> dict:
        return {
            "id": self.id,
            "home": str(self.resolved_home),
            "homeRaw": self.home,
            "profile": self.profile,
            "label": self.display_label,
            "instanceName": self.instance_name,
            "isolated": self.isolated,
            "shared": not self.home,
        }


def enumerate_targets(instances: list[Instance] | None = None) -> list[PluginTarget]:
    """列出所有可安装的 DSH 环境。

    总是包含"共用 home"这一个目标——它是主 DSH 用的环境，即使当前没有任何
    实例指向它，用户也需要能给它装插件。

    按 ``(home, profile)`` 去重：多个实例共用同一个 home（或同一个实例被重复
    列出）时只保留一个目标，避免"安装到全部"做重复且可能互相冲突的工作。
    """
    targets: list[PluginTarget] = [
        PluginTarget(home="", profile="web", label=f"{SHARED_TARGET_LABEL} · profile web"),
    ]
    seen = {targets[0].id}

    for instance in instances or []:
        profile = (instance.profile or instance.kind or "web").strip()
        home = str(instance.home or "")
        # 共用 home 的实例与上面的"共用"目标是同一个环境（id 相同），会被
        # 去重掉；只有独立 home 的实例才是新的目标，标签用实例名更好辨认。
        label = (
            f"{instance.name}（独立 home）· profile {profile}"
            if home else ""
        )
        candidate = PluginTarget(
            home=home,
            profile=profile,
            label=label,
            instance_name=instance.name,
            isolated=bool(home),
        )
        if candidate.id in seen:
            continue
        seen.add(candidate.id)
        targets.append(candidate)
    return targets


def find_target(target_id: str, instances: list[Instance] | None = None) -> PluginTarget:
    """按 id 定位目标，找不到就抛出可展示的错误。"""
    wanted = str(target_id or "").strip()
    if not wanted:
        raise PluginError("安装目标不能为空。")
    for target in enumerate_targets(instances):
        if target.id == wanted:
            return target
    raise PluginError(f"没有找到安装目标：{wanted}")


# ---------------------------------------------------------------------------
# 读取某个环境已装的插件
# ---------------------------------------------------------------------------

def profile_dir(target: PluginTarget) -> Path:
    """目标环境的 profile 目录（``dsh plugin`` 的工作目录）。"""
    return target.resolved_home / "profiles" / target.profile


def read_profile(target: PluginTarget) -> dict:
    """读取目标环境的 profile 清单。

    直接读 ``package.json`` 而不去问 dsh：列表展示是只读操作，不该为了刷个
    界面就去跑一次外部命令。读不到就是"环境还没初始化"，属于正常状态。
    """
    path = profile_dir(target) / "package.json"
    empty = {
        "exists": False,
        "path": str(path),
        "dependencies": {},
        "bundles": [],
        "error": "",
    }
    if not path.is_file():
        return empty
    try:
        # utf-8-sig：Windows 上的编辑器/PowerShell 常写出带 BOM 的 JSON，
        # 而带 BOM 的内容会让 json.loads 直接报错（实测 dsh 自己就栽在这上面）。
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        return {**empty, "exists": True, "error": f"读取 profile 清单失败：{error}"}
    if not isinstance(payload, dict):
        return {**empty, "exists": True, "error": "profile 清单顶层不是对象。"}

    dependencies = payload.get("dependencies")
    dsh_section = payload.get("dsh")
    bundles = []
    if isinstance(dsh_section, dict):
        profile_section = dsh_section.get("profile")
        if isinstance(profile_section, dict):
            raw_bundles = profile_section.get("bundles")
            if isinstance(raw_bundles, list):
                bundles = [str(item) for item in raw_bundles if str(item or "").strip()]

    return {
        "exists": True,
        "path": str(path),
        "dependencies": dependencies if isinstance(dependencies, dict) else {},
        "bundles": bundles,
        "error": "",
    }


def list_installed(target: PluginTarget) -> dict:
    """列出某个环境已安装的插件（供界面渲染）。

    "已安装"以 ``dependencies`` 为准（那是 pnpm 真正装进去的东西）；
    同时标注它是不是被当作 profile 层激活（``dsh.bundle``）——这正是
    ``dsh plugin`` 会自动维护的 ``bundles`` 列表。
    """
    info = read_profile(target)
    bundles = set(info["bundles"])
    rows: list[dict] = []
    for name, spec in sorted(info["dependencies"].items()):
        active = name in bundles
        rows.append({
            "name": name,
            "spec": str(spec),
            "active": active,
            "statusLabel": "已启用" if active else "普通依赖",
            "statusTone": "success" if active else "unknown",
        })

    # 内置层（@deepseek-ai/... 等）不是用户装的依赖，但也在 bundles 里，
    # 一并列出并标注，避免用户以为"列表里没有 = 环境里没有"。
    builtin = [name for name in info["bundles"] if name not in info["dependencies"]]

    return {
        "ok": not info["error"],
        "message": info["error"],
        "exists": info["exists"],
        "path": info["path"],
        "plugins": rows,
        "builtinLayers": builtin,
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# 安装任务
# ---------------------------------------------------------------------------

@dataclass
class InstallJob:
    """一次安装/卸载任务。由后台线程执行，界面轮询它的状态与日志。"""

    id: str
    action: str
    spec: str
    # 提交时就已经解析好的目标。**不在执行时重新解析**：后台线程可能晚于
    # 提交才开始跑，而实例随时可能被删除或改名；那时再按 id 去查会失败，
    # 或者装到一个和用户所看到的不一致的环境里。
    targets: list[PluginTarget] = field(default_factory=list)
    status: str = JOB_RUNNING
    message: str = ""
    log_path: str = ""
    started_at: str = ""
    finished_at: str = ""
    # 已经处理完的目标数量，用于显示进度。
    done: int = 0

    @property
    def running(self) -> bool:
        return self.status == JOB_RUNNING

    def to_row(self) -> dict:
        return {
            "id": self.id,
            "action": self.action,
            "actionLabel": ACTION_LABELS.get(self.action, self.action),
            "spec": self.spec,
            "targetIds": [item.id for item in self.targets],
            "targetLabels": [item.display_label for item in self.targets],
            "status": self.status,
            "statusLabel": JOB_LABELS.get(self.status, self.status),
            "running": self.running,
            "message": self.message,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "done": self.done,
            "total": len(self.targets),
        }


def validate_spec(spec: str) -> str:
    """校验用户输入的包标识，返回清理后的值。

    pnpm 最终会经 shell 执行，所以这里挡掉控制字符与换行；同时不接受以
    ``-`` 开头的输入——那是 pnpm 自己的参数位（``-D`` 之类），把它当包名
    传下去会得到难以理解的行为。
    """
    text = str(spec or "").strip()
    if not text:
        raise PluginError("请填写要安装的包（npm 包名、本地目录或 git 地址）。")
    if text.startswith("-"):
        raise PluginError("包名不能以 '-' 开头（那是 pnpm 的参数，不是包）。")
    if any(char in text for char in ("\n", "\r", "\x00")):
        raise PluginError("包名不能包含换行或空字符。")
    if len(text) > 500:
        raise PluginError("包名过长（上限 500 字符）。")
    return text


def build_plugin_command(target: PluginTarget, args: list[str]) -> list[str]:
    """构造 ``dsh plugin --profile <名> ...`` 的 argv。

    以列表传参、不经过 shell：包名里含空格（本地路径很常见）也不会被拆开。
    """
    if not PROFILE_NAME_RE.match(target.profile):
        raise PluginError(
            f"profile 名 {target.profile!r} 不合法：只能用小写字母、数字、"
            "``.``、``_``、``-``。"
        )
    return [*resolve_dsh_bin(), "plugin", "--profile", target.profile, *args]


class InstallJobManager:
    """串行执行安装任务的工作线程 + 任务表。

    串行的理由见模块开头：pnpm 会写同一个 profile 目录，并发会互相踩踏。
    """

    def __init__(
        self,
        *,
        log_dir: Path | None = None,
        runner=None,
    ) -> None:
        self.log_dir = Path(log_dir) if log_dir else (resolve_home() / "codex-switch-instances" / "plugin-logs")
        # 允许注入 runner 以便单测：默认走真实的子进程。
        self._runner = runner or self._run_command
        self._jobs: dict[str, InstallJob] = {}
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    # -- 任务表 ---------------------------------------------------------
    def jobs(self) -> list[InstallJob]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda item: item.started_at, reverse=True)

    def job(self, job_id: str) -> InstallJob:
        with self._lock:
            found = self._jobs.get(str(job_id))
        if found is None:
            raise PluginError(f"没有找到任务：{job_id}")
        return found

    def job_log(self, job_id: str, *, tail_lines: int = 300) -> str:
        found = self.job(job_id)
        text = read_log_text(found.log_path, tail_lines=tail_lines) if found.log_path else ""
        return text or "（暂无输出。）"

    def has_running(self) -> bool:
        with self._lock:
            return any(item.running for item in self._jobs.values())

    # -- 提交 -----------------------------------------------------------
    def submit(
        self,
        action: str,
        spec: str,
        targets: list[PluginTarget],
    ) -> InstallJob:
        """登记一个任务并交给工作线程。立即返回，不等它跑完。"""
        if not targets:
            raise PluginError("没有可用的安装目标。")
        if action not in (ACTION_INSTALL, ACTION_UNINSTALL):
            raise PluginError(f"未知操作：{action}")

        with self._lock:
            running = [item for item in self._jobs.values() if item.running]
        if running:
            raise PluginError(
                "已有安装任务在进行中，请等它结束再提交新的任务"
                f"（当前：{running[0].action} {running[0].spec}）。"
                "pnpm 会写同一个目录，并发执行会互相踩踏。"
            )

        job = InstallJob(
            id=uuid.uuid4().hex[:12],
            action=action,
            spec=spec,
            targets=list(targets),
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        with self._lock:
            self._jobs[job.id] = job
        self._queue.put(job.id)
        self._ensure_worker()
        return job

    # -- 工作线程 -------------------------------------------------------
    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            worker = threading.Thread(target=self._work, name="dsh-plugin-install", daemon=True)
            self._worker = worker
        worker.start()

    def _work(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None:
                return
            try:
                self._execute(job_id)
            except Exception as error:  # noqa: BLE001 - 后台线程绝不能因异常静默死掉
                self._finish(job_id, JOB_FAILED, f"任务异常终止：{type(error).__name__}: {error}")
            finally:
                self._queue.task_done()

    def _execute(self, job_id: str) -> None:
        job = self.job(job_id)
        targets = list(job.targets)

        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_path = self.log_dir / f"{job.id}.log"
            log_path.write_text("", encoding="utf-8")
            job.log_path = str(log_path)
        except OSError as error:
            self._finish(job_id, JOB_FAILED, f"无法创建安装日志：{error}")
            return

        failures: list[str] = []
        for index, target in enumerate(targets, start=1):
            header = (
                f"\n{'=' * 60}\n"
                f"[{index}/{len(targets)}] {ACTION_LABELS.get(job.action, job.action)} "
                f"{job.spec}\n目标：{target.display_label}\n"
                f"home：{target.resolved_home}\n"
                f"profile：{target.profile}\n{'=' * 60}\n"
            )
            self._append_log(job, header)

            try:
                argv = self._command_for(job, target)
            except PluginError as error:
                failures.append(f"{target.display_label}: {error}")
                self._append_log(job, f"\n[失败] {error}\n")
                job.done = index
                continue

            self._append_log(job, f"$ {' '.join(argv)}\n")
            code, output = self._runner(argv, target, job)
            if output:
                self._append_log(job, output)
            if code == 0:
                self._append_log(job, "\n[成功]\n")
            else:
                detail = _first_error_line(output) or f"退出码 {code}"
                failures.append(f"{target.display_label}: {detail}")
                self._append_log(job, f"\n[失败] 退出码 {code}\n")
                if code == 127:
                    self._append_log(
                        job,
                        "\n提示：dsh 报告找不到 pnpm。请确认 pnpm 在 PATH 上"
                        "（dsh 自身就是靠 pnpm 管理 profile 插件的）。\n",
                    )
            job.done = index

        if failures:
            self._finish(
                job_id,
                JOB_FAILED,
                f"{len(failures)}/{len(targets)} 个目标失败：" + "；".join(failures[:3]),
            )
        else:
            verb = "安装" if job.action == ACTION_INSTALL else "卸载"
            self._finish(
                job_id, JOB_SUCCESS,
                f"已在 {len(targets)} 个环境中{verb} {job.spec}。",
            )

    def _command_for(self, job: InstallJob, target: PluginTarget) -> list[str]:
        if job.action == ACTION_INSTALL:
            return build_plugin_command(target, ["add", job.spec])
        return build_plugin_command(target, ["remove", job.spec])

    def _append_log(self, job: InstallJob, text: str) -> None:
        if not job.log_path or not text:
            return
        try:
            with open(job.log_path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except OSError:
            # 日志写不进去不该让安装本身失败。
            pass

    def _run_command(self, argv: list[str], target: PluginTarget, job: InstallJob) -> tuple[int, str]:
        """执行一次 dsh plugin 调用，返回 ``(退出码, 合并后的输出)``。

        输出**重定向到文件**而不是管道：管道有容量上限，pnpm 输出多时会把
        子进程写阻塞（死锁）；重定向到文件则没有这个问题，也让"边跑边看日志"
        成为可能。
        """
        env = dict(os.environ)
        # 目标环境由 DSH_HOME 决定——这正是"装到哪个环境"的唯一开关。
        env["DSH_HOME"] = str(target.resolved_home)
        try:
            target.resolved_home.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise PluginError(f"无法创建环境目录 {target.resolved_home}：{error}") from error

        output_path = Path(job.log_path).with_suffix(".out") if job.log_path else None
        if output_path is None:
            raise PluginError("任务缺少日志路径。")
        try:
            stream = open(output_path, "wb")
        except OSError as error:
            raise PluginError(f"无法创建输出文件 {output_path}：{error}") from error

        kwargs: dict = {
            # cwd 必须是**已存在**的目录：dsh 会用它作为相对路径参数的锚点，
            # 而 profiles/ 在全新 home 上还不存在（profile 由 dsh 自己创建），
            # 直接用它当 cwd 会因为"目录无效"而启动失败（WinError 267）。
            # 用 harness home：它一定存在（上面刚创建），语义也清楚——
            # 相对路径相对于该环境解析。
            "cwd": str(target.resolved_home),
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": stream,
            "stderr": subprocess.STDOUT,
        }
        kwargs.update(hidden_process_kwargs())
        try:
            try:
                completed = subprocess.run(  # noqa: S603 - argv 由本模块构造
                    argv, timeout=INSTALL_TIMEOUT_SECONDS, check=False, **kwargs,
                )
            except subprocess.TimeoutExpired:
                return 1, f"命令超过 {INSTALL_TIMEOUT_SECONDS} 秒未结束，已放弃。"
            except OSError as error:
                return 1, f"无法执行命令：{error}"
        finally:
            stream.close()

        return completed.returncode, read_log_text(output_path)

    def _finish(self, job_id: str, status: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = status
            job.message = message
            job.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")

    def shutdown(self) -> None:
        """停止工作线程。

        只停止"继续接新任务"，**不等**正在跑的安装结束：安装可能还要几十秒，
        为了退出程序而中断一个写到一半的 pnpm 更糟。工作线程是 daemon，
        进程退出时由操作系统回收。
        """
        self._queue.put(None)


def _first_error_line(output: str) -> str:
    """从输出里挑一行最像错误的内容作为摘要。"""
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    for line in reversed(lines):
        lowered = line.lower()
        if "error" in lowered or "err_" in lowered or "错误" in line or "failed" in lowered:
            return line[:300]
    return lines[-1][:300] if lines else ""


__all__ = [
    "ACTION_INSTALL",
    "ACTION_LABELS",
    "ACTION_UNINSTALL",
    "INSTALL_TIMEOUT_SECONDS",
    "InstallJob",
    "InstallJobManager",
    "JOB_FAILED",
    "JOB_LABELS",
    "JOB_RUNNING",
    "JOB_SUCCESS",
    "PluginError",
    "PluginTarget",
    "SHARED_TARGET_LABEL",
    "build_plugin_command",
    "enumerate_targets",
    "find_target",
    "list_installed",
    "profile_dir",
    "read_profile",
    "validate_spec",
]
