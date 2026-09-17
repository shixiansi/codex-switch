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

核心逻辑在 ``codex_switch.codebuddy_core``，与 CodexSwitch 的 CodeBuddy 插件
共用同一份实现；本文件只负责命令行参数解析与输出排版。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许直接以脚本方式运行（未安装成包时），把 src 加进搜索路径。
_HERE = Path(__file__).resolve()
for _candidate in (_HERE.parents[1] / "src", _HERE.parents[2] / "src"):
    if (_candidate / "codex_switch" / "codebuddy_core.py").is_file():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from codex_switch.codebuddy_core import (  # noqa: E402
    IMPORT_SUFFIXES,
    SnapshotStore,
    ToolError,
    describe_credential,
    import_credential_file,
    load_credential_file,
    resolve_auth_path,
    resolve_store_dir,
    save_current,
    switch_to,
)


def _load_live_credential() -> dict:
    return load_credential_file(resolve_auth_path())


def _console_supports(text: str) -> bool:
    """当前控制台编码能否输出这段文字。

    中文 Windows 的控制台默认是 GBK，输出 ``✔`` 这类符号会直接抛
    ``UnicodeEncodeError`` 让整个命令崩掉——用户看到的是一次莫名其妙的
    堆栈，而不是账号列表。所以符号类装饰要先问一句能不能印。
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _mark(primary: str, fallback: str) -> str:
    return primary if _console_supports(primary) else fallback


# --------------------------------------------------------------------------
# 命令实现
# --------------------------------------------------------------------------

def cmd_list(store: SnapshotStore, _args: argparse.Namespace) -> int:
    rows = store.rows()
    if not rows:
        print("快照库为空。")
        print(f"快照目录：{store.root}")
        print("用 `save` 保存当前账号，或 `import <文件>` 导入已有凭据。")
        return 0

    print(f"快照目录：{store.root}")
    print(f"{'序号':<4} {'当前':<4} {'昵称':<14} {'UID':<10} {'刷新令牌到期':<18} 状态")
    print("-" * 78)
    for row in rows:
        if row["broken"]:
            print(f"{row['seq']:<4} {'':<4} {'<损坏>':<14} {'':<10} {'':<18} {row['error']}")
            continue
        current = _mark("✔", "*") if row["current"] else ""
        state = "刷新令牌已过期" if row["refreshExpired"] else "可用"
        print(
            f"{row['seq']:<4} {current:<4} {row['nickname']:<14} {row['uidShort']:<10} "
            f"{row['refreshExpiresLabel']:<18} {state}"
        )
    return 0


def cmd_save(_store: SnapshotStore, args: argparse.Namespace) -> int:
    result = save_current((args.name or "").strip())
    info = result.detail
    print(f"已保存快照：{info['name']}")
    print(f"  昵称：{info['nickname']}    UID：{info['uid']}")
    return 0


def cmd_import(_store: SnapshotStore, args: argparse.Namespace) -> int:
    saved = 0
    failed = 0
    for raw in args.files:
        path = Path(raw).expanduser()
        if path.is_dir():
            # 目录导入时递归找候选文件，方便一次吃下一整个导出目录。
            # `.info` 是 codebuddy2api 的账号文件后缀，与本工具自身的 `.json`
            # 快照并存；两种都收，其余（日志、sqlite、锁文件）自然被跳过。
            targets = sorted(
                item for item in path.rglob("*")
                if item.is_file() and item.suffix.lower() in IMPORT_SUFFIXES
            )
            if not targets:
                print(f"[跳过] {path}：目录下没有可导入的凭据文件。")
                failed += 1
                continue
        else:
            targets = [path]

        for target in targets:
            try:
                credential = load_credential_file(target)
                info = describe_credential(credential)
                label = info["nickname"] if info["nickname"] != "(无昵称)" else info["uid"][:8]
                result = import_credential_file(target, label)
            except ToolError as error:
                print(f"[跳过] {target}：{error}")
                failed += 1
                continue
            print(
                f"[导入] {target.name}  ->  {result.detail['name']}  "
                f"({result.detail['nickname']} / {result.detail['uid'][:8]})"
            )
            saved += 1

    print(f"完成：导入 {saved} 个，跳过 {failed} 个。")
    return 0 if saved else 1


def cmd_use(store: SnapshotStore, args: argparse.Namespace) -> int:
    name = store.resolve(args.key)
    info = describe_credential(store.read(name))

    if info["refresh_expired"]:
        # 刷新令牌过期后插件无法自动续期，只有重新浏览器登录才行；
        # 仍然允许切换（用户可能就是想切过去再登），但必须明确警告。
        print(f"警告：`{info['nickname']}` 的刷新令牌已于 {info['refresh_expires_label']} 过期。")
        print("      插件无法自动续期，需要重新执行 `dsh-codebuddy-login` 登录。")

    result = switch_to(args.key)
    auth_path = resolve_auth_path()

    print(f"已切换到：{info['nickname']}  (UID {info['uid'][:8]})")
    print(f"凭据文件：{auth_path}")
    if result.detail.get("backup"):
        print(f"原凭据已备份：{Path(result.detail['backup']).name}")
    print()
    print("生效方式：插件在内存缓存为空时会重新读盘。")
    print("  · 若仍显示旧账号，重启 DSH 即可；重启后必定读取新账号。")
    return 0


def cmd_remove(store: SnapshotStore, args: argparse.Namespace) -> int:
    name = store.resolve(args.key)
    info = describe_credential(store.read(name))
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
