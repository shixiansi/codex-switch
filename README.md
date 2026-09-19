# Codex Switch

Codex Switch 是一个本地桌面配置管理工具，用来维护多套 Codex / Claude API 配置、全局/项目 MCP 配置、路由代理、号池和项目启动模板，并把选中的配置安全写入 Codex 使用的 `config.toml`、`auth.json`、Claude 使用的 `settings.json` 或项目级 `.codex` / `.claude` 目录。

界面基于 `PySide6 + Qt Quick/QML`（浅色主题默认，支持深色切换），定位是轻量、离线、可打包的桌面工具。API Key、项目配置和文档模板默认只保存在本机。

## 适合解决的问题

- 你有多套 OpenAI 或兼容 OpenAI 的 API，需要在 Codex 中快速切换。
- 你想同时管理 Codex 与 Claude 的 API、模型、鉴权方式和项目绑定。
- 你想把健康、异常、受限的 API 配置统一管理，并隐藏异常配置。
- 你需要为不同项目生成独立的 `.codex` 运行环境和启动脚本。
- 你希望集中维护 MCP server 配置，并在项目配置中自动替换项目路径。
- 你需要按项目启用本地路由代理，在 OpenAI Responses、Chat Completions 与 Anthropic Messages 之间做协议适配。
- 你想用号池为 Codex 路由代理提供多个上游渠道，并自动跳过异常渠道。
- 你想测试某个 API 返回的每个模型是否真的能完成聊天请求。
- 你希望维护一份默认 `AGENTS.md` 模板，用于后续生成项目模板。
- 你想扩展 CodexSwitch 的功能，又不希望每次升级都重新打补丁。

## 主要功能

### 全局配置

- 显示当前 Codex 正在使用的 provider、base URL、wire API、模型、API Key 掩码和 MCP 状态，同时展示 Claude 生成配置路径和当前模型信息。
- 在全局页可分别从配置库选择 Codex 和 Claude API，并预览将写入的 provider、wire API、模型、API 地址和活动 Key。
- 将选中的配置写入用户级 `~/.codex/config.toml`、`~/.codex/auth.json` 和 Claude `settings.json`。
- 写入前会备份已有 Codex 配置到 `~/.codex/switch-backups/`。
- 支持注入全局托管 MCP，也支持清空并显式禁用默认 MCP 注入。

### 配置库

- 新增、编辑、删除多套 API 配置。
- 配置字段包括名称、供应商类型、provider、base URL、API Key、Codex 模型、Claude 默认模型、Claude 兜底模型、接口标准、OpenAI 鉴权开关、签到信息和备注。
- 供应商类型支持 Codex、Claude、通用和其他；全局配置、项目配置和模型测试会按使用场景过滤可选配置。
- 同一套 API 配置可保存多个 API Key，并通过活动 Key 单选决定全局写入、健康检测、聊天测试和项目模板使用哪个 Key。
- 支持 `responses`、`chat_completions` 与 `anthropic_messages` 三种聊天接口标准。
- 支持健康检测、手动状态覆盖和隐藏异常 API。
- 健康检测会探测 `/v1/models` 或 `/models`，并保存最近返回的模型列表。

### 项目配置

- 维护项目目录与 Codex / Claude API 配置的绑定关系。
- 为项目生成独立模板文件，包括：
  - `AGENTS.md`
  - `CLAUDE.md`
  - `.codex/config.toml`
  - `.codex/home/config.toml`
  - `.codex/home/AGENTS.md`
  - `.claude/settings.local.json`
  - `.codex/local.env` 与 `.codex/local.env.example`
  - `.codex/home/skills/` 下选中的项目 Skills
  - `codex_scripts/start-codex.ps1`
  - `codex_scripts/start-codex.cmd`
  - `codex_scripts/codex-profile.cmd`
