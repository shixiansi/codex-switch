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

## 上传到 GitHub

如果这是第一次把项目推到 GitHub，可以按下面做：

```powershell
git init
git add .
git commit -m "feat: initial release"
git branch -M main
git remote add origin https://github.com/<your-name>/<your-repo>.git
git push -u origin main
```

如果仓库已经建好了，只需要：

```powershell
git add .
git commit -m "chore: prepare github release workflow"
git push
```

## 自动打包不同系统

仓库已经内置了 GitHub Actions 工作流：

- 工作流文件：`.github/workflows/release.yml`
- 跨平台打包脚本：`scripts/package_release.py`
- 构建依赖：`requirements-build.txt`

它会在下面两种情况下运行：

- 你在 GitHub Actions 页面手动触发 `Build Release Packages`
- 你推送版本标签，例如 `v0.1.0`

工作流会分别构建：

- `CodexSwitch-windows-x64.zip`
- `CodexSwitch-linux-x64.tar.gz`
- `CodexSwitch-macos-x64.tar.gz`

如果是推送 `v*` 标签，工作流还会自动创建 GitHub Release，并把这些包上传到 Release 附件里。

## 如何发布一个版本

先提交代码：

```powershell
git add .
git commit -m "release: v0.1.0"
git push
```

然后打标签并推送：

```powershell
git tag v0.1.0
git push origin v0.1.0
```

推送后 GitHub Actions 会自动开始构建。构建完成后：

- 在 `Actions` 页面可以看到三个系统的构建结果
- 在 `Releases` 页面可以看到自动生成的版本和安装包

## 注意事项

- Linux runner 里工作流会自动安装 `python3-tk`
- macOS 包默认是未签名包，首次打开可能会被系统拦截，需要手动放行
- 当前项目主要面向桌面端 Tk 应用，跨平台包能构建，不代表每个平台都已经做过完整人工验收

## 配置存储位置

- 配置库：`%APPDATA%/CodexSwitch/profiles.json` 或 `~/.codex-switch/profiles.json`
- Codex 配置：`~/.codex/config.toml`
- Codex 鉴权：`~/.codex/auth.json`
