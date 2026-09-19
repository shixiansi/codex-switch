# CodeBuddy 多账号切换

DSH 的 CodeBuddy 插件（`@shatyuka/dsh-llm-codebuddy`）把登录凭据存在**单个文件**里：

```
~/.dsh/codebuddy-auth.json
```

每次登录都会直接覆盖它，所以插件本身同时只能持有一个账号。本工具在这个文件之外维护
一个账号快照库，切换时把目标账号原子地写回凭据文件，从而实现「账号快照，随时切换」。

**不改动 CodeBuddy 插件自身的任何文件**，所以插件升级不会丢失账号。

## 与 DSH 多开配合：每个环境各自登录

凭据文件的位置是 **`<harness home>/codebuddy-auth.json`**——也就是说**每个独立
harness home 各有一份**。而「DSH 多开」插件会给每个独立实例注入自己的
`DSH_HOME`，所以：

| 环境 | 凭据文件 | 说明 |
| --- | --- | --- |
| 共用 `~/.dsh` | `~/.dsh/codebuddy-auth.json` | 主 DSH 用的账号 |
| 独立实例 | `~/.dsh/codex-switch-instances/homes/<实例名>/codebuddy-auth.json` | 该实例自己的账号 |

**关键点**：一个实例里 CodeBuddy 登录的是哪个号，由**那个环境自己的凭据文件**
决定，与别的环境互不影响。所以插件页面提供了「目标环境」选择：

1. 选中一个环境（共用 `~/.dsh` 或某个独立实例）；
2. 下方的「当前生效账号」「切换」「保存当前账号」都作用于**该环境**；
3. 可以给不同实例切不同账号——例如主窗口用工作号、沙箱实例用个人号。

**账号快照库是共用一份的**（放在 `~/.dsh/codebuddy-accounts/`），不随环境走：
多开的价值就是让同一批账号在各环境间复用。只有"当前生效的账号"按环境区分。

> 在某个环境里切换账号后，需要**重启该环境的 DSH 实例**才会生效——
> 凭据是启动时读入的。

## 快速开始

最省事的方式是在 CodexSwitch 界面里操作：左侧「插件中心」→「CodeBuddy 多账号」。
下面是命令行用法。

```powershell
# 把当前正在用的账号存成快照（名字可省略，默认用账号昵称）
python scripts/codebuddy_accounts.py save 主号

# 查看所有账号
python scripts/codebuddy_accounts.py list

# 切换账号：支持序号、昵称、UID 前缀
python scripts/codebuddy_accounts.py use 2
python scripts/codebuddy_accounts.py use 主号

# 查看当前用的是哪个账号
python scripts/codebuddy_accounts.py status
```

不传参数时输出中文；在 PowerShell 里若出现乱码，先执行一次：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

## 新增账号

插件一次只能存一个账号，所以新增账号要「登录 → 存快照」交替进行：

```powershell
# 1. 用第二个账号登录（会打开浏览器）
npx dsh-codebuddy-login

# 2. 登录完成后，把它存成独立快照
python scripts/codebuddy_accounts.py save 小号

# 3. 之后就能在两个账号之间随意切换
python scripts/codebuddy_accounts.py use 主号
```

## 导入已有凭据文件

如果你在别处有导出好的凭据（DSH 插件的 `codebuddy-auth.json`，或 **codebuddy2api 的 `.info` 账号文件**），
可以直接批量导入（支持文件、多个文件、目录）：

```powershell
python scripts/codebuddy_accounts.py import D:\exports\codebuddy-auth.json
python scripts/codebuddy_accounts.py import G:\codebuddy2api\auth
```

目录导入会递归收集 `.json` 与 `.info` 两种后缀，同目录下的账单、模型目录、sqlite
等文件会被自动跳过并说明原因。导入时会校验凭据形状（必须有 `auth.accessToken`、
`auth.refreshToken`、`account.uid` 等），不合格的文件不会污染快照库。
带 UTF-8 BOM 的文件也能正常导入。

> **注意**：同一个账号可能在多处各有一份凭据（例如 DSH 里一份、codebuddy2api 里一份），
> 它们的 `account.uid` 相同但令牌不同。工具按 uid 区分账号，但**不会自动判断哪份更新**，
> 两份都会成为独立快照。导入后请用 `status` 对比到期时间，`remove` 掉较旧的那份。

## 生效方式

凭据文件是插件每次请求时按需读盘的，但**已经运行的 DSH 进程可能把旧令牌缓存在内存里**：