- 生成前会备份已存在的托管文件到 `.codex/template-backups/`。
- 支持项目级 MCP 覆盖；未设置时会回退到全局 MCP。
- 支持从用户 Skills 目录和项目 Skills 目录选择要同步到 `.codex/home/skills/` 的技能。
- 修改项目绑定 API 后，会同步更新已生成项目的 Codex 配置、Claude 配置、模型、API 地址、wire API 和 `.codex/local.env` 中的活动 Key。
- 项目启用路由代理后，生成或同步模板时会写入项目专属代理地址和代理占位 Key。
- 支持“运行项目”、“VS Code 运行”、Codex CMD 和 Claude CMD。
- 可配置项目运行命令，例如 `npm run dev`、`pnpm dev`、`python main.py`。

### 路由代理

- 内置本地 HTTP 路由代理，默认监听 `127.0.0.1:15721`。
- 可按项目启用或关闭代理，并分别维护 Codex 与 Claude 的路由规则。
- Codex 侧支持 OpenAI 直通、Chat Completions 转 Responses、Responses 转 Chat Completions。
- Claude 侧支持 Anthropic Messages 直通，也支持将 Anthropic 请求转接到 OpenAI 兼容上游。
- 支持为 Codex 设置 compact 模型，并在项目配置变更后自动刷新代理规则。
- 保留最近代理事件日志，便于排查上游失败、协议转换和项目路由问题。

### 号池

- 管理供 Codex 路由代理使用的多个上游渠道。
- 每个渠道可配置名称、base URL、API Key、wire API 和默认模型，保存前会用 `/models` 做连通性测试。
- 号池启用后，路由代理会在正常渠道中轮询选择上游，并在渠道失败时标记异常、跳过不可用渠道。
- 支持手动重测异常渠道，恢复后可重新加入可用池。

### 插件中心

