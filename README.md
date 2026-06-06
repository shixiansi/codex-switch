# Codex Switch

Codex Switch 是一个本地桌面配置管理工具，用来维护多套 Codex API 配置、全局/项目 MCP 配置和项目启动模板，并把选中的配置安全写入 Codex 使用的 `config.toml`、`auth.json` 或项目级 `.codex` 目录。

界面基于 `Tkinter + ttkbootstrap`，定位是轻量、离线、可打包的桌面工具。API Key、项目配置和文档模板默认只保存在本机。

## 适合解决的问题

- 你有多套 OpenAI 或兼容 OpenAI 的 API，需要在 Codex 中快速切换。
- 你想把健康、异常、受限的 API 配置统一管理，并隐藏异常配置。
- 你需要为不同项目生成独立的 `.codex` 运行环境和启动脚本。
- 你希望集中维护 MCP server 配置，并在项目配置中自动替换项目路径。
- 你想测试某个 API 返回的每个模型是否真的能完成聊天请求。
- 你希望维护一份默认 `AGENTS.md` 模板，用于后续生成项目模板。

## 主要功能

### 全局配置

- 显示当前 Codex 正在使用的 provider、base URL、wire API、模型、API Key 掩码和 MCP 状态。
- 在全局页可从配置库下拉选择 API，并预览将写入的 provider、wire API、模型、API 地址和活动 Key。
- 将选中的配置写入用户级 `~/.codex/config.toml` 和 `~/.codex/auth.json`。
- 写入前会备份已有 Codex 配置到 `~/.codex/switch-backups/`。
- 支持注入全局托管 MCP，也支持清空并显式禁用默认 MCP 注入。

### 配置库

- 新增、编辑、删除多套 API 配置。
- 配置字段包括名称、provider、base URL、API Key、模型、接口标准、OpenAI 鉴权开关、签到信息和备注。
- 同一套 API 配置可保存多个 API Key，并通过活动 Key 单选决定全局写入、健康检测、聊天测试和项目模板使用哪个 Key。
- 支持 `responses` 与 `chat_completions` 两种聊天接口标准。
- 支持健康检测、手动状态覆盖和隐藏异常 API。
- 健康检测会探测 `/v1/models` 或 `/models`，并保存最近返回的模型列表。

### 项目配置

- 维护项目目录与 API 配置的绑定关系。
- 为项目生成独立模板文件，包括：
  - `AGENTS.md`
  - `.codex/config.toml`
  - `.codex/home/config.toml`
  - `.codex/home/AGENTS.md`
  - `.codex/local.env` 与 `.codex/local.env.example`
  - `codex_scripts/start-codex.ps1`
  - `codex_scripts/start-codex.cmd`
  - `codex_scripts/codex-profile.cmd`
- 生成前会备份已存在的托管文件到 `.codex/template-backups/`。
- 支持项目级 MCP 覆盖；未设置时会回退到全局 MCP。
- 修改项目绑定 API 后，会同步更新已生成项目的模型、API 地址、wire API 和 `.codex/local.env` 中的活动 Key。
- 支持“运行项目”、“VS Code 运行”和“CMD 运行”。
- 可配置项目运行命令，例如 `npm run dev`、`pnpm dev`、`python main.py`。

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
- 聊天设置使用弹窗配置，可临时选择或手动输入模型、切换接口标准，并编辑请求体 JSON 模板。
- 未做批量测试时，聊天模型来源于最近健康检测返回的模型列表。
- 完成模型批量测试后，聊天模型只允许选择成功请求的模型。
- 可打开“成功模型”弹窗查看并复制最近批量测试成功的模型名称。
- 批量测试会对每个模型发送轻量 `ping` 请求，默认最多 3 个并发，可在设置页调整到 1-5。
- 批量测试完成后会缓存到本地，跨重启保留，直到手动重新测试该 API。
- 如果接口返回 JSON 但无法提取文本，会显示完整返回结果，方便排查兼容性。

