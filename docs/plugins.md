# CodexSwitch 插件开发规范

插件让 CodexSwitch 的功能扩展不再需要修改主程序源码。本文是插件的契约说明，
也是提交插件前的自查清单。

- [1. 插件放在哪里](#1-插件放在哪里)
- [2. 目录结构](#2-目录结构)
- [3. plugin.json 字段](#3-pluginjson-字段)
- [4. 权限模型](#4-权限模型)
- [5. 入口模块](#5-入口模块)
- [6. 插件页面](#6-插件页面)
- [7. 风险防范](#7-风险防范)
- [8. 调试与排错](#8-调试与排错)
- [9. 自查清单](#9-自查清单)

---

## 1. 插件放在哪里

| 位置 | 用途 | 是否随程序升级 |
| --- | --- | --- |
| `src/codex_switch/builtin_plugins/` | 内置插件，随程序发布 | 会 |
| `%APPDATA%\CodexSwitch\plugins\` | 用户安装的插件 | 不会 |

在插件中心点「打开插件目录」可直接定位到用户插件目录。放入插件后点
「重新扫描」即可被发现，无需重启。

> 目录名以 `_` 或 `.` 开头的会被跳过，可以用这个约定临时停用某个插件。

## 2. 目录结构

一个插件就是一个目录，最少需要两个文件：

```
my-plugin/
├── plugin.json     必需，插件清单
├── entry.py        必需，Python 入口
└── page.qml        可选，插件自带的界面
```

清单里声明的 `entry` 与 `page` 必须是**插件目录内的相对路径**：不允许绝对路径，
也不允许 `..` 逃逸。这条限制让宿主能审计一个插件到底加载了哪些文件。

## 3. plugin.json 字段

```json
{
  "id": "my-plugin",
  "name": "我的插件",
  "version": "1.0.0",
  "apiVersion": 1,
  "entry": "entry.py",
  "page": "page.qml",
  "author": "你的名字",
  "description": "一句话说明这个插件做什么。",
  "permissions": ["snapshot:read", "action:invoke"],
  "paths": {},
  "actions": [
    { "key": "refresh", "label": "刷新", "description": "重新读取状态。" }
  ]
}
```

| 字段 | 必需 | 说明 |
| --- | --- | --- |
| `id` | 是 | 全局唯一。小写字母开头，只能含小写字母、数字、连字符，长度 3–64 |
| `name` | 是 | 显示名，上限 64 字符 |
| `version` | 是 | `1.0` 或 `1.0.0` |
| `apiVersion` | 是 | 必须是整数 **1**。不匹配会被拒绝加载 |
| `entry` | 是 | Python 入口，必须是 `.py` |
| `page` | 否 | 插件页面，必须是 `.qml` |
| `author` | 否 | 上限 100 字符 |
| `description` | 否 | 上限 500 字符 |
| `permissions` | 否 | 权限列表，见下一节。**未知权限会被拒绝**，不会静默忽略 |
| `paths` | 条件必需 | 声明了 `fs:read` / `fs:write` 时必须给出对应根目录 |
| `actions` | 否 | 声明式动作按钮，`key` 不可重复，每项必须有 `label` |

### apiVersion 为什么必须精确匹配

插件是按某一份契约写的。宿主升级后如果行为变了而插件没跟着改，
与其让插件在半懂的 API 上跑出难以定位的怪问题，不如在加载阶段就拒绝，
并在插件中心明确告诉用户"该插件需要更新"。

## 4. 权限模型

**能力必须显式声明，未声明的调用直接抛 `PermissionDenied`。**

| 权限 | 含义 | 敏感 |
| --- | --- | --- |
| `snapshot:read` | 读取应用状态快照 | |
| `action:invoke` | 触发已登记的宿主动作 | |
| `fs:read` | 读取指定目录下的文件 | |
| `fs:write` | 写入指定目录下的文件 | 是 |
| `exec` | 执行外部命令 | 是 |

敏感权限会在插件中心里被标注出来，方便用户判断是否信任。

### 文件权限必须配 paths

声明了 `fs:read` / `fs:write` 的插件**必须**同时给出可访问的根目录：

```json
{
  "permissions": ["fs:read", "fs:write"],
  "paths": {
    "fs:read":  ["~/.dsh"],
    "fs:write": ["~/.dsh"]
  }
}
```

缺少 `paths` 会在**加载阶段**就报错。这是刻意设计的：与其让作者在运行时
困惑"我明明声明了权限为什么读不到"，不如在清单校验时就指出问题——
错误在插件中心里一眼可见。

运行期还有第二道防线：即清单合法，路径解析后也必须落在声明的根目录内，
`..` 逃逸会被拒绝。声明了权限但宿主没配置根目录时一律拒绝，而不是放行。

## 5. 入口模块

入口必须提供一个 `load(api)` 函数，宿主在加载插件时调用它：

```python
def load(api):
    api.log("插件已加载。")
    return MyPlugin(api)


class MyPlugin:
    def __init__(self, api):
        self.api = api

    def unload(self):
        """可选。宿主退出或禁用插件时调用，用于释放资源。"""
```

`load()` 可以返回 `None`（无状态插件）。返回的对象就是插件实例，
插件页面通过它取数据。

### api 提供什么

插件**只拿到 `PluginApi`，拿不到宿主内部对象**。这是刻意的：
插件能做的事必须是一份可审计的短清单。

| 方法 | 需要权限 | 说明 |
| --- | --- | --- |
| `api.log(message)` | | 在界面上提示一条信息 |
| `api.has(permission)` | | 是否声明了某权限 |
| `api.snapshot()` | `snapshot:read` | 应用状态快照。返回**深拷贝**，改它不影响宿主 |
| `api.invoke(action, payload)` | `action:invoke` | 调用宿主已登记的动作 |
| `api.read_text(path)` | `fs:read` | 读文件，必须在声明的根目录内 |
| `api.write_text(path, text)` | `fs:write` | 原子写文件，同样受根目录限制 |
| `api.list_dir(path)` | `fs:read` | 列目录 |
| `api.run_command(argv)` | `exec` | 执行命令。**列表参数形式，不经 shell**，120 秒超时 |

## 6. 插件页面

`page.qml` 由插件中心的宿主控件（`PluginHost`）动态加载。它是普通 QML，
可以直接 `import theme` 与 `import components`，与内置页面用同一套视觉规范。

### 页面拿数据的方式

宿主会给页面注入一个 `instance` 属性：

```qml
Item {
    property var instance: null

    function reload() {
        if (!instance) return
        accounts = instance.accounts()
    }

    onInstanceChanged: if (instance) reload()
    Component.onCompleted: if (instance) reload()
}
```

两个时机都要写：`instance` 可能在页面创建之后才注入（插件异步加载完），
只在 `onCompleted` 里读会拿到空数据。

> **重要**：`instance` 不是插件的 Python 对象本身，而是宿主包装后的
> `PluginCallBridge`（一个真正的 `QObject`）。原因见下节。

### 为什么不能直接暴露插件对象

QML 只对注册过的 `QObject` 类型调用方法。把一个普通的 Python 对象作为
`QVariant` 传给 QML 后，`instance.foo()` 会直接报：

```
Property 'foo' of object QVariant(PySide::PyObjectWrapper, <MyPlugin>) is not a function
```

插件页面因此完全无法工作，而且没有任何编译期错误提示。所以宿主统一用
`PluginCallBridge` 包装后再注入。

调用桥只放行白名单方法（见 `ui_v2/plugin_bridge.py` 的 `ALLOWED_METHODS`），
插件实例上的内部方法无法被界面触发。

## 7. 风险防范

插件是第三方代码，宿主在多处做了隔离。写插件时也请遵守同样的原则。

**宿主侧**

| 措施 | 效果 |
| --- | --- |
| 权限白名单 | 未声明的能力调用直接拒绝，不静默放行 |
| 路径根目录 + 解析校验 | 走 `api` 的 `..` 逃逸会被拒绝，`fs:read` 不等于全盘可读（直接文件访问不受限，见下） |
| `snapshot()` 返回深拷贝 | 插件改不动宿主状态 |
| `exec` 不经 shell | 避免拼接字符串导致的命令注入 |
| 清单严格校验 | 非法 id、越界路径、未知权限、apiVersion 不匹配一律拒载 |
| 加载/调用异常隔离 | 插件抛错只影响该插件，不中断启动、不影响其他插件 |
| 调用桥方法白名单 | 插件内部方法不会被界面随手触发 |

前六项约束的是"插件通过宿主提供的接口能做什么"；它们**不构成对恶意代码的
隔离**，原因见下一节。

**插件侧**

- 请只读写声明过的路径。**注意**：`api` 之外的文件访问不会被拦截，见下方说明。
- 长时间操作要给出反馈，避免界面看起来卡住。
- 不要吞掉异常后返回 `None`；返回带 `ok`/`message` 的结果，让用户知道发生了什么。
- 不要修改其他插件或宿主自身的文件。

### 权限边界的真实范围（重要）

上面那张表里的路径限制，**只对 `api.read_text` / `api.write_text` /
`api.list_dir` / `api.run_command` 生效**。插件入口是普通的 Python 代码，
运行在宿主进程内，它可以 `import` 宿主模块、也可以直接用 `open()` 读任何
它能访问的文件——这些都不会被拦截。

也就是说，`paths` 声明是一份**可审计的意图声明**，而不是操作系统级的沙箱：

| 想解决的问题 | 是否解决 |
| --- | --- |
| 让用户看清插件声明了多大范围 | ✅ 插件中心会显示权限与根目录 |
| 防止插件"顺手"越界后难以排查 | ✅ 走 `api` 的越界会被明确拒绝 |
| 抵御恶意插件 | ❌ 做不到，恶意代码可以直接绕过 |

因此：**只安装你信任的插件**。`fs:write` 与 `exec` 之所以被标为敏感权限，
就是因为它们的影响无法靠声明约束住。

> 真正的进程级隔离（例如把插件跑在独立子进程里、只通过 RPC 通信）是更大的
> 架构改动，目前没有做。如果你需要这一层保障，请把它当作已知的边界来对待。

**一个坏插件的影响范围**：只会让它在插件中心里显示为「错误」状态，
其余插件照常工作，程序照常启动。

## 8. 调试与排错

插件的问题都会显示在插件中心的页面上，按状态区分：

| 状态 | 含义 | 常见原因 |
| --- | --- | --- |
| 已启用 | 加载成功 | |
| 已禁用 | 被用户关闭 | |
| 错误 | 扫描或加载失败 | 清单非法、入口缺失、导入报错、`load()` 抛异常 |

**排错顺序**

1. 看插件中心顶部的红色区块——清单级错误会显示在这里。
2. 选中该插件，详情里有完整错误信息。
3. 页面加载失败会在页面区域显示 QML 的真实错误（含行列号）。

**常用的环境变量**

| 变量 | 作用 |
| --- | --- |
| `DSH_HOME` | 覆盖 harness home（默认 `~/.dsh`） |
| `CODEBUDDY_ACCOUNTS_DIR` | 覆盖 CodeBuddy 快照库目录 |
| `DSH_CODEBUDDY_AUTH_FILE` | 覆盖 CodeBuddy 凭据文件路径 |

## 9. 自查清单

提交插件前逐项确认：

- [ ] `plugin.json` 里 `id` 合法且唯一，`version` 格式正确
- [ ] `apiVersion` 是 `1`
- [ ] `entry` / `page` 是插件目录内的相对路径，文件真的存在
- [ ] 用到的每一种能力都写进了 `permissions`
- [ ] 声明了 `fs:read` / `fs:write`，且给出了对应的 `paths` 根目录
- [ ] 入口提供了 `load(api)`，返回值为插件实例（或 `None`）
- [ ] 页面同时处理了 `onInstanceChanged` 与 `onCompleted`
- [ ] 没有直接访问文件系统、网络或执行命令——都走 `api`
- [ ] 所有失败路径都返回带 `message` 的结果，而不是抛异常或静默返回 `None`
- [ ] 在本机插件中心里确认状态为「已启用」，页面正常渲染

---

## 参考实现

`src/codex_switch/builtin_plugins/codebuddy-accounts/` 是一个完整的示例：
它声明了文件权限与 `paths`、提供了页面、通过调用桥与界面交互，
可以作为编写新插件的起点。