- 以插件形式扩展 CodexSwitch 功能，新增能力不需要修改主程序源码。
- 插件目录分为内置与用户目录（`%APPDATA%\CodexSwitch\plugins\`），用户放入插件后点「重新扫描」即可生效，无需重启。
- 每个插件必须在 `plugin.json` 中显式声明所需权限；未声明的能力调用会被直接拒绝。
- 敏感权限（写入文件、执行命令）会在插件中心里标注出来，方便判断是否信任。
- 插件可以自带 QML 页面，选中后直接在插件中心内渲染。
- 单个插件出错只影响它自己：状态显示为「错误」并给出原因，其余插件与主程序照常工作。
- 插件开发规范见 [`docs/plugins.md`](docs/plugins.md)。

#### 内置插件：CodeBuddy 多账号

- 为 DSH 的 CodeBuddy 插件维护账号快照库，可在多个账号之间随时切换。
- 快照存在凭据文件之外，**不改动 CodeBuddy 插件自身文件**，插件升级不会丢失账号。
- 切换前会自动备份原凭据，误切了还能捞回来。
- 支持从目录批量导入凭据文件（兼容 codebuddy2api 的 `.info` 格式）。
- 切换后若 DSH 仍显示旧账号，重启 DSH 即可生效。
- 详细说明见 [`docs/codebuddy-accounts.md`](docs/codebuddy-accounts.md)。

#### 内置插件：DSH 多开

- 同时运行多个 DSH 实例，各自独立端口，互不干扰。
- 默认共用 `~/.dsh`（沿用登录态与设置，无需重新登录）；勾选「独立 home」则为该实例注入独立的 `DSH_HOME`，做到账号、设置、会话完全隔离。
- 启动时会**等到实例真的就绪**（日志里出现带 token 的访问地址）才报告成功，并可直接用浏览器打开该地址。
- 启动失败会终止残留进程，并把日志里的真实原因显示出来；每个实例都有独立日志。
- 关闭 CodexSwitch 或禁用插件**不会**杀掉正在运行的实例。
- **可给任意 DSH 环境安装插件**：每个独立 home 是一个独立环境，可单独安装，也可一次装到全部环境；支持 npm 包名、本地目录、tarball 与 git 地址，安装/卸载异步执行并显示进度与日志。
- 详细说明见 [`docs/dsh-multi.md`](docs/dsh-multi.md)。

### MCP 配置

- 以列表形式管理全局 MCP server，每个工具单独占一行。
- 支持新增、修改、删除、保存、恢复默认和清空禁用。
- 支持编辑字段：名称、type、command、args、cwd、env 和高级 TOML 字段。
- 支持在字符串字段中使用 `{project_root}` 占位符。
- 生成项目配置时，`{project_root}` 会递归替换为当前项目目录。
- 兼容旧行为：未显式使用 `{project_root}` 时，`filesystem` 和 `serena` 会自动适配项目路径。

### 文档配置

- 内置 `AGENTS.md` 模板编辑器。
- 默认模板已补充 PMNote 项目连续性规则、MCP 服务调用约束和中文编码安全流程，生成新项目模板时会同步带上这些协作规范。
- 保存后的模板会写入应用配置库，并用于后续项目模板生成。
- “恢复默认”只恢复包内默认模板预览，点击“保存文档”后才会生效。
- 不会直接修改当前仓库根目录的 `AGENTS.md`。

### 模型测试

- 左侧 API 列表复用配置库的“隐藏异常”状态。
- 右侧显示选中 API 的健康检测详情、返回模型、成功模型和聊天测试区域。
- 聊天设置使用弹窗配置，可临时选择或手动输入模型、切换 `responses`、`chat_completions`、`anthropic_messages` 接口标准，并编辑请求体 JSON 模板。
- 未做批量测试时，聊天模型来源于最近健康检测返回的模型列表。
- 完成模型批量测试后，聊天模型只允许选择成功请求的模型。
- 可打开“成功模型”弹窗查看并复制最近批量测试成功的模型名称。
- 批量测试会对每个模型发送轻量 `ping` 请求，默认最多 3 个并发，可在设置页调整到 1-5。
- 批量测试完成后会缓存到本地，跨重启保留，直到手动重新测试该 API。
- 如果接口返回 JSON 但无法提取文本，会显示完整返回结果，方便排查兼容性。

### 设置

- 设置模型批量测试的同时请求数量，范围固定为 1-5。
- 查看应用版本、Python、PySide6/Qt、配置库路径、Codex 配置路径、Claude 配置路径、当前工作目录和平台信息。

## 安装使用

### 下载发布包

在 GitHub Releases 下载对应平台包：

- `CodexSwitch-windows-x64.zip`
- `CodexSwitch-linux-x64.tar.gz`
- `CodexSwitch-macos-x64.tar.gz`

Windows 解压后运行 `CodexSwitch.exe`。macOS 包默认未签名，首次打开可能需要在系统安全设置中手动放行。

### 源码运行

需要 Python 3.11+。

```powershell
python -m pip install -r requirements.txt
python main.py
```

界面依赖 `PySide6-Essentials`。`requirements.txt` 同时保留了 `ttkbootstrap`，因为旧 Tk 界面模块与其测试仍在仓库中，但默认入口不会加载 Tk。

## 本地测试

```powershell
python -m compileall -q main.py src tests
python -m unittest discover -q -s tests
```

## 本地打包

Windows 本地打包：

```powershell
.\build.ps1
```

打包完成后输出在 `dist/CodexSwitch.exe`。

跨平台发布包由 GitHub Actions 在 tag 推送时构建。工作流会在 Windows、Linux、macOS 上安装依赖、运行单元测试（含 QML 离屏冒烟测试）并上传 Release 资产。

## 配置和数据位置

### 应用配置库

- Windows：`%APPDATA%/CodexSwitch/profiles.json`
- Linux/macOS：`~/.codex-switch/profiles.json`

`profiles.json` 保存 API 配置、项目记录、隐藏异常状态、全局 MCP、路由代理、号池、文档模板、项目 Skills 选择、模型批量测试缓存和应用设置。

### Codex 用户级配置

- `~/.codex/config.toml`
- `~/.codex/auth.json`
- `~/.codex/switch-backups/`

点击全局切换时，Codex Switch 会写入这两个 Codex 配置文件，并在写入前创建备份。

### Claude 用户级配置

- `~/.claude/settings.json`
- `~/.claude/switch-backups/`

点击全局切换时，如果选择了 Claude 配置，Codex Switch 会写入 Claude `settings.json` 并创建备份。

### 项目级模板

项目模板生成后，会在目标项目下创建 `.codex/`、`.claude/` 和 `codex_scripts/`。其中 `.codex/local.env` 包含当前项目绑定配置的活动 API Key 或路由代理占位 Key，应保持本地私有；生成器会维护 `.gitignore` 托管块，默认忽略 `codex_scripts/`。

## 项目结构

```text
.
├── main.py                         # 兼容启动入口
├── build.ps1                       # Windows 打包入口
├── CodexSwitch.spec                # PyInstaller 配置
├── scripts/package_release.py      # Release 打包脚本
├── src/codex_switch/
│   ├── main.py                     # 应用启动入口（默认启动 QML 界面）
│   ├── models.py                   # Profile、ProjectRecord、健康结果等数据模型
│   ├── storage.py                  # profiles.json 读写
│   ├── dsh_home.py                 # DSH harness home 解析（DSH_HOME > ~/.dsh）
│   ├── dsh_instances.py            # DSH 多开：实例注册表、启动计划、进程状态机
│   ├── dsh_plugins.py              # DSH 插件安装：环境枚举、异步安装任务
│   ├── process_util.py             # 进程/日志工具（pid 探测、整树结束、编码解码）
│   ├── codex_config.py             # Codex config/auth 与 MCP TOML 生成逻辑
│   ├── claude_config.py            # Claude settings.json 生成与备份
│   ├── health.py                   # /models 健康检测
│   ├── chat.py                     # 聊天测试与响应提取
│   ├── project_template.py         # 项目模板生成
│   ├── skills.py                   # 项目 Skills 扫描与同步
│   ├── proxy/                      # 路由代理、协议转换与请求清洗
│   ├── resources.py                # 包内资源加载
│   ├── assets/                     # 默认 MCP JSON 与 AGENTS 模板
│   ├── ui_v2/                      # PySide6 + QML 界面（默认入口）
│   │   ├── app.py                  # QApplication / QQmlApplicationEngine 启动
│   │   ├── controller.py           # QML 唯一边界：导航、抽屉、后台任务、提示
│   │   ├── workspace.py            # 无 Qt 依赖的业务编排层
│   │   ├── session.py              # 内存状态与 profiles.json 读写
│   │   ├── snapshots.py            # 业务对象 → QML 展示数据
│   │   ├── forms.py                # 抽屉表单结构与提交校验
│   │   ├── theme.py                # 浅色/深色主题令牌
│   │   ├── viewmodels/             # 各功能区域 ViewModel
│   │   ├── workers/                # QThreadPool 后台任务
│   │   ├── qml/                    # AppShell、components、pages、theme
│   │   └── assets/icons/           # 本地 SVG 图标
│   └── ui/                         # 旧 Tkinter 界面（保留，非默认入口）
└── tests/                          # 单元测试与 QML 冒烟测试
```

## 安全说明

- Codex Switch 不会把 API Key 上传到网络服务；Key 只在本地配置文件和你主动调用的 API 请求中使用。
- 提交到 GitHub 的源码不包含 `.codex/`、`.serena/`、`.recovered/`、`.claude/`、`.pmnote/`、本地 `.mcp.json`、trace/log/jsonl 或根目录 `AGENTS.md`。
- 项目模板生成的 `.codex/local.env` 含有项目 API Key 或路由代理占位 Key，请不要手动提交到远端仓库。
- 如果需要分享配置示例，请使用脱敏值，例如 `sk-your-key-here`。

## 开发备注

- UI 技术栈：`PySide6 + Qt Quick/QML`（`src/codex_switch/ui_v2`）。
- 应用包布局：`src/codex_switch`。
- 主题令牌由 `src/codex_switch/ui_v2/theme.py` 与 `qml/theme/Theme.qml` 统一管理，默认浅色，可在「系统」页切换深色。
- QML 不在 UI 线程执行网络、Git、模型测试或模板生成，统一走 `ui_v2/workers` 的后台任务。
- 旧 `Tkinter + ttkbootstrap` 界面保留在 `src/codex_switch/ui`，但不再是默认入口。
- MCP 默认配置来自 `src/codex_switch/assets/mcp-servers-2026-04-11.json`。
- 默认文档模板来自 `src/codex_switch/assets/AGENTS.md`。

## Community

[![LinuxDO](https://img.shields.io/badge/Community-Linux.do-blue?style=flat-square)](https://linux.do/)

Discuss, share tips, and get help at [linux.do](https://linux.do/).