### 设置

- 设置模型批量测试的同时请求数量，范围固定为 1-5。
- 查看应用版本、Python、Tk/Tcl、ttkbootstrap、配置库路径、Codex 配置路径、当前工作目录和平台信息。

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

Linux 环境如果缺少 Tk，需要先安装系统包，例如 Ubuntu：

```bash
sudo apt-get install python3-tk
```

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

跨平台发布包由 GitHub Actions 在 tag 推送时构建。工作流会在 Windows、Linux、macOS 上安装依赖、验证 tkinter、运行单元测试并上传 Release 资产。

## 配置和数据位置

### 应用配置库

- Windows：`%APPDATA%/CodexSwitch/profiles.json`
- Linux/macOS：`~/.codex-switch/profiles.json`

`profiles.json` 保存 API 配置、项目记录、隐藏异常状态、全局 MCP、文档模板、模型批量测试缓存和应用设置。

### Codex 用户级配置

- `~/.codex/config.toml`
- `~/.codex/auth.json`
- `~/.codex/switch-backups/`

点击全局切换时，Codex Switch 会写入这两个 Codex 配置文件，并在写入前创建备份。

### 项目级模板

项目模板生成后，会在目标项目下创建 `.codex/` 和 `codex_scripts/`。其中 `.codex/local.env` 包含当前项目绑定配置的活动 API Key，应保持本地私有；生成器会维护 `.gitignore` 托管块，默认忽略 `codex_scripts/`。

## 项目结构

```text
.
├── main.py                         # 兼容启动入口
├── build.ps1                       # Windows 打包入口
├── CodexSwitch.spec                # PyInstaller 配置
├── scripts/package_release.py      # Release 打包脚本
├── src/codex_switch/
│   ├── main.py                     # 应用启动与 Tcl/Tk 环境修正
│   ├── models.py                   # Profile、ProjectRecord、健康结果等数据模型
│   ├── storage.py                  # profiles.json 读写
│   ├── codex_config.py             # Codex config/auth 与 MCP TOML 生成逻辑
│   ├── health.py                   # /models 健康检测
│   ├── chat.py                     # 聊天测试与响应提取
│   ├── project_template.py         # 项目模板生成
│   ├── resources.py                # 包内资源加载
│   ├── assets/                     # 默认 MCP JSON 与 AGENTS 模板
│   └── ui/
│       ├── app.py                  # 主窗口和页面逻辑
│       ├── dialogs.py              # 配置、项目、MCP、聊天和批量测试弹窗
│       ├── styles.py               # 主题、按钮、状态徽标、顶部菜单
│       └── utils.py                # UI 辅助函数
└── tests/                          # 单元测试
```

## 安全说明

- Codex Switch 不会把 API Key 上传到网络服务；Key 只在本地配置文件和你主动调用的 API 请求中使用。
- 提交到 GitHub 的源码不包含 `.codex/`、`.serena/`、`.recovered/`、`.claude/`、`.pmnote/`、本地 `.mcp.json`、trace/log/jsonl 或根目录 `AGENTS.md`。
- 项目模板生成的 `.codex/local.env` 含有项目 API Key，请不要手动提交到远端仓库。
- 如果需要分享配置示例，请使用脱敏值，例如 `sk-your-key-here`。

## 开发备注

- UI 技术栈：`Tkinter + ttkbootstrap`。
- 应用包布局：`src/codex_switch`。
- 默认主题由 `src/codex_switch/ui/styles.py` 管理。
- MCP 默认配置来自 `src/codex_switch/assets/mcp-servers-2026-04-11.json`。
- 默认文档模板来自 `src/codex_switch/assets/AGENTS.md`。

## Community

[![LinuxDO](https://img.shields.io/badge/Community-Linux.do-blue?style=flat-square)](https://linux.do/)

Discuss, share tips, and get help at [linux.do](https://linux.do/).
