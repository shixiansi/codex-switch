# Codex Switch

一个本地桌面工具，用来管理多套 Codex API 配置，并一键切换到 `~/.codex/config.toml` 和 `~/.codex/auth.json`。

## 主要功能

- 显示当前 Codex 正在使用的配置
- 保存多套 API 配置并随时切换
- 测试 API 和 Key 是否可用
- 手动修正健康状态，解决“能连通但不能聊天”的情况
- 用选中的配置直接测试对话

## 本地运行

```powershell
python main.py
```

## 本地打包 Windows exe

```powershell
.\build.ps1
```

打包完成后输出在 `dist/CodexSwitch.exe`。

## 注意事项

- Linux runner 里工作流会自动安装 `python3-tk`
- macOS 包默认是未签名包，首次打开可能会被系统拦截，需要手动放行
- 当前项目主要面向桌面端 Tk 应用，跨平台包能构建，不代表每个平台都已经做过完整人工验收

## 配置存储位置

- 配置库：`%APPDATA%/CodexSwitch/profiles.json` 或 `~/.codex-switch/profiles.json`
- Codex 配置：`~/.codex/config.toml`
- Codex 鉴权：`~/.codex/auth.json`

## Community

[![LinuxDO](https://img.shields.io/badge/Community-Linux.do-blue?style=flat-square)](https://linux.do/)

Discuss, share tips, and get help at [linux.do](https://linux.do/).