- 多数情况下切换后直接生效；
- 如果界面仍显示旧账号，重启 DSH 即可，重启后必定读取新账号。

工具栏里不会自动刷新账号名，这属于插件自身行为，本工具不做侵入式改动。

## 三种使用方式

同一个核心实现（`src/codex_switch/codebuddy_core.py`）有三种入口，按需选一种即可。

### 1. 在 CodexSwitch 界面里用（推荐）

打开 CodexSwitch → 左侧「插件中心」→「CodeBuddy 多账号」，即可查看账号列表、
一键切换、保存当前账号。这是最省事的方式，不需要记命令。

界面版由内置插件 `codebuddy-accounts` 提供，详见 [`plugins.md`](plugins.md)。

### 2. 命令行

```powershell
python scripts\codebuddy_accounts.py list
python scripts\codebuddy_accounts.py use 主号
```

脚本自带路径探测，未安装成包也能直接运行。

### 3. 走进 CodexSwitch 的脚本中心（需要包装脚本）

脚本中心以 `python <临时文件>` 运行脚本，**不传任何参数**，而本工具的 CLI 需要
子命令。直接贴进去会在 argparse 处以退出码 2 退出；若又勾了「结束后自动关闭窗口」，
窗口一闪而过，看起来就像「点了没反应」——这是运行方式不匹配，不是脚本损坏。

要用的话必须写一个把动作写死的包装脚本，且每个动作一个：

```python
import subprocess, sys
subprocess.run([sys.executable, r"F:\编程\codex-switch\scripts\codebuddy_accounts.py", "list"])
```

并且**不要勾选「结束后自动关闭窗口」**，否则看不到输出。

> 既然插件中心已经提供了完整的图形界面，一般不需要再走这条路。

## 安全与可恢复性

- **切换前自动备份**：原凭据会复制到 `~/.dsh/codebuddy-auth-backups/`，只保留最近 20 份。
- **原子写入**：先写临时文件再替换，中途失败不会留下半截凭据把你自己锁在门外。
- **失败不落地**：`use` 失败（例如账号名打错）时，凭据文件保持原样。
- **凭据不外传**：工具完全离线，只读写本地文件，不发送任何网络请求。快照里只保存插件
  会读的字段，不会把无关内容一并复制。

## 文件位置

| 内容 | 路径 |
| --- | --- |
| 当前生效的凭据 | `~/.dsh/codebuddy-auth.json` |
| 账号快照库 | `~/.dsh/codebuddy-accounts/` |
| 切换前备份 | `~/.dsh/codebuddy-auth-backups/` |

可用环境变量覆盖（默认跟随 DSH 自身优先级）：

- `DSH_HOME` —— 改写 harness home；
- `DSH_CODEBUDDY_AUTH_FILE` —— 直接指定凭据文件（插件也认这个变量）；
- `CODEBUDDY_ACCOUNTS_DIR` —— 指定快照库目录。

## 命令一览

| 命令 | 作用 |
| --- | --- |
| `list` | 列出所有账号快照，`✔` 标记当前生效的账号 |
| `save [名称]` | 把当前凭据保存为快照，名称默认取账号昵称 |
| `import <文件或目录...>` | 导入外部凭据文件 |
| `use <序号\|名称>` | 切换到指定账号 |
| `remove <序号\|名称>` | 删除一个快照（不影响当前凭据） |
| `status` | 显示当前凭据详情与令牌到期时间 |

## 常见问题

**Q：`list` 里的「刷新令牌已过期」是什么意思？**
刷新令牌过期后插件无法自动续期，切过去也会请求失败，需要重新执行
`npx dsh-codebuddy-login` 登录一次。切换到这类账号时工具会给出警告但不会阻止你。

**Q：切换后模型列表没变？**
重启 DSH。插件对目录有 5 分钟缓存，重启是最确定的刷新方式。

**Q：`use` 支持哪些写法？**
序号（`1`）、昵称（`主号`）、文件名（`主号--3c5aa09c.json`）、UID 前缀（`3c5aa09c`）都可以。
如果匹配到多个会提示你改用序号或更完整的名称。

**Q：会不会和插件升级冲突？**
不会。本工具不修改插件的任何文件，只读写插件本来就在用的凭据文件，
所以插件升级或用 `npx` 重装都不会影响快照库。

## 测试

```powershell
python -m unittest tests.test_codebuddy_accounts
```

覆盖凭据校验、BOM 容忍、原子写入、快照增删改、名称/Uid/序号解析，以及
save → import → use → status 的完整往返。
