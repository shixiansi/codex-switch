# CodeBuddy 多账号切换

DSH 的 CodeBuddy 插件（`@shatyuka/dsh-llm-codebuddy`）把登录凭据存在**单个文件**里：

```
~/.dsh/codebuddy-auth.json
```

每次登录都会直接覆盖它，所以插件本身同时只能持有一个账号。本工具在这个文件之外维护
一个账号快照库，切换时把目标账号原子地写回凭据文件，从而实现「账号快照，随时切换」。

## 快速开始

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

如果你在别处有导出好的 `codebuddy-auth.json`，可以直接批量导入（支持文件、多个文件、目录）：

```powershell
python scripts/codebuddy_accounts.py import D:\exports\codebuddy-auth.json
python scripts/codebuddy_accounts.py import D:\exports\
```

导入时会校验凭据形状（必须有 `auth.accessToken`、`auth.refreshToken`、
`account.uid` 等），不合格的文件会被跳过并说明原因，不会污染快照库。
带 UTF-8 BOM 的文件也能正常导入。

## 生效方式

凭据文件是插件每次请求时按需读盘的，但**已经运行的 DSH 进程可能把旧令牌缓存在内存里**：

- 多数情况下切换后直接生效；
- 如果界面仍显示旧账号，重启 DSH 即可，重启后必定读取新账号。

工具栏里不会自动刷新账号名，这属于插件自身行为，本工具不做侵入式改动。

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
