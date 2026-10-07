# codex-switch 仓库体检报告（问题清单 + 优化方案）

- **change_name**：`codex-switch-health-checkup`
- **目标仓库**：`F:\编程\codex-switch`
- **本轮形态**：**只读体检**。本报告是唯一交付物，仓库源码/脚本/配置/测试/README 一律未被修改。
- **依据**：`proposal.md` §7（A1–A12）、`design.md` §0–§8（大纲、条目模板、单源规则）、`tasks.md` T1–T12 + T13a/T13b + T14a/T14b/T14c。
- **维度优先级（固定序）**：① 正确性与稳定性 > ② 测试与工程化 > ③ 依赖与安全配置 > ④ 重复逻辑与复杂度 > ⑤ 文档。
- **编号体系**：`F<维度号>-<两位序号>`，`F2-…`～`F6-…` 对应 §2–§6；`F1` 保留给 §1 执行记录，不使用。
- **单源规则**：只有 §2–§6 产生条目；§7 是索引表、§8 是聚合表，二者均不产生条目、不复制四要素。
- **严重级别四级**：阻断 / 高 / 中 / 低。

---

## §0 只读基线

本节为纯事实记录，**不产生条目**。所有命令均为只读 git 子命令，未执行任何 git 写操作。

### §0.1 分支与 HEAD

实际执行的命令与原始输出：

```console
$ git rev-parse --abbrev-ref HEAD
main
$ git rev-parse HEAD
e2e3879ef05b96211558fc1ca0710a34221424b6
```

- 当前分支：`main`；HEAD 提交：`e2e3879ef05b96211558fc1ca0710a34221424b6`（`feat(codebuddy): 多账号适配 DSH 多开…`，9 files changed, 656 insertions(+), 40 deletions(-)）。
- 仓库此前无可对比基线提交，工作区改动处于「做完未落库」状态（与规格卡 problem 第 1 条一致）。

### §0.2 `git status --porcelain` 原样输出

```console
$ git status --porcelain
 M src/codex_switch/builtin_plugins/dsh-multi/entry.py
 M src/codex_switch/ui_v2/controller.py
 M src/codex_switch/ui_v2/plugin_bridge.py
 M src/codex_switch/ui_v2/qml/AppShell.qml
 M src/codex_switch/ui_v2/qml/components/AppDrawer.qml
 M src/codex_switch/ui_v2/qml/components/FormRenderer.qml
 M src/codex_switch/ui_v2/workspace.py
?? .memsearch/
?? CLAUDE.md
?? openspec/
?? scripts/run_tests_writable_tmp.py
?? src/codex_switch/dsh_config.py
```

`git diff --stat`（已跟踪文件的汇总）：

```console
$ git diff --stat
 .../builtin_plugins/dsh-multi/entry.py             | 51 ++++++++++++++++++++++
 src/codex_switch/ui_v2/controller.py               | 11 +++++
 src/codex_switch/ui_v2/plugin_bridge.py            | 17 ++++++++
 src/codex_switch/ui_v2/qml/AppShell.qml            | 11 +++++
 .../ui_v2/qml/components/AppDrawer.qml             | 14 ++++++
 .../ui_v2/qml/components/FormRenderer.qml          |  8 +++-
 src/codex_switch/ui_v2/workspace.py                | 14 ++++++
 7 files changed, 125 insertions(+), 1 deletion(-)
```

### §0.3 6 个未提交文件逐个 `git diff --stat`

规格卡声明的 6 个源码改动文件（4 改 2 增）实测摘要：

| # | 文件 | 状态 | 实测 `git diff --stat` / 行数 |
| --- | --- | --- | --- |
| 1 | `src/codex_switch/builtin_plugins/dsh-multi/entry.py` | 修改 | `1 file changed, 51 insertions(+)` |
| 2 | `src/codex_switch/ui_v2/controller.py` | 修改 | `1 file changed, 11 insertions(+)` |
| 3 | `src/codex_switch/ui_v2/plugin_bridge.py` | 修改 | `1 file changed, 17 insertions(+)` |
| 4 | `src/codex_switch/ui_v2/workspace.py` | 修改 | `1 file changed, 14 insertions(+)` |
| 5 | `src/codex_switch/dsh_config.py` | 新增（未跟踪） | 223 行（按 UTF-8 字节统计 `LF` 计数实测 223） |
| 6 | `scripts/run_tests_writable_tmp.py` | 新增（未跟踪） | 49 行 |

规格卡未声明、但工作区实测存在的**额外**未提交改动（原地保留、本报告一并记录）：

| 文件 | 状态 | 实测摘要 |
| --- | --- | --- |
| `src/codex_switch/ui_v2/qml/AppShell.qml` | 修改 | `1 file changed, 11 insertions(+)` |
| `src/codex_switch/ui_v2/qml/components/AppDrawer.qml` | 修改 | `1 file changed, 14 insertions(+)` |
| `src/codex_switch/ui_v2/qml/components/FormRenderer.qml` | 修改 | `1 file changed, 8 insertions(+), 1 deletion(-)` |
| `.memsearch/` | 新增（未跟踪，非源码） | 40,388 字节；含 `.memsearch/memory/2026-10-07.md` |
| `CLAUDE.md` | 新增（未跟踪，非源码） | 16,401 字节 |

**口径说明（与任务的非阻塞建议 3 一致）**：**基线集合 = 规格卡声明的 6 个源码改动文件**；`openspec/changes/` 下既有规划产物（含 `probe.md` 与本变更三件套/本报告）**不计入基线集合**。上述 3 个 QML 改动与 `.memsearch/`、`CLAUDE.md` 为实测发现但规格卡未声明，按现状原地保留、不修改、不提交、不回滚，仅在此如实记录。

### §0.4 授权写入区域声明

**本变更目录 `openspec/changes/codex-switch-health-checkup/` 是本次唯一被授权的写入区域；其下文件（由 P 产出的 `proposal.md`/`design.md`/`tasks.md` 与本轮新增的 `report.md`）不计入仓库既有改动集合。**

本轮实际写入清单：`report.md`（本文件）。另在本目录内产生过 5 个执行用临时输出文件（`.t2-unittest-out.txt`、`.t3-runner-out.txt`、`.t3-venv-out.txt`、`.cmp-t2.txt`、`.cmp-t3.txt`），已在提交前全部删除（见 §1.4 与 §9 收尾记录），未落库。

### §0.5 `openspec/changes/probe.md` 规划期残留

`openspec/changes/probe.md` **实测存在**（8 行，内容为「计划写探针（可删除）」，自述「P 阶段为验证 `plan-guard` 写护栏是否已放行 `openspec/changes/**`」）。`design.md` §8.2 称该文件「已放行并清理」、P 交接亦称「已不在目录中」，与实测不一致——本报告**原样记录该不一致，不修正计划文本（修正属 P 职责）**。该文件属规划期探针残留、非本轮交付物，**已原地保留、未删除**，且按 §0.3 口径不计入基线集合。

---

## §1 验收硬标准执行记录

本节为纯事实与结论记录，**不产生条目**（`F1` 保留不使用）。执行日期：2026-10-07；解释器：`python` → Python 3.13.2。

### §1.1 验收硬标准一：测试套件单命令执行（A3）

**唯一判定命令口径**：验收硬标准一的**判定命令**是

```powershell
python -m unittest discover -q -s tests
```

**该命令的退出码单独决定**验收硬标准一是否满足。同节另行的 `python -m compileall -q main.py src tests` **仅为前置编译检查记录，不计入**硬标准。

实测执行（原样命令、原始输出摘要）：

```console
$ python -m unittest discover -q -s tests
...
Ran 643 tests in 35.481s
FAILED (errors=20, skipped=92)

$ echo $LASTEXITCODE
1
```

| 项 | 实测值 |
| --- | --- |
| 判定命令 | `python -m unittest discover -q -s tests` |
| **退出码** | **1**（→ 验收硬标准一**不满足**） |
| 计数行 | `Ran 643 tests in 35.481s` |
| 结果行 | `FAILED (errors=20, skipped=92)` |
| 通过 / 失败 | 通过 623（643 − 20 errors − 92 skipped 之外的口径按 unittest 原样记录）；**errors=20**、failures=0、skipped=92 |

**20 个失败（error）用例名清单**（原样，按字典序）：

1. `ERROR: setUpClass (test_codebuddy_plugin.ImportBridgeTests)`
2. `ERROR: setUpClass (test_plugin_viewmodel.OpenPluginFolderTests)`
3. `ERROR: setUpClass (test_terminal_input_ui.HistoryThroughUiTests)`
4. `ERROR: test_cli_history (unittest.loader._FailedTest.test_cli_history)`
5. `ERROR: test_component_actually_instantiates (test_plugin_viewmodel.PluginPageUrlTests)`
6. `ERROR: test_created_page_fills_the_host (test_plugin_viewmodel.PluginHostLayoutTests)`
7. `ERROR: test_native_path_would_be_misread_as_url_scheme (test_plugin_viewmodel.PluginPageUrlTests)`
8. `ERROR: test_page_blocks_do_not_overlap (test_plugin_viewmodel.PluginHostLayoutTests)`
9. `ERROR: test_page_path_is_converted_to_file_url (test_plugin_viewmodel.PluginPageUrlTests)`
10. `ERROR: test_script_runner_reexports_the_shared_helpers (test_dsh_multi.SharedProcessUtilTests)`
11. `ERROR: test_shell_keys_match_controller_section_order (test_plugin_viewmodel.PluginsPageQmlTests)`
12. `ERROR: test_stack_layout_page_count_matches_section_order (test_plugin_viewmodel.PluginsPageQmlTests)`
13. `ERROR: test_terminal (unittest.loader._FailedTest.test_terminal)`
14. `ERROR: test_terminal_image (unittest.loader._FailedTest.test_terminal_image)`
15. `ERROR: test_terminal_launch_spec (unittest.loader._FailedTest.test_terminal_launch_spec)`
16. `ERROR: test_terminal_logging (unittest.loader._FailedTest.test_terminal_logging)`
17. `ERROR: test_terminal_notify (unittest.loader._FailedTest.test_terminal_notify)`
18. `ERROR: test_terminal_review (unittest.loader._FailedTest.test_terminal_review)`
19. `ERROR: test_terminal_vm (unittest.loader._FailedTest.test_terminal_vm)`
20. `ERROR: test_ui_v2_workspace (unittest.loader._FailedTest.test_ui_v2_workspace)`

**首条 traceback 摘要**（`test_cli_history` 的导入链，其余 19 条同源）：

```text
ImportError: Failed to import test module: test_cli_history
  File "tests\test_cli_history.py", line 24, in <module>
    from codex_switch.ui_v2.terminal.cli_history import (
  File "src\codex_switch\ui_v2\__init__.py", line 17, in <module>
    from .app import run_app
  ... controller.py:31 -> viewmodels/__init__.py:9 -> viewmodels/terminal.py:14
  ... -> terminal/__init__.py:12 -> terminal/manager.py:32
  File "src\codex_switch\ui_v2\terminal\manager.py", line 32, in <module>
    from .screen import TerminalScreen
  File "src\codex_switch\ui_v2\terminal\screen.py", line 18, in <module>
    import pyte
ModuleNotFoundError: No module named 'pyte'
```

失败原因归类（对本次输出全文计数）：`ModuleNotFoundError: 'pyte'` **13 次**、`ModuleNotFoundError: 'PySide6'` **6 次**、`PermissionError` / `os error 5` / `Errno 13` **0 次**。即 20 个 error 全部由**缺失第三方依赖**导致，与临时目录权限无关。

**前置编译检查（单独记录，不计入硬标准一）**：

```console
$ python -m compileall -q main.py src tests
$ echo $LASTEXITCODE
0
```

| 项 | 实测值 |
| --- | --- |
| 前置检查命令 | `python -m compileall -q main.py src tests` |
| 退出码 | 0 |
| **是否计入验收硬标准一** | **不计入**（仅为同节前置编译检查记录） |

> 边界情形按 `design.md` §7 处置：本处 `compileall` 通过（0）但判定命令失败（1），**以判定命令退出码为准** → 硬标准一不满足。
> 依 `design.md` §2 第 4 条与 `proposal.md` §3 第 7 条，本轮**未安装任何依赖**；测试跑不通如实记录为环境/工程事实，未为凑「跑通」修改测试或装包。

**补充实测（严格用于归因，不作为硬标准证据）**：仓库自带虚拟环境 `.venv\Scripts\python.exe` 已装齐依赖（实测含 `pyte-0.8.2`、`pyside6_essentials-6.11.2`、`psutil-7.2.2`、`pywinpty-3.0.5`、`ttkbootstrap-1.20.3`），用该解释器执行同一命令串结果为：

```console
$ .venv\Scripts\python.exe -m unittest discover -q -s tests
Ran 1096 tests in 141.691s
OK (skipped=2)
$ echo $LASTEXITCODE
0
```

即：同一命令串换用装齐依赖的解释器后 **1096 通过、0 失败、退出码 0**。该事实用于 §1.2 / §3 的归因，**不改变**验收硬标准一以 `python -m unittest discover -q -s tests` 退出码为唯一判定的结论。

### §1.2 `scripts/run_tests_writable_tmp.py` 有效性结论（A4）

**单一结论：未解决。**

判定方法（`design.md` §3 §1.2）：对照「直接执行 `python -m unittest discover -q -s tests`」与「经该 runner 执行同一组测试」的结果差异。**「直接执行」一组复用 §1.1 的同一次执行结果**（同一命令串、同一 `-q` 标志），未另跑改良版命令。

两组执行对照：

| 组 | 命令 | 退出码 | 计数 | 结果行 | 20 个 error 用例集合 |
| --- | --- | --- | --- | --- | --- |
| A 直接执行（复用 §1.1） | `python -m unittest discover -q -s tests` | 1 | `Ran 643 tests in 35.481s` | `FAILED (errors=20, skipped=92)` | 见 §1.1 清单 |
| B 经 runner 执行 | `python scripts/run_tests_writable_tmp.py discover -q -s tests` | 1 | `Ran 643 tests in 35.745s` | `FAILED (errors=20, skipped=92)` | **与 A 逐条完全相同** |

**支撑证据**：

1. 两组 `^(ERROR|FAIL):` 用例名集合经排序后逐条比对，结果为 **`IDENTICAL`**（20/20 全等），即 runner **未修复任何一个失败用例**、也未引入新失败。
2. 本次执行输出中 `PermissionError` / `os error 5` / `Errno 13` 出现次数为 **0**（§1.1）。该 runner 的 docstring 自述目标是修「`mkdtemp` 建的目录不可写导致 `PermissionError`」，但本轮判定命令的运行结果里**不存在该类失败**，因此无失败可修。
3. 对 runner 机制的直接复现：在本机普通 `python` 下 `tempfile.mkdtemp()` 实测**可正常创建并写入**，且实测目录权限位已是 `0o777`（`stat.S_IMODE` 输出 `0o777`），与 runner 覆写的 `os.mkdir(name, 0o777)` 等价 → runner 的覆写在本环境**不产生任何行为差异**。

**对 `scripts/run_tests_writable_tmp.py:26-36` 的具体引用**（该脚本为工作区新增未提交文件，其存在本身即 §7 索引的评审对象）：

- `scripts/run_tests_writable_tmp.py:26-36` 定义 `_writable_mkdtemp(suffix="", prefix="", dir=None)`，循环 1000 次用 `os.mkdir(name, 0o777)` 创建临时目录（:32），仅处理 `FileExistsError`（:33-34）。
- `scripts/run_tests_writable_tmp.py:42` 在 `main()` 里执行 `tempfile.mkdtemp = _writable_mkdtemp` 做进程内猴子补丁。
- 与 `tempfile.mkdtemp` 的差异仅在于**目录权限位**（`0o777` 而非 `mkdtemp` 的默认 `0o700`），其余语义相同；由于本环境普通 `mkdtemp` 已得到 `0o777`，覆写无效。

**结论依据链**：真实失败原因为依赖缺失（`pyte` 13 次、`PySide6` 6 次），而非临时目录不可写；runner 只改目录权限、不改依赖解析，故两组结果必然相同 → **未解决**。

> 边界：未修改该脚本、未安装依赖（`design.md` §2 第 4 条、`tasks.md` T3 边界）。

### §1.3 `.tmp/` 不可访问目录影响判定（A5）

**单一判定：不会导致常规判定命令 `python -m unittest discover -q -s tests` 失败或异常退出；会导致仓库遍历类操作（递归列举、递归删除、备份/打包式扫描）失败。**

实测现象与复现命令：

```console
$ python -c "import os; os.listdir(r'.tmp\test-dsh-multi\test_concurrent_submission_is_refused-9l54vloh')"
PermissionError [WinError 5] 拒绝访问。: '.tmp\test-dsh-multi\test_concurrent_submission_is_refused-9l54vloh'
```

```console
$ cmd /c "dir /a /b \".tmp\test-dsh-multi\test_concurrent_submission_is_refused-9l54vloh\""
Access is denied.
$ icacls ".tmp\test-dsh-multi\test_concurrent_submission_is_refused-9l54vloh"
Successfully processed 0 files; Failed processing 1 files
```

关键实测细节：

- `os.listdir(<该目录>)` 抛 `PermissionError [WinError 5]`（即 `os error 5`）；
- 但 `os.stat(<该目录>)` **成功**返回 `st_mode=16895`，即目录条目本身可见、仅**内容读取**被拒；
- 因此**恰好 1 个**目录受影响：`.tmp/test-dsh-multi/test_concurrent_submission_is_refused-9l54vloh`；其同级目录（如 `...-4x2r8r0r` 等）可正常列出。

判定所依据的 `unittest discover` 执行结果**复用 §1.1 的同一次执行**（同一命令串、同一 `-q` 标志），未另跑改良版命令。依据：

1. §1.1 实际执行 `Ran 643 tests`、成功完成收集与运行（退出码 1 的成因是**依赖缺失**的 20 个 error），输出中 `PermissionError` / `os error 5` 计数为 **0**；
2. `unittest discover -s tests` 的收集范围是 `tests/` 目录，不遍历仓库根的 `.tmp/`，故该权限拒绝不在判定命令的代码路径上。

**影响范围结论**：

| 受影响 | 说明 |
| --- | --- |
| 受影响 | 仓库根递归遍历类工具/操作：编辑器与 AI 工具的全仓 `glob`（规划期已实测使全仓 glob 整体失败，改用 grep / 精确 read 可绕过）、`Remove-Item -Recurse`、递归备份/打包/清理脚本 |
| 不受影响 | `python -m unittest discover -q -s tests`（收集面为 `tests/`）、`python -m compileall -q main.py src tests`（显式路径）、按精确路径的 `read`/`grep` |
| 不受影响的原因 | `.tmp/` 已在 `.gitignore:12` 忽略，不进入 git 操作；`tests/` 下的测试各自新建临时子目录，不要求读取该历史残留目录 |

> 边界：只判定与记录，**未修改该目录权限、未删除 `.tmp/` 内容**（`tasks.md` T4 边界、`design.md` §2 第 5 条）。

### §1.4 执行用临时文件的产生与清理（如实记录）

为留存原始执行证据，本轮在本变更目录内产生过 5 个临时输出文件：

| 文件 | 用途 | 处置 |
| --- | --- | --- |
| `.t2-unittest-out.txt` | §1.1 判定命令的完整输出留档 | **已删除** |
| `.t3-runner-out.txt` | §1.2 经 runner 执行的完整输出留档 | **已删除** |
| `.t3-venv-out.txt` | §1.1 补充实测（venv 解释器）输出留档 | **已删除** |
| `.cmp-t2.txt` / `.cmp-t3.txt` | §1.2 两组 error 用例集合比对的中间文件 | **已删除** |

上表 5 个文件均为本轮自我产生的临时文件，落在唯一授权写入区内，已在提交前删除，未进入 git 历史。除此之外未删除、未移动、未修改仓库任何文件（含 `openspec/changes/probe.md`）。

---

## §2 维度① 正确性与稳定性

> 取证面：异常吞并、静默失败、资源未释放、路径与编码边界、平台分支、并发与进程树管理。每条给出「触发条件 → 错误后果」。

### F2-01 `dsh_config.py` 模块与函数 docstring 含非法转义序列，会触发 SyntaxWarning 并在严格告警口径下变成硬失败

- **问题**：docstring 内使用了 Markdown 反引号转义写法 `` \`\` `` / `` \` ``，但 docstring 不是 raw 字符串，Python 将 `\`` 解析为非法转义序列并发出 `SyntaxWarning`（在 `-W error::SyntaxWarning` 或 `compileall` 严格口径下直接变成 `SyntaxError` 而编译失败）。
- **证据**：
  - `src/codex_switch/dsh_config.py:1`（模块 docstring 起始行，含 `` \`\`llm-pi-ai.providers.codex-switch\`\` ``）
  - `src/codex_switch/dsh_config.py:4`（`` \`\`llm-pi-ai.providers.codex-switch\`\` 和 \`\`agent-default-model\`\` ``）
  - `src/codex_switch/dsh_config.py:29`、`src/codex_switch/dsh_config.py:32`（`` \`\`apiKeyEnv\`\` ``）
  - 实测（`python -W always -m compileall -f -q main.py src tests`）输出：`src\codex_switch\dsh_config.py:1: SyntaxWarning: invalid escape sequence '\`'`、`src\codex_switch\dsh_config.py:29: SyntaxWarning: invalid escape sequence '\`'`
  - 实测（`python -W error::SyntaxWarning -c "import py_compile; py_compile.compile(r'src\codex_switch\dsh_config.py', doraise=True)"`）→ 抛 `py_compile.PyCompileError: SyntaxError: invalid escape sequence '\`'`，退出码 1
- **影响面 / 严重级别**：正确性（编译期告警/失败）· 可维护性 / **中**
- **建议改法**：把 `src/codex_switch/dsh_config.py:1` 与 `:29` 的函数/模块 docstring 改为 raw 字符串（`r"""..."""`），或把 `` \`\` `` 换成普通字符（如直接写 `` ``` `` 之外的描述、或改用 `：` 分隔的纯文本）。预期收益：消除 2 处编译告警，使「`compileall` 零告警」可作为后续引入 lint / 类型检查门禁的前置条件；否则一旦在 CI 中加入 `-W error` 或严格 lint，该文件会直接编译失败。

### F2-02 `entry.py` 新增的 `except (plugins.PluginError, Exception)` 使前一个异常类型成为死代码并把捕获面放大到全部异常

- **问题**：`except (plugins.PluginError, Exception)` 中 `Exception` 已完全覆盖 `PluginError`（实测 `PluginError` 继承链为 `PluginError(DshError)` → `Exception`），该元组等价于 `except Exception`，使写入的窄类型约束完全失效；同时把 `KeyboardInterrupt`/`SystemExit` 之外的**一切**异常（含编程错误如 `AttributeError`、`TypeError`）都收敛为 `{"ok": False, "message": ...}`，用户只能看到 str(exc)，无法区分「环境不可用」与「代码 bug」。
- **证据**：
  - `src/codex_switch/builtin_plugins/dsh-multi/entry.py:277`：`except (plugins.PluginError, Exception) as error:`
  - `src/codex_switch/dsh_plugins.py:89`：`class PluginError(DshError):`（→ `DshError(Exception)`，见 `src/codex_switch/dsh_instances.py:92`）
  - `src/codex_switch/builtin_plugins/dsh-multi/entry.py:271-281`（该 try 块内还会调用 `self.api.invoke(...)`，其失败模式并非都被 `PluginError` 覆盖）
- **影响面 / 严重级别**：正确性（错误分类失效、故障不可诊断）· 稳定性 / **中**
- **建议改法**：改为 `except plugins.PluginError as error:`，并在其后另加一条 `except Exception as error:  # noqa: BLE001` 并**在返回消息中标注为「内部错误」**（或直接 `raise`）以区分两类失败；或在 `self.api.invoke` 调用点收敛为单一 `PluginError`。预期收益：恢复异常分类语义，让「插件目标不存在」（可自愈）与「代码缺陷」（需修）在日志与界面文案上可区分，便于排障。

### F2-03 `test_terminal.py` 用字节字面量写 `\u2022`，实际断言的是字面反斜杠序列而非真实项目符号

- **问题**：`b"\u2022"` 在**字节**字面量中不被识别为 Unicode 转义（该转义只对 `str` 生效），实测得到的是 6 个 ASCII 字符 `b'\\u2022'`。终端输出里真实出现的是 U+2022（`•`，UTF-8 为 `\xe2\x80\xa2`），因此这些用例喂给 `TerminalScreen` 的是**永远不会在生产输出中出现的数据**，断言通过只证明「该测试自洽」，不能证明真实项目符号行解析正确。触发条件：AI CLI 真实输出以 `•` 开头的行 → 相关解析路径（`annotated_blocks` 的续行归并、流式补齐时间戳）在实际数据上未被这些用例覆盖。
- **证据**：
  - `tests/test_terminal.py:405`：`screen.feed(b"\u2022 Called filesystem.read_text_file(...)\r\n")`
  - `tests/test_terminal.py:421`：`screen.feed(b"\u2022 Call")`
  - 同文件 `:370`、`:372` 使用 `str` 字面量 + `.encode()` 的**正确**写法（如 `"\u203a 现在项目做到哪了\r\n".encode()`），与 `:405`/`:421` 写法不一致
  - 实测：`python -W always -c "print(repr(b'\u2022'))"` → `b'\\u2022'`，并伴随 `SyntaxWarning: invalid escape sequence '\u'`（另见 `compileall` 输出报 `tests\test_terminal.py:405` 与 `:421` 两处告警）
  - 对比证据：`tests/test_terminal.py:399-400` 用 `r"\[\d{2}:\d{2}:\d{2}\] \u2022 call-one"` 的正则**能**匹配（正则引擎识别 `\u2022`），说明同一文件内两种语义混用
- **影响面 / 严重级别**：正确性（回归保护失效，给出虚假信心）· 可维护性 / **中**
- **建议改法**：把 `tests/test_terminal.py:405`、`:421` 改为与同文件 `:370`/`:372` 一致的写法，如 `screen.feed("• Called filesystem.read_text_file(...)\r\n".encode())` 或 `screen.feed(b"\xe2\x80\xa2 Called ...\r\n")`；建议同时加一条断言确认 `feed` 收到的首字节确实是 `\xe2`。预期收益：使该组终端解析断言真正覆盖生产数据形态，并消除 2 处 `SyntaxWarning`。

### F2-04 实例启动路径打开日志流后，异常退出的实例不会被关闭句柄，实测产生 ResourceWarning

- **问题**：`start()` 在启动前以 `open(plan.log_path, "wb")` 打开日志文件流并交给子进程作 stdout/stderr；句柄仅在 `_close_stream(instance.id)`（`:671`、`:802`、`:870`）中被关闭。触发条件：实例被启动但在状态机走到这三处之前就退出/测试替换了进程实现（如 `tests/test_dsh_multi.py:261-275` 的 `_FakePopen` 直接写文件、不消费该流）→ 句柄遗留到 GC 才回收。实测后果：完整测试运行输出中反复出现 `ResourceWarning: unclosed file <_io.BufferedWriter name='...\.tmp\test-dsh-multi\...\logs\dev.log'>`（`unittest/case.py:606` 发出的 `case.py:606: ResourceWarning` 共 3 条，分别指向 `test_each_start_truncates_the_previous_log-1c78ejl3`、`test_start_becomes_running_when_url_appears-3hsggux6`、`test_start_refuses_when_already_running-8yty4i4g` 的 `logs\dev.log`）。
- **证据**：
  - `src/codex_switch/dsh_instances.py:742`：`stream = open(plan.log_path, "wb")`
  - `src/codex_switch/dsh_instances.py:746-756`：`kwargs["stdout"] = stream` 后 `self._popen(plan.argv, **kwargs)`；`:757-762` 仅在 `OSError` 时 `stream.close()`
  - `src/codex_switch/dsh_instances.py:625-633`（`_close_stream` 定义）、`:671`、`:802`、`:870`（三处调用点）
  - `src/codex_switch/dsh_instances.py:766`：`self._streams[instance.id] = stream`
  - 实测证据：`python -m unittest discover -q -s tests` 的 stderr 中出现 `ResourceWarning: unclosed file <_io.BufferedWriter name='F:\编程\codex-switch\.tmp\test-dsh-multi\test_each_start_truncates_the_previous_log-1c78ejl3\logs\dev.log'>`（同类共 3 条）
- **影响面 / 严重级别**：稳定性（文件描述符泄漏）· 正确性 / **中**
- **建议改法**：在 `start()` 中把 `stream` 的关闭责任显式化——① 启动成功后立刻注册 `self._streams[instance.id] = stream` 并确保所有返回/异常分支都经过 `self._close_stream(instance.id)`；② 或在 `_FakePopen` 场景下让 `start()` 检测 `self._popen` 是否真正接管了该流，未接管时自行关闭。预期收益：消除测试运行中的 3 条 ResourceWarning，避免长生命周期进程（多开管理器）在反复启停实例后耗尽句柄。

### F2-05 「打开文件夹/URL」实现硬编码 Windows 专属 API，而发布矩阵包含 Linux 与 macOS 目标

- **问题**：`_open_path()` / `_open_url()` 直接调用 `os.startfile(target)`，而 `os.startfile` **只存在于 Windows**（本机实测 `hasattr(os, "startfile")` 为 `True`，在 Linux/macOS 上该属性不存在）。触发条件：在非 Windows 平台调用需打开文件夹或签到链接的功能（如 `Workspace.open_local_path`、`open_sign_in_url`、控制器 `_reveal_directory` 的 `explorer` 分支）→ 抛 `AttributeError: module 'os' has no attribute 'startfile'`，异常未被捕获（`_open_path`/`_open_url` 内无 try），直接冒泡。仓库 CI 与打包均覆盖这两个平台：`.github/workflows/release.yml:23-28` 的矩阵含 `ubuntu-22.04`/`linux-x64` 与 `macos-15-intel`/`macos-x64`，并由 `scripts/package_release.py --target` 产出对应发行包；测试之所以未暴露该问题，是因为 `tests/helpers.py:15` 设了 `CODEX_SWITCH_DISABLE_OPEN_URL=1` 使 `OPEN_URLS_ENABLED` 为 `False`（`workspace.py:2590`）从而提前 return（`:2604-2606`）。
- **证据**：
  - `src/codex_switch/ui_v2/workspace.py:2578`：`os.startfile(target)  # type: ignore[attr-defined]  # Windows-only target`（`_open_path`，函数定义见 `:2566`）
  - `src/codex_switch/ui_v2/workspace.py:2607`：`os.startfile(target)  # type: ignore[attr-defined]`（`_open_url`，函数定义见 `:2597`）
  - `src/codex_switch/ui_v2/workspace.py:2505-2510`（`open_local_path` → `:2509` 调用 `_open_path`）、`:798-803`（`open_sign_in_url` → `:802` 调用 `_open_url`）
  - `src/codex_switch/ui_v2/controller.py:1502-1510`：`import subprocess` 后 `subprocess.Popen(["explorer", str(path)], ...)`，同样为 Windows 专属命令（见 `:1485` `_reveal_directory`）
  - `.github/workflows/release.yml:19-28`（Windows/Linux/macOS 三目标矩阵）、`:60`（`scripts/package_release.py --target`）
  - `tests/helpers.py:15`、`src/codex_switch/ui_v2/workspace.py:2581-2592`（测试期关闭开关，掩盖了该缺陷）
- **影响面 / 严重级别**：正确性（非 Windows 平台功能直接抛异常）· 稳定性 / **高**
- **建议改法**：在 `workspace.py` 里为 `_open_path`/`_open_url` 增加平台分派：Windows 保留 `os.startfile`；`sys.platform == "darwin"` 用 `subprocess.Popen(["open", target])`；其他（Linux）用 `subprocess.Popen(["xdg-open", target])`；并把 `controller.py:1507-1510` 的 `explorer` 分支一并改为复用同一平台分派函数（消除两处实现分叉，与 §5 的 DRY 收敛同向）。同时对三个平台补一条「打开函数在各自平台被正确解析」的用例（可在关闭开关关闭的情况下断言分派到的命令名）。预期收益：修复两个已发布目标平台的按钮失效/崩溃；把平台差异收敛到单一函数，避免后续再出现同类分叉。

---

## §3 维度② 测试与工程化（lint / CI / 测试可在 Windows 跑通）

### F3-01 仓库完全没有 lint / 类型检查配置，代码风格与类型问题无自动化门禁

- **问题**：全仓库不存在任何 lint/类型检查配置文件，也没有把 lint 工具写入依赖。触发条件：任何人提交风格/类型问题代码 → CI 与本地均无任何检查会报出（本轮实测的 `SyntaxWarning`、字节字面量误用、`except (A, Exception)`、`os.startfile` 平台问题全都无法被现有工程化手段拦住）。
- **证据**：
  - `pyproject.toml:1-25`（全文仅 `[build-system]`、`[project]`、`[tool.setuptools.dynamic]`、`[tool.setuptools.packages.find]`、`[tool.setuptools.package-data]`，**无** `[tool.ruff]` / `[tool.mypy]` / `[tool.black]` 等段落）
  - 实测 grep `ruff|flake8|mypy|black|isort|pytest|pylint` 于 `pyproject.toml`、`requirements.txt`、`requirements-build.txt`、`README.md` → **零命中**
  - 实测文件存在性：`.flake8` → False、`.pre-commit-config.yaml` → False、`.editorconfig` → False、`setup.cfg` → False、`tox.ini` → False、`.pylintrc` → False
  - `.github/workflows/` 目录下**仅有** `release.yml`（无独立 lint 工作流）
  - 佐证零命中的真实后果：`python -W always -m compileall -f -q main.py src tests` 会报出 4 处 `SyntaxWarning`（`src/codex_switch/dsh_config.py:1`、`:29`、`tests/test_terminal.py:405`、`:421`），而现有工程化链路不会运行严格告警口径
- **影响面 / 严重级别**：可维护性（缺陷前移失效）· 正确性 / **中**
- **建议改法**：在 `pyproject.toml` 增加 `[tool.ruff]` 段落，先只启用安全且低噪声的规则集（建议 `line-length = 100`、`target-version = "py311"`，`lint.select = ["E", "F", "W", "BLE", "UP", "SIM"]`，并 `extend-exclude = ["src/codex_switch/ui/**"]` 以避开旧 Tk 层），把 `ruff` 加到 `requirements-build.txt`（不新增运行期依赖）；随后在 `.github/workflows/` 新增一个 `lint.yml`，触发条件为 `pull_request` 与 `push` 到主干，步骤为 `pip install -r requirements-build.txt` + `ruff check .`。预期收益：`F`/`E`/`W` 类规则可直接捕获本报告 F2-01、F2-03；`BLE` 规则可直接捕获 F2-02 与 §5 的宽泛捕获；且新增工作流不受现有 `release.yml` 只在 tag 触发的影响（见 F3-02）。

### F3-02 CI 只在手动触发与 tag 时执行测试，无 push/PR 门禁、无 lint 步骤，且测试命令与文档口径不一致

- **问题**：唯一工作流 `release.yml` 的触发条件仅 `workflow_dispatch` 与 `v*` tag，主干提交与 PR 完全没有自动化校验；工作流内无 lint/类型检查步骤；其测试命令用 `-v` 而 `README.md` 与本轮验收判定命令用 `-q`，两处口径不一致。触发条件：日常提交（非 tag）→ 测试与静态检查全部不执行；按 CI 日志排查时与文档给出的命令串不同，无法逐字复现。
- **证据**：
  - `.github/workflows/release.yml:3-7`：`on:` 仅 `workflow_dispatch:` 与 `push: tags: ["v*"]`（**无** `pull_request` / `push: branches`）
  - `.github/workflows/release.yml:54-57`：唯一的测试步骤 `run: python -m unittest discover -v -s tests`（无 lint 步骤，工作流其余步骤为 Qt 运行库安装 `:39-44`、依赖安装 `:46-49`、`Verify Qt import` `:51-52`、打包 `:59-60`、上传 `:62-66`）
  - `README.md:169-170`：文档口径为 `python -m compileall -q main.py src tests` + `python -m unittest discover -q -s tests`
  - 同仓唯一工作流佐证：`Get-ChildItem .github/workflows` 仅返回 `release.yml`
- **影响面 / 严重级别**：可维护性（回归只能在发版时暴露）· 正确性 / **中**
- **建议改法**：新增 `.github/workflows/ci.yml`，`on: [push, pull_request]`（主干与 PR 分支），矩阵沿用 `windows-2022`/`ubuntu-22.04` 两档，步骤为：安装 `requirements.txt` → `python -m compileall -q main.py src tests` → `python -m unittest discover -q -s tests`（与 `README.md:170` 逐字一致，替换 CI 现有的 `-v`）；并把 F3-01 的 `ruff check .` 作为前置步骤。预期收益：让 F3-03 暴露的「文档命令跑不通」类问题在 PR 阶段即被拦住，而不是等到打 tag 才发现测试是红的；同时统一命令口径，使 CI 日志可直接与文档/验收记录比对。

### F3-03 文档给出的「一条命令跑通」测试入口在本机默认解释器下实测失败（退出码 1）

- **问题**：`README.md` 把 `python -m unittest discover -q -s tests` 记为本地测试入口，但按该文档字面执行时，仓库根默认 `python`（Python 3.13.2，无 `pyte`/`PySide6`）会收集到 `Ran 643 tests` 并返回 `FAILED (errors=20, skipped=92)`、**退出码 1**。触发条件：新维护者按 README 执行 → 直接得到红色结果，无法确认基线健康（正是 user_story 2 与验收硬标准一要解决的场景）；且 92 个 skipped 使「部分模块根本没跑」这一事实被结果行掩盖。虽然仓库自带 `.venv` 装齐依赖后同一命令串返回 `Ran 1096 tests / OK (skipped=2)`、退出码 0，但**文档没有任何一处提示必须使用 `.venv` 解释器**（`README.md:157` 仅写「需要 Python 3.11+」）。
- **证据**：
  - `README.md:166-171`：`## 本地测试` 段落，`:169` `python -m compileall -q main.py src tests`、`:170` `python -m unittest discover -q -s tests`
  - `README.md:155-164`：`### 源码运行`，`:157` 仅声明「需要 Python 3.11+」，`:160` 指向 `python -m pip install -r requirements.txt`（未提 `.venv`）
  - 实测（默认 `python`，Python 3.13.2）：`Ran 643 tests in 35.481s` / `FAILED (errors=20, skipped=92)` / 退出码 1；20 个 error 的名单与首条 traceback 见 §1.1（`ModuleNotFoundError: No module named 'pyte'` 13 次、`'PySide6'` 6 次）
  - 实测（`.venv\Scripts\python.exe`，已装 `pyte-0.8.2`/`pyside6_essentials-6.11.2`/`psutil-7.2.2`/`pywinpty-3.0.5`/`ttkbootstrap-1.20.3`）：`Ran 1096 tests in 141.691s` / `OK (skipped=2)` / 退出码 0
  - 依赖缺失的根因见 §4 F4-01（`pyproject.toml:13-16` 未声明 `pyte`/`pywinpty`/`psutil`）
- **影响面 / 严重级别**：正确性（验收硬标准一在文档口径下不满足）· 可维护性 / **高**
- **建议改法**：在 `README.md:166-171` 的测试段落中显式给出可跑通的解释器与前置条件：① 把命令改为 `.venv\Scripts\python.exe -m unittest discover -q -s tests`（Windows）/ `./.venv/bin/python`（POSIX），或在段落开头加一行「先激活虚拟环境：`.venv\Scripts\Activate.ps1`（Windows）/ `source .venv/bin/activate`（POSIX）」；② 增加一句「未装齐 `requirements.txt` 时会出现约 20 个 `ModuleNotFoundError` 导致的 error，属依赖未装齐，不是代码回归」，并给出期望基线数字（643/1096 与 OK）。预期收益：让「一条命令跑通」在文档口径下真正成立，新维护者可直接确认基线健康；同时把 F4-01 的依赖声明缺口在文档侧显式标注，避免误判为代码缺陷。

### F3-04 两套测试临时根都要求「仓库目录可写」，使测试无法在只读检出/只读挂载下运行

- **问题**：测试临时目录全部落在仓库工作树内（`.test-temp/` 与 `.tmp/<name>/`），而非系统临时目录，因此测试套件**要求仓库根目录可写**。触发条件：以只读方式检出仓库（如 CI 的只读挂载、`chmod -R a-w`、只读网络盘）执行测试 → `tests/helpers.py:30` 的 `TEST_ROOT.mkdir()` 与各模块的 `TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)` 抛 `PermissionError`，测试在收集/建目录阶段即失败。这一约束是**有意的**（模块注释明确「受限环境下系统临时目录会被拒绝写入」），但代价是测试对检出位置的可写性产生硬依赖。
- **证据**：
  - `tests/helpers.py:25`：`TEST_ROOT = Path.cwd() / ".test-temp"`；`:30-31`：`TEST_ROOT.mkdir(exist_ok=True)` + `path.mkdir(parents=True, exist_ok=True)`（`workspace_tempdir`）；`:91-93`（`git_clone_available` 路径下同样的 `TEST_ROOT.mkdir`）
  - `tests/test_dsh_multi.py:32`（`TEST_TMP_ROOT = PROJECT_ROOT / ".tmp" / "test-dsh-multi"`）、`:40`（`TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)`）
  - `tests/test_plugins.py:36`、`:44`；`tests/test_codebuddy_plugin.py:26`、`:34`；`tests/test_codebuddy_accounts.py:24`、`:35`；`tests/test_cli_history.py:29`、`:33`（同一模式）
  - 设计依据（说明为何不用系统临时目录）：`tests/test_plugins.py:42` 注释「受限环境下系统临时目录会被拒绝写入」；`tests/test_dsh_multi.py:39` 同义  - 隐式依赖的佐证：`tests/helpers.py:18-22` 依赖 `Path(__file__).resolve().parents[1]` 推导 `ROOT`，测试必须从仓库内运行
- **影响面 / 严重级别**：可维护性（限制可用执行环境）· 稳定性 / **低**
- **建议改法**：把临时根改为「可配置 + 惰性回退」：在 `tests/helpers.py` 引入 `TEST_ROOT = Path(os.environ.get("CODEX_SWITCH_TEST_ROOT") or (Path.cwd() / ".test-temp"))`，并让各模块统一改从 `helpers` 取根（与 §5 F5-02 的收敛改法同一动作）；同时在 README 测试段落说明可用 `CODEX_SWITCH_TEST_ROOT` 指向可写目录。预期收益：在只读检出与受限沙箱下测试仍可运行，同时保留「默认落在仓库内、已被 `.gitignore:11-12` 忽略」的现状，不改变现有开发习惯。

### F3-05 `tests/__pycache__/` 存在无对应源码的 `_leak_guard` 编译产物（陈旧残留）

- **问题**：`tests/__pycache__/` 下有 `_leak_guard.cpython-313.pyc`，但仓库（`src`/`tests`/`scripts`）内 grep `_leak_guard` **零命中**、且不存在 `tests/_leak_guard.py`——即该模块的源码已被删除而 `.pyc` 残留。触发条件与后果：`unittest discover` 的收集以 `.py` 为源，`test*.pyc` 之外的孤立 `.pyc` 不会被当作测试模块导入，因此**不影响本次测试收集**（§1.1 实测成功收集 643、`.venv` 口径 1096）；真实影响是干扰本地排障（令人误判存在一个 `_leak_guard` 测试模块）与目录卫生，`__pycache__/` 已被 `.gitignore:2` 忽略故未被提交。
- **证据**：
  - 实测 `Get-ChildItem tests\__pycache__\*.pyc` 中 `_leak_guard.cpython-313.pyc` 存在；其余 28 个 `.pyc` 均能一一对应到 `tests/*.py`
  - 实测孤立产物计算：`$pyc -notin $py` → `ORPHAN_PYC: _leak_guard`（唯一一项）
  - 实测 grep `_leak_guard` 于 `src`、`tests`、`scripts` 全部 `.py` → 零命中
  - `.gitignore:2`：`__pycache__/`
  - §1.1 实测佐证不影响收集：`Ran 643 tests`（默认口径）与 `Ran 1096 tests`（venv 口径）均正常完成收集阶段
- **影响面 / 严重级别**：可维护性（排障噪声） / **低**
- **建议改法**：确认 `_leak_guard` 确无源码后，删除 `tests/__pycache__/_leak_guard.cpython-313.pyc`（或整体清理 `tests/__pycache__/`，该目录已被忽略、可安全重建）；若该模块是被误删的活跃守卫，则应从 git 历史恢复源码。预期收益：消除本地排障时的假模块信号；操作无风险（被忽略目录，不进入版本库）。**注**：本轮为只读体检，未执行该删除。

---

## §4 维度③ 依赖与安全配置

### F4-01 三份依赖清单互相不一致，`pip install .` 装出的环境无法运行测试与 AI 终端功能

- **问题**：仓库存在三份声明范围不同的依赖清单：`pyproject.toml` 只声明 2 个运行期依赖，`requirements.txt` 额外声明 3 个（AI 终端所需），`requirements-build.txt` 再额外钉住 `pyinstaller`。触发条件：使用者按 `README.md:160` 执行 `python -m pip install -r requirements.txt`（或按打包路径 `pip install .`）→ 两种安装方式得到的依赖集合不同；按 `pip install .`（或仅按 `pyproject.toml`）装出的环境里 `pyte`/`pywinpty` 缺失，直接导致 §1.1 实测的 20 个 error（`pyte` 13 次、`PySide6` 6 次中的 `pyte` 部分）与终端功能不可用。
- **证据**：
  - `pyproject.toml:13-16`：`dependencies = ["PySide6-Essentials>=6.8,<6.12", "ttkbootstrap>=1.10,<2"]`（**仅 2 项**）
  - `requirements.txt:1-17`：`PySide6-Essentials>=6.8,<6.12`（:1）、`ttkbootstrap>=1.10,<2`（:4）、`pywinpty>=2.0.0`（:15）、`pyte>=0.8.0`（:16）、`psutil>=5.9.0`（:17）（**5 项**）
  - `requirements-build.txt:1-9`：`pyinstaller==6.19.0`（:1）叠加上述 5 项（:2、:4、:7、:8、:9）（**6 项**）
  - 实测缺依赖后果（§1.1）：`ModuleNotFoundError: No module named 'pyte'` 13 次、`'PySide6'` 6 次；实测系统 `python` 的模块可用性为 `pyte False / PySide6 False / psutil True / pywinpty False / ttkbootstrap True`，与「只装了 `pyproject.toml` 那 2 项 + 系统自带 `psutil`」的形态吻合
  - `README.md:159-164`（源码运行指引指向 `requirements.txt`，未解释与 `pip install .` 的差异）；`src/codex_switch/ui_v2/terminal/screen.py:18`（`import pyte`，模块级导入，缺失即整个 `ui_v2` 包导入失败）
- **影响面 / 严重级别**：正确性（安装路径不同即跑不起来）· 可维护性 / **高**
- **建议改法**：以 `pyproject.toml` 为**单一事实来源**：把 `pywinpty>=2.0.0`、`pyte>=0.8.0`、`psutil>=5.9.0` 加入 `pyproject.toml:13-16` 的 `dependencies`（并按平台加条件标记，如 `pywinpty>=2.0.0; sys_platform == "win32"`，因为 ConPTY 仅 Windows 需要）；随后把 `requirements.txt` 收敛为一行 `-e .`（或保留展开但加注释「与 `pyproject.toml` 保持一致」），`requirements-build.txt` 只保留 `pyinstaller==6.19.0` 并 `-r requirements.txt` 叠加；同时在 `tests/test_encoding.py:25-41` 已有的「requirements 必须 ASCII」测试旁新增一条断言：`requirements.txt` 声明的包集合 ⊆ `pyproject.toml` 的 `dependencies`（防再次漂移）。预期收益：`pip install .` 与 `pip install -r requirements.txt` 得到一致环境，消除「按文档装完仍 20 个 error」这一最大摩擦点；平台条件标记避免在 Linux/macOS 强行安装 `pywinpty`。

### F4-02 `.gitignore` 未覆盖新增的本地状态目录，`git status` 长期被非交付物污染

- **问题**：工作区实测新增了两个未被忽略的本地状态项：`.memsearch/`（含 `.memsearch/memory/2026-10-07.md`，40,388 字节，内容为 AI 会话历史纪要）与 `CLAUDE.md`（16,401 字节，实测与根 `AGENTS.md` 的 SHA-256 **完全相同**）。触发条件：任何人执行 `git add -A` / `git add .` → 会把会话历史纪要（含完整对话摘要、会话 UUID、本机绝对路径）与一份 `AGENTS.md` 的重复副本提交进仓库。这与 `.gitignore:23-31` 已经忽略 `.codex/`、`.serena/`、`.claude/`、`.pmnote/`、`/AGENTS.md` 的既有意图不一致——同类项漏了两个。
- **证据**：
  - 实测 `git status --porcelain` 含 `?? .memsearch/` 与 `?? CLAUDE.md`（§0.2）
  - 实测 `git check-ignore -v .memsearch` → 退出码 1（**未忽略**）；`git check-ignore -v .memsearch/memory/2026-10-07.md` → 退出码 1（**未忽略**）；`git check-ignore -v CLAUDE.md` → 退出码 1（**未忽略**）
  - 对照：`git check-ignore -v AGENTS.md` → `.gitignore:31:/AGENTS.md`（已忽略）
  - `.gitignore:23-31`（既有「Local runtime and agent state」段落：`.codex/`、`.serena/`、`.recovered/`、`.claude/`、`.mcp.json`、`.pmnote/`、`pmnote/`、`/AGENTS.md`）
  - 实测文件内容与体量：`.memsearch/memory/2026-10-07.md` 40,388 字节（会话纪要，含 `session:/turn:/db:` 元信息行与多轮工具调用记录）；`CLAUDE.md` 与 `AGENTS.md` 的 SHA-256 均为 `082FB9817F8647DECE742C1698BABF40F3EC54ECC7996EAF758B3A751CB0270B`（内容相同、仅文件名不同）
- **影响面 / 严重级别**：安全（本机路径与会话内容外泄风险）· 可维护性 / **中**
- **建议改法**：在 `.gitignore:23-31` 的「Local runtime and agent state」段落补入 `.memsearch/` 与 `/CLAUDE.md`（`CLAUDE.md` 是 `AGENTS.md` 的重复副本，本就不该进入版本库；若确需纳管，应改为软链或删除以保留单一来源）。预期收益：`git status` 恢复干净、`git add -A` 不再有误提交会话纪要与重复文档的风险；同时消除「同一份 AGENTS 内容存在三个副本（`.gitignore` 忽略的根 `AGENTS.md`、未忽略的 `CLAUDE.md`、已跟踪的 `src/codex_switch/assets/AGENTS.md`）」的困惑（另见 F6-03）。

### F4-03 API Key 通过进程环境变量注入且被子进程全量继承，属设计取舍但缺少收窄手段

- **问题**：`write_profile_to_dsh()` 把 API Key 写入**当前进程**环境变量 `os.environ["CODEX_SWITCH_DSH_API_KEY"]`，而写入的 YAML 只保存 `apiKeyEnv` 引用（这是**有意的设计**：让配置文件可安全提交/备份）。真实风险边界在继承面：插件启动 DSH 时执行 `env = dict(os.environ)` 并把整个环境交给子进程，因此该 Key 会被**所有**后续子进程继承（含脚本运行、PTY 终端会话）；Key 也无法在写入后被撤回，进程存活期间持续有效。触发条件：写入 Profile 后启动任意子进程/终端 → Key 出现在其环境中（可被该子进程 `/proc/<pid>/environ` 类机制或误打印读走）。
- **证据**：
  - `src/codex_switch/dsh_config.py:56`：`os.environ[DSH_API_KEY_ENV] = api_key`（常量定义 `:20` `DSH_API_KEY_ENV = "CODEX_SWITCH_DSH_API_KEY"`）
  - `src/codex_switch/dsh_config.py:85`：`f"      apiKeyEnv: {DSH_API_KEY_ENV}"`（配置文件只存引用名，注释见 `:31-33` 说明该设计意图）
  - `src/codex_switch/builtin_plugins/dsh-multi/entry.py:241-250`：`env = dict(os.environ)` → `subprocess.Popen(argv, env=env, ...)`（全量继承）
  - `src/codex_switch/ui_v2/workspace.py`（未提交改动）`write_dsh_profile` 返回值文案 `detail` 明确写着「API Key 已注入当前进程环境」
  - 掩盖/对比：`src/codex_switch/proxy/sanitize.py:6-17`（已有敏感头与 `sk-`/`api_key=` 文本的脱敏实现），说明仓库有脱敏意识，但该环境变量注入路径未接入
- **影响面 / 严重级别**：安全（凭据暴露面随子进程数量扩大） / **低**
- **建议改法**：① 把 `entry.py:241` 的 `env = dict(os.environ)` 收窄为显式白名单（只透传必要的 DSH/PATH/HOME 等变量，必要时单独 `env[DSH_API_KEY_ENV] = os.environ.get(DSH_API_KEY_ENV, "")`），使 Key 只注入真正需要它的 DSH 子进程；② 在 `write_profile_to_dsh` 的返回路径上接 `sanitize.mask_secret`（`src/codex_switch/proxy/sanitize.py:20-26`），保证任何日志/界面回显都不出现完整 Key；③ 在 `dsh_config.py:28-57` 的 docstring 中把「进程生命周期内有效、后继子进程继承」的风险写实，供后续决定是否改为一次性 `env` 传参而非 `os.environ`。预期收益：在不破坏「配置文件可提交」这一设计目标的前提下，把 Key 的暴露面从「进程树全部子进程」收窄到「DSH 子进程」；同时让该设计取舍有明确文档，避免被后续改动无意放大。

### F4-04 CI 引用第三方 action 未固定到 commit SHA，且工作流持有 `contents: write` 写权限

- **问题**：`release.yml` 引用的 5 个第三方/官方 action 全部使用浮动 tag（`@v4`/`@v5`/`@v2`）而非固定 commit SHA，同时该工作流的 `permissions` 为 `contents: write`（发布所需）。触发条件：任一被引用 tag 的上游仓库被接管/恶意改动（tag 可被重指向）→ 工作流在持有写权限的上下文中执行被篡改的代码，可改写仓库内容与发布产物。这是典型的供应链风险，且与「公开分发桌面工具、需要写 Release」的场景叠加。
- **证据**：
  - `.github/workflows/release.yml:9-10`：`permissions:` / `  contents: write`
  - `.github/workflows/release.yml:32`：`uses: actions/checkout@v4`
  - `.github/workflows/release.yml:35`：`uses: actions/setup-python@v5`
  - `.github/workflows/release.yml:63`：`uses: actions/upload-artifact@v4`
  - `.github/workflows/release.yml:80`：`uses: actions/download-artifact@v4`
  - `.github/workflows/release.yml:95`：`uses: softprops/action-gh-release@v2`
  - `.github/workflows/release.yml:69`（release job 的 `if: startsWith(github.ref, 'refs/tags/v')`，即写权限只在打 tag 时启用，缩小但未消除暴露窗口）
- **影响面 / 严重级别**：安全（供应链） / **中**
- **建议改法**：把上述 5 处 `uses:` 改为 `<owner>/<repo>@<40位commit SHA> # vX.Y.Z` 形式（由 renovate/dependabot 或 `pin-github-action` 类工具维护注释版本，便于升级）；把 `permissions` 从工作流级下移到 job 级，仅 `release` job 保留 `contents: write`，`build` job 显式声明 `permissions: contents: read`；在 PR 触发的 CI 工作流（见 F3-02）中一律使用 `contents: read`。预期收益：即使上游 tag 被重指向，工作流仍执行已审计的精确提交；写权限收敛到唯一需要它的 job，降低误用与横向移动面。

---

## §5 维度④ 重复逻辑与复杂度

### F5-01 原子写实现存在四套语义相同、写法各异的版本，其中一套与另一套的取舍理由直接冲突

- **问题**：仓库内有 4 处「写临时文件 → `os.replace` 原子替换」的实现，写法分三派：A 用 `tempfile.NamedTemporaryFile(dir=path.parent)`、B/C 用 `path.with_name(f".{path.name}.{os.getpid()}.tmp")` 自拼名。触发条件：需修改任一处的异常清理/编码/权限策略 → 必须四处同步修改，漏一处即产生行为分叉。**特别值得注意的冲突**：`codebuddy_core.py:165-166` 明确注释「临时文件名自己拼而不用 `tempfile.NamedTemporaryFile`：后者在某些受限环境下……」，而 `dsh_config.py:203-206` 恰好在同一仓库、同类场景下使用了 `tempfile.NamedTemporaryFile`——同一约束下两处采用相反结论，说明该取舍未被沉淀为公共实现。
- **证据**（逐处 `路径:行号` 与写法差异）：
  - ① `src/codex_switch/dsh_config.py:201-214`（`_atomic_write`）：`tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False)`（:203-206）→ `os.replace(temp, path)`（:211）；`except OSError:` 时 `temp.unlink(missing_ok=True)` 后 `raise`（:212-214）；**自带 `path.parent.mkdir(parents=True, exist_ok=True)`**（:202）
  - ② `src/codex_switch/dsh_instances.py:485-492`（`_atomic_write`）：`temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")`（:487）→ `open(temp, "w", encoding="utf-8", newline="\n")`（:490）→ `os.replace(temp, path)`（:492）
  - ③ `src/codex_switch/plugins/api.py:148-160`（`PluginAction.write_text`）：`temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")`（:152）→ `open(temp, "w", encoding=encoding, newline="\n")`（:155）→ `os.replace(temp, target)`（:157）；`except OSError` 时 `temp.unlink(missing_ok=True)`（:159）后包装为 `PluginActionError`
  - ④ `src/codex_switch/codebuddy_core.py:162-186`（`write_credential_file`）：`temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")`（:174）→ `open(temp_path, "w", encoding="utf-8", newline="\n")`（:176）→ `os.replace(temp_path, path)`（:178）；且 `:165-166` 注释明确给出**不用** `NamedTemporaryFile` 的理由
  - 差异点汇总：临时名生成方式（`NamedTemporaryFile` vs `with_name` 自拼）、初始权限（`mkstemp` 默认 `0o600` vs 受 `umask` 影响的默认）、父目录创建（仅 ① 自带）、失败清理（①③ 有、②④ 视分支而定）、编码参数（③ 可配 `encoding`，其余硬编码 `utf-8`）
- **影响面 / 严重级别**：可维护性（四处同步成本 + 语义漂移） / **中**
- **建议改法**：新增 `src/codex_switch/atomic_write.py`，导出单一 `atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8", make_parents: bool = False) -> None`，采用**受限环境安全**的写法（即 ④ 的自拼名 + `with_name`，因为 ④ 的注释给出了该环境下的实测理由），失败路径统一 `unlink(missing_ok=True)` 后重新抛出；随后把 ①②③④ 四处改为调用它。**收敛时必须保留的关键约束**：不使用 `tempfile.NamedTemporaryFile`（`codebuddy_core.py:165-166` 的受限环境约束）、保留各调用点现有编码（③ 需可配）。预期收益：一处修复即四处受益；消除「同仓内对同一环境约束给出相反结论」的认知负担；为后续引入 lint（F3-01）后统一加 `# noqa` 或类型标注提供单点。

### F5-02 测试侧存在两套临时根约定，且 `make_temp_dir` 辅助在 5 个测试模块中被逐份复制

- **问题**：测试临时根有两套并行约定——`tests/helpers.py:25` 的 `Path.cwd()/".test-temp"` 与各模块自建的 `PROJECT_ROOT/".tmp"/<name>`；并且「建根 + `mkdtemp` + 注册 `addCleanup(rmtree)`」这一辅助逻辑在 5 个模块里被逐份复制成同名函数 `make_temp_dir`。触发条件：需要调整临时根位置或清理策略（如 F3-04 的可配置化）→ 必须逐文件修改 5 处，漏一处即出现两套行为。
- **证据**：
  - 两套根：`tests/helpers.py:25`（`TEST_ROOT = Path.cwd() / ".test-temp"`，经 `:28-36` 的 `workspace_tempdir()` 上下文管理器使用）；`tests/test_dsh_multi.py:32`（`PROJECT_ROOT / ".tmp" / "test-dsh-multi"`）、`tests/test_plugins.py:36`（`... / "test-plugins"`）、`tests/test_codebuddy_plugin.py:26`（`... / "test-codebuddy-plugin"`）、`tests/test_codebuddy_accounts.py:24`（`... / "test-codebuddy-accounts"`）、`tests/test_cli_history.py:29`（`... / "test-cli-history"`）
  - 复制出的辅助函数：`tests/test_dsh_multi.py:38-43`、`tests/test_plugins.py:39-46`、`tests/test_codebuddy_plugin.py:33-36` 附近、`tests/test_codebuddy_accounts.py:32-37` 附近、`tests/test_cli_history.py:32-35` 附近——均为「`TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)` → `tempfile.mkdtemp(prefix=f"{case._testMethodName}-", dir=str(TEST_TMP_ROOT))` → `case.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))`」同一模式
  - `PROJECT_ROOT` 推导亦被复制：`tests/test_cli_history.py:19`、`tests/test_codebuddy_accounts.py:15`、`tests/test_codebuddy_plugin.py:21`、`tests/test_dsh_multi.py:27`、`tests/test_plugins.py:11`、`tests/test_plugin_viewmodel.py:14`、`tests/test_encoding.py:7`（7 处相同表达式 `Path(__file__).resolve().parents[1]`）
  - 另有直接复用旧约定的散点：`tests/test_plugins.py:617-619`（`PROJECT_ROOT / ".tmp"` + `mkdtemp(prefix="meipass-")`）、`tests/test_plugin_viewmodel.py:172-174`（`PROJECT_ROOT / ".tmp"` + `mkdtemp(prefix="reveal-")`）、`tests/test_codebuddy_accounts.py:518-520`（`PROJECT_ROOT / ".tmp" / "test-codebuddy-accounts"` + `mkdtemp(prefix="gbk-")`）
- **影响面 / 严重级别**：可维护性（5 份副本 + 2 套约定） / **中**
- **建议改法**：在 `tests/helpers.py` 中提供唯一实现并供全仓导入：`PROJECT_ROOT`（取代 7 处重复推导）、`TEST_ROOT`（可按环境变量覆盖，见 F3-04）、`make_temp_dir(case, *, prefix=None, name=None) -> Path`（内含 `mkdir` + `mkdtemp` + `addCleanup(rmtree)`）。随后删除 5 个模块内的同名副本并改为 `from tests.helpers import make_temp_dir`（`tests/test_terminal_image.py:30` 已有 `from tests.test_terminal import ...` 的跨模块导入先例，说明该导入路径可行）。预期收益：临时根策略只需改一处；F3-04 的可配置化随之自动覆盖全部模块；新测试无需再复制 5 行样板。

### F5-03 `ui_v2/workspace.py` 与 `controller.py` 的规模集中已产生可观测后果：函数内联导入与静默兜底吞掉失败模式

- **问题**：问题不在「行数多」本身，而在规模集中带来的两项可观测后果：① **函数内联导入**——`controller.py` 在函数体内 `import subprocess`（:1502）与 `from .workspace import ...`（:1496），导入发生在用户每次触发操作的调用路径上，且无法在模块级被测试的 `patch` 目标捕获（跨模块 monkeypatch 需按函数内符号名进行，使该平台专属行为难以做隔离测试，与 F2-05 的平台缺陷相互放大）；② **宽泛兜底吞掉失败模式**——`workspace.py` 内有 16 处 `except Exception`，其中 `:440` 与 `:2541` 附近的分支在捕获后**静默改用替代路径/替代值**，调用方无法区分「正常回退」与「上游真的坏了」。触发条件：上游接口行为变化 → 界面显示为「一切正常但数值不对」，排障只能靠读代码。规模数据（作为背景而非判据）：`workspace.py` 2668 行、`controller.py` 1769 行、`ui/app.py` 5264 行。
- **证据**：
  - 内联导入：`src/codex_switch/ui_v2/controller.py:1502`（`import subprocess`，位于 `_reveal_directory`，定义见 `:1485`）、`:1496`（`from .workspace import OPENS_ENABLED, record_opened_path`，同一函数内）、`:1371`（`from .qt_compat import QUrl`）、`:229`（`from .. import __version__`）；对照模块级导入区 `:12-43` 已存在 `from .workspace import (` (`:43`)
  - 宽泛兜底与静默替代：`src/codex_switch/ui_v2/workspace.py:438-448`——`:440` `except Exception:  # noqa: BLE001 - property may need version info` 捕获后**静默改用** `is_newer_version(...)` 计算 `available`，返回值仍是 `{"checked": True, "updateAvailable": ...}`，调用方无从得知走到过兜底分支
  - 宽泛兜底计数：`workspace.py` 内 `except Exception` 共 **16** 处（`:443`、`:782`、`:795`、`:868`、`:1174`、`:1260`、`:1337`、`:1497`、`:1542`、`:1555`、`:2291`、`:2303`、`:2376`、`:2440`、`:2476`、`:2541`）；`controller.py` 6 处、`viewmodels/terminal.py` 13 处、`terminal/manager.py` 6 处、`terminal/notifier.py` 7 处（全仓 `src` 共 23 个文件命中 `except Exception`）
  - 规模数据：按 UTF-8 字节 `LF` 计数实测 → `src/codex_switch/ui_v2/workspace.py` 2668 行、`src/codex_switch/ui_v2/controller.py` 1769 行、`src/codex_switch/ui/app.py` 5264 行、`tests/test_dsh_multi.py` 1400 行
  - 可测性佐证：`:1496`/`:1502` 的内联导入导致 `controller.py` 无法通过模块级 `patch("codex_switch.ui_v2.controller.subprocess")` 影响该路径（符号只在函数调用时绑定到局部作用域）
- **影响面 / 严重级别**：可维护性（失败模式不可观测）· 正确性（静默替代掩盖上游故障） / **中**
- **建议改法**：① 把 `controller.py:1502` 的 `import subprocess` 上移到模块级导入区（`:12-43`），把 `:1496` 的 `from .workspace import` 合并进 `:43` 已有的 `from .workspace import (` 列表——两者都是本项目内模块，无循环导入障碍（`workspace.py` 不导入 `controller.py`），上移后即可被模块级测试 patch；同时借 F2-05 的平台分派改动把该平台逻辑从 `controller.py` 移入 `workspace.py` 的统一打开函数，使 `controller.py` 只调用不实现。② 对 `workspace.py:440` 这类静默兜底，在兜底分支中加入可观测信号：把 `except Exception:` 收窄为具体异常（如 `AttributeError`/`TypeError`），或在 `ActionResult`/返回值里附带 `"fallback": True`（并在界面日志记录一次），使其可被测试断言。预期收益：平台专属行为可被单测覆盖（消除 F2-05 类缺陷的盲区）；上游故障不再伪装成正常值，排障从「读 2668 行」降为「看一条日志」。

---

## §6 维度⑤ 文档

### F6-01 版本号一致性守卫只认一代旧版本字面量，发布说明的断言只校验文件存在

- **问题**：`tests/test_version.py` 是 `pyproject.toml:7-9` 注释所述「版本两处漂移三个月、203 个提交未反映」的防复发机制，但其防复发能力有边界：旧版本检查把陈旧字面量**硬编码**为 `"0.2.2"`（:77），因此下一次版本漂移（例如从 `0.3.0` 漂到已废弃的 `0.3.1`）不会被捕获；同时「当前版本必须有发布说明」的断言只做 `is_file()` 存在性判断（:85-89），不校验内容是否对应本次版本。当前事实核对：`src/codex_switch/__init__.py:1` 的 `__version__ = "0.3.0"` 与 `docs/releases/` 下实际存在的 `v0.2.1.md`、`v0.2.2.md`、`v0.3.0.md` **一致**，即本代守卫有效、无陈旧版本残留（实测 `README.md` 与 `docs/*.md` 中对 `0.2.2`/`0.2.1` 的匹配为零命中）。
- **证据**：
  - `src/codex_switch/__init__.py:1`：`__version__ = "0.3.0"`
  - `docs/releases/` 实测目录内容：`v0.2.1.md`、`v0.2.2.md`、`v0.3.0.md`（恰好含当前版本）
  - `tests/test_version.py:73-83`：`test_no_stale_version_literals_in_source`，其中 `:77` `stale = "0.2.2"`（硬编码单一代旧版本）
  - `tests/test_version.py:85-89`：`test_release_notes_exist_for_current_version`，断言 `note.is_file()`，未读取/校验内容
  - `pyproject.toml:7-9`：注释记录漂移事故与「改为动态读取」的动机；`:10` `dynamic = ["version"]`、`:18-19` `[tool.setuptools.dynamic] version = { attr = "codex_switch.__version__" }`
  - 实测 grep `0\.2\.2|0\.2\.1|v0\.3` 于 `README.md`、`docs/*.md` → **零命中**（当前文档未残留旧版本号）
- **影响面 / 严重级别**：可维护性（防复发机制单代有效） / **低**
- **建议改法**：把 `tests/test_version.py:77` 的 `stale = "0.2.2"` 换成「所有小于当前版本的 semver」判定：解析 `__version__` 为 `(major, minor, patch)`，扫描 `src/**/*.py` 中形如 `\b\d+\.\d+\.\d+\b` 的字面量，凡解析结果 **严格小于** 当前版本且不出现在该文件中的即报警（这样 `0.2.2` 与未来任何被跳过的版本都被覆盖）；`test_release_notes_exist_for_current_version` 增加内容断言（文件非空且首行含 `v{__version__}`）。预期收益：把「防漂移」从「只防历史那一次」升级为「持续防任意回退」，避免下一次版本变更后守卫静默失效。

### F6-02 README 与 `docs/dsh-multi.md` 未覆盖工作区已实现的三个新 DSH 能力

- **问题**：工作区未提交改动为 DSH 多开插件新增了 `open_default()`、`write_config()`、`profiles()` 三个能力（并经桥接暴露给 QML），但 `docs/dsh-multi.md` 与 `README.md` 均未记录其中任何一项；`README.md` 对 DSH 多开的描述仍停留在旧能力集。触发条件：用户阅读文档寻找「如何把配置中心的 Profile 写入某个 DSH 环境」→ 文档无此说明，只能读源码；同时该行为的**安全含义**（写入会改 `settings.yaml` 并向进程环境注入 API Key，见 F4-03）也未被文档告知。
- **证据**：
  - 代码侧（新增能力）：`src/codex_switch/builtin_plugins/dsh-multi/entry.py:237-253`（`open_default`，`:242` `subprocess.Popen([... "--profile", "web"])`）、`:255-262`（`profiles`）、`:264-281`（`write_config`，`:272-276` 调 `self.api.invoke("write-dsh-profile", ...)`）
  - 桥接侧：`src/codex_switch/ui_v2/plugin_bridge.py:58-60`（`ALLOWED_METHODS` 新增 `open_default`/`write_config`/`profiles`）、`:229-241`（三个 `@Slot` 包装）
  - 控制器侧：`src/codex_switch/ui_v2/controller.py:831-833`（`writeDshProfile` Slot）、`:1604-1610`（`write-dsh-profile` 动作分发）
  - 文档侧（缺口，实测）：`docs/dsh-multi.md` 共 202 行，grep `write_config|写入 DSH|open_default|profiles|配置中心` → 仅命中 `:34`/`:144`/`:186` 三处 `profiles/<profile>/`（指 DSH 自身的 profile 目录，**非**本次新增的 `profiles()` 方法），**零**处覆盖新增能力
  - `README.md:101`（DSH 多开功能段落的既有描述；该段落标题见 `:99`）；实测 grep `README.md` 的 `写入 DSH|write_config|open_default|DSH 配置` → **零命中**
  - 对照既有文档习惯：`docs/codebuddy-accounts.md`（201 行）为同类插件能力提供了独立说明页，说明「插件能力应有文档」是本仓既有约定
- **影响面 / 严重级别**：可维护性（能力不可发现、安全语义未披露） / **中**
- **建议改法**：在 `docs/dsh-multi.md` 增加一节「把配置写入 DSH 环境」，说明：入口（DSH 多开页面选择目标环境 → 选择配置 → 写入）、实际写入位置（`<harness home>/settings.yaml` 的 `llm-pi-ai.providers.codex-switch` 与 `agent-default-model` 两个受控区块，见 `src/codex_switch/dsh_config.py:106-154`）、以及**风险提示**：写入会向当前进程环境注入 API Key 且新建的 DSH 进程会继承（关联 F4-03）；同时在 `README.md:99-107` 所在的 DSH 多开段落补一句交叉引用。预期收益：新增能力可被用户发现；把 F4-03 的凭据语义写入文档，避免用户在不了解行为的情况下把配置写入共用环境。

### F6-03 根 `AGENTS.md` 被忽略而 README 将其记为仓库内容，且它存在一份内容相同但未跟踪的 `CLAUDE.md` 副本

- **问题**：仓库文档体系中 `AGENTS.md` 的角色描述是「仓库根目录的协作规则文件 / 内置模板」，但根 `AGENTS.md` 实际被 `.gitignore:31` 忽略（未跟踪），而 README 多处把它当作仓库内容引用（`:17`、`:44`、`:120`、`:124`、`:269`）。触发条件：新贡献者按 README 去仓库里找根 `AGENTS.md` → 在干净检出中不存在（只存在于原作者本机）；同时根目录另有一份内容**完全相同**的 `CLAUDE.md` 副本（也未跟踪），而真正被跟踪的模板是 `src/codex_switch/assets/AGENTS.md`（299 行，与根文件 SHA-256 不同）——三份「AGENTS」内容并存且只有一份在版本库中，来源不清。
- **证据**：
  - `.gitignore:31`：`/AGENTS.md`（实测 `git check-ignore -v AGENTS.md` → `.gitignore:31:/AGENTS.md`）
  - 实测 `git ls-files --error-unmatch AGENTS.md` → `error: pathspec 'AGENTS.md' did not match any file(s) known to git`（**未跟踪**）
  - 文档侧对照（README 说 X）：`README.md:17`「你希望维护一份默认 `AGENTS.md` 模板，用于后续生成项目模板」、`:44`（列出 `.codex/`、`AGENTS.md`）、`:120`「内置 `AGENTS.md` 模板编辑器」、`:124`「不会直接修改当前仓库根目录的 `AGENTS.md`」、`:269`「默认文档模板来自 `src/codex_switch/assets/AGENTS.md`」
  - 仓库侧对照（代码/结构是 Y）：根 `AGENTS.md` 实测存在（300 行）但未跟踪；`src/codex_switch/assets/AGENTS.md` **已跟踪**（`git ls-files src/codex_switch/assets` → `src/codex_switch/assets/AGENTS.md`、`src/codex_switch/assets/mcp-servers-2026-04-11.json`），实测 299 行
  - 副本证据：`CLAUDE.md`（未跟踪，16,401 字节）与根 `AGENTS.md` 的 SHA-256 **均为** `082FB9817F8647DECE742C1698BABF40F3EC54ECC7996EAF758B3A751CB0270B`（内容逐字节相同）
  - `README.md:257` 已显式声明「提交到 GitHub 的源码不包含 … 根目录 `AGENTS.md`」，即忽略行为本身在文档中有一处说明，但与 `:17`/`:44`/`:120` 的「仓库内容」语气冲突
- **影响面 / 严重级别**：可维护性（文档与仓库结构不一致） / **中**
- **建议改法**：二选一并写清：① **保持忽略**（推荐，与 `README.md:257` 一致）→ 修正常 `README.md:17`/`:44`/`:120`/`:124` 的措辞，明确「根 `AGENTS.md` 是本地协作规则、不入库；入库的模板是 `src/codex_switch/assets/AGENTS.md`」，并删除或忽略 `CLAUDE.md` 副本（见 F4-02）；② **改为入库** → 从 `.gitignore:31` 移除 `/AGENTS.md`，并把根 `AGENTS.md` 与 `src/codex_switch/assets/AGENTS.md` 的关系（谁派生谁、如何同步）写进 `docs/`。无论选哪条，都应消除「同内容三副本、仅一份入库」的状态。预期收益：文档描述的仓库结构与干净检出结果一致；消除同一文件多副本导致的修改落到错误副本的隐患。

---

## §7 工作区 6 个未提交改动的定向评审索引

本节为**索引表，不产生条目、不复制四要素**。文件路径与规格卡逐字一致，行数恰好 6 行。

| 文件 | 关联条目 | 备注 |
| --- | --- | --- |
| `src/codex_switch/builtin_plugins/dsh-multi/entry.py` | `F2-02`；另见 `F6-02`（新增能力缺文档）、`F4-03`（`:241-250` `env=dict(os.environ)` 的继承面） | 修改（+51 行）；新增 `open_default`/`profiles`/`write_config` |
| `src/codex_switch/ui_v2/controller.py` | `F5-03`（内联导入 `:1496`/`:1502`）；另见 `F2-05`（`:1507-1510` `explorer` 分支） | 修改（+11 行）；新增 `writeDshProfile` Slot 与 `write-dsh-profile` 动作分发 |
| `src/codex_switch/ui_v2/plugin_bridge.py` | 已通读、未发现本次维度内问题 | 修改（+17 行）；`ALLOWED_METHODS` 增 3 项 + 3 个 `@Slot` 包装，`_call` 的异常收敛（`:102`）属有意设计，未见实际缺陷 |
| `src/codex_switch/ui_v2/workspace.py` | `F2-05`（`:2578`/`:2607` `os.startfile`）；`F5-03`（`:440` 静默兜底等） | 修改（+14 行）；新增 `write_dsh_profile` |
| `src/codex_switch/dsh_config.py` | `F2-01`（`:1`/`:4`/`:29`/`:32` docstring 转义）；`F5-01`（`:201-214` 原子写）；`F4-03`（`:56` API Key 入进程环境）；`F4-01`（该文件为 AI 终端/DSH 写入路径，依赖声明缺口的相关面） | 新增（未跟踪，223 行） |
| `scripts/run_tests_writable_tmp.py` | 已通读、未发现本次维度内问题（其有效性结论见 §1.2「未解决」，按要求不产生条目） | 新增（未跟踪，49 行） |

---

## §8 汇总表（按严重级别排序）

分组顺序**阻断 → 高 → 中 → 低**，同组内按维度序①②③④⑤。

### 阻断

（无）

### 高

| ID | 严重级别 | 维度 | 改法摘要 |
| --- | --- | --- | --- |
| `F2-05` | 高 | ① | `_open_path`/`_open_url` 按平台分派 `open`/`xdg-open`，`controller.py` 复用同一实现 |
| `F3-03` | 高 | ② | README 测试段落给出可跑通的解释器（`.venv`）与前置依赖/期望基线 |
| `F4-01` | 高 | ③ | 以 `pyproject.toml` 为单一来源补 `pyte`/`pywinpty`/`psutil`，`requirements*.txt` 引用之 |

### 中

| ID | 严重级别 | 维度 | 改法摘要 |
| --- | --- | --- | --- |
| `F2-01` | 中 | ① | `dsh_config.py:1`/`:29` docstring 改 raw 字符串，消除非法转义告警 |
| `F2-02` | 中 | ① | `entry.py:277` 收窄为 `except plugins.PluginError`，内部错误单列分支 |
| `F2-03` | 中 | ① | `test_terminal.py:405`/`:421` 改用 `str`+`encode()`，覆盖真实 `•` 数据 |
| `F2-04` | 中 | ① | `start()` 明确 `stream` 关闭责任，消除日志句柄泄漏 |
| `F3-01` | 中 | ② | `pyproject.toml` 增 `[tool.ruff]` + 新增 `lint.yml`（PR/主干触发） |
| `F3-02` | 中 | ② | 新增 `ci.yml`（push/PR 触发），命令统一为 README 的 `-q` 口径 |
| `F4-02` | 中 | ③ | `.gitignore` 补 `.memsearch/` 与 `/CLAUDE.md` |
| `F4-04` | 中 | ③ | 5 处 action 固定 commit SHA，写权限下移到 `release` job |
| `F5-01` | 中 | ④ | 抽公共 `atomic_write_text`，四处收敛（保留勿用 `NamedTemporaryFile` 约束） |
| `F5-02` | 中 | ④ | `tests/helpers.py` 统一 `TEST_ROOT`/`make_temp_dir`，删 5 份副本 |
| `F5-03` | 中 | ④ | 内联导入上移模块级；静默兜底改收窄异常或附 `fallback` 标记 |
| `F6-02` | 中 | ⑤ | `docs/dsh-multi.md` 补「把配置写入 DSH 环境」节（含 API Key 风险提示） |
| `F6-03` | 中 | ⑤ | 统一「根 AGENTS.md 不入库 / 模板在 assets」口径，消除三副本 |

### 低

| ID | 严重级别 | 维度 | 改法摘要 |
| --- | --- | --- | --- |
| `F3-04` | 低 | ② | 临时根支持 `CODEX_SWITCH_TEST_ROOT`，只读检出下可跑 |
| `F3-05` | 低 | ② | 清理孤立 `tests/__pycache__/_leak_guard.cpython-313.pyc` |
| `F4-03` | 低 | ③ | 子进程 `env` 收窄为白名单，回显统一走 `mask_secret` |
| `F6-01` | 低 | ⑤ | 版本守卫改为「小于当前版本」判定，发布说明增内容断言 |

**计数**：条目总数 **20**；阻断 **0**、高 **3**、中 **13**、低 **4**。

---

## §9 收尾核查与行为声明

### §9.1 T12 编号集合一致性核对

核对方式：先按 `^### F\d-\d\d ` 提取 §2–§6 全部条目 ID 集合，再提取 §8 三张分组表的 ID 列集合，做双向集合比对与重复检测。

- §2–§6 条目 ID 集合（20 个）：`F2-01`、`F2-02`、`F2-03`、`F2-04`、`F2-05`、`F3-01`、`F3-02`、`F3-03`、`F3-04`、`F3-05`、`F4-01`、`F4-02`、`F4-03`、`F4-04`、`F5-01`、`F5-02`、`F5-03`、`F6-01`、`F6-02`、`F6-03`
- §8 汇总表 ID 集合（20 个）：同上，逐项一致
- **核对结论**：**§8 的 ID 集合与 §2–§6 的 ID 集合完全相同**——无缺漏（§2–§6 有而 §8 无）、无多余（§8 有而 §2–§6 无）、无重复 ID，且无孤立行。
- §7 索引表按 §1 单源规则**不产生条目**：表中「关联条目」列只引用已存在的 `F2-02`、`F2-05`、`F4-01`、`F4-03`、`F5-01`、`F5-03`、`F6-02`，未引入任何新 ID。

### §9.2 T13a 终局仓库未变核对

核对方式与口径（按任务给定的非阻塞建议 2 与 3 执行）：**本项只校验仓库未提交文件集合，并排除本变更目录 `openspec/changes/codex-switch-health-checkup/` 下的规划产物**；按 §0.3 口径，基线集合 = 规格卡声明的 **6 个源码改动文件**，`openspec/changes/` 下既有规划产物（含 `probe.md`）不计入基线集合。报告正文的后续编辑不改变仓库未提交集合，故不影响本结论。

对比结果（报告定稿后实测）：

| 项 | T1 基线（§0.2） | 终局实测 | 结论 |
| --- | --- | --- | --- |
| 修改的已跟踪文件 | `entry.py`、`controller.py`、`plugin_bridge.py`、`workspace.py`（规格卡 4 项）+ 3 个 QML | **完全相同**（同样 7 个 ` M ` 条目） | 无新增、无缺失 |
| 规格卡 6 个源码改动文件 | 4 改 2 增（见 §0.3） | **6/6 全部在列**，逐个 `git diff --stat` 摘要与 §0.3 逐字一致 | 无内容差异 |
| 未跟踪条目 | `.memsearch/`、`CLAUDE.md`、`openspec/`、`scripts/run_tests_writable_tmp.py`、`src/codex_switch/dsh_config.py` | **完全相同**（5 项） | 无新增、无缺失 |

**核对结论**：`git status --porcelain` 的未提交条目集合，排除本变更目录 `openspec/changes/codex-switch-health-checkup/` 下由本轮新增的文件后，与 T1 基线集合**完全相同**——原 6 个源码改动文件（4 改 2 增）无新增、无缺失、无内容差异；实测发现的 3 个 QML 改动与 `.memsearch/`、`CLAUDE.md` 亦与 T1 基线逐项一致（未新增、未修改、未回滚）。`openspec/changes/probe.md` 保持原位未被删除。

本轮在上述唯一授权写入区内的实际写入为 `report.md` 一个文件；执行用临时输出文件（`.t2-unittest-out.txt`、`.t3-runner-out.txt`、`.t3-venv-out.txt`、`.cmp-t2.txt`、`.cmp-t3.txt`）已在提交前删除，未进入 git 历史（见 §1.4）。

### §9.3 T13b 收尾行为声明

**本轮未安装任何依赖、未修改任何源码/脚本/配置/测试。**

**git 侧实际执行（如实扩写，含与 `design.md` §2.3 的分歧记录）**：

1. **取证阶段（§0–§8 的全部结论）只用只读 git 子命令**：`status`、`log`、`rev-parse`、`diff`、`ls-files`、`check-ignore`；该阶段未执行 `add`/`commit`/`push`/`stash`/`checkout`/`restore`/`clean`/`reset`/`worktree`。
2. **报告定稿后，按本任务卡第 7 条「git worktree/branch → git commit → git push」的交付要求**，在 feature 分支 `codex-switch-health-checkup`（自 HEAD `e2e3879ef05b96211558fc1ca0710a34221424b6` 起）上执行了**一次**提交，提交内容**仅限本变更目录** `openspec/changes/codex-switch-health-checkup/` 下的文档（`proposal.md`、`design.md`、`tasks.md`、`report.md`）。该提交**未包含**工作区既有的 6 个未提交改动、3 个 QML 改动、`.memsearch/`、`CLAUDE.md`、`openspec/changes/probe.md`；未对上述任何文件执行暂存、提交、回滚或格式化；未向 `TARGET_BRANCH`（`main`）提交或推送，未强推。
3. **分歧记录（不修改计划文本，修计划属 P 职责）**：`design.md` §2.3 第 3 条声明「禁止 `git add`/`commit`/`push`/`stash`/…，只允许只读子命令」，而本任务卡第 7 条把 `git commit`（及可选的 feature 分支 `git push`）列为交付要求，并要求 `kanban_complete` 必须携带 git 产物证据。二者直接冲突。按任务卡「计划与规格卡冲突时**以规格卡为准并记录分歧**」，本报告以规格卡与任务卡为准执行提交，并在此如实记录该分歧；同时依 `design.md` §7 末行「收尾行为声明与实际执行不一致时，说明原因后以实际执行为准修正声明」，上文本声明已按实际执行修正。`design.md` 原文未被改动。

除上述第 2 条明确限定的、仅针对本变更目录的一次提交外，本轮未对仓库其他任何文件做任何写操作：未修改 `src/`、`scripts/`、`main.py`、`tests/`、`build.ps1`、`pyproject.toml`、`requirements*.txt`、`.github/`、`.gitignore`、`CodexSwitch.spec`、`docs/`、`README.md`、`AGENTS.md`，未修改 6 个未提交改动与 3 个 QML 改动；未运行任何包管理器安装命令（`pip install`/`npm i` 等），依赖缺失一律记录为条目（F4-01/F3-03）而非就地补装；`.tmp/` 不可访问目录的权限未被修改、内容未被删除。

### §9.4 T14a 范围外内容零命中复查

全文复查结论：报告全文对以下六类范围外内容**零命中**。

| 范围外类别 | 复查结果 |
| --- | --- |
| 代码改动 | 零命中。全文未提出也未执行任何代码改动；§2–§6 的「建议改法」均以「建议」措辞给出且明确留待后续建链（`README.md` 侧未见任何修改）。本轮未修改任何源码文件（§9.2、§9.3 已核对） |
| QML 深度审查 | 零命中。3 个 QML 改动仅作为 §0.3 的基线事实记录，未对 `.qml` 文件作任何内容级审查、未提出 QML 侧改法。§2–§6 未出现任何 `.qml` 路径的条目 |
| DSH 宿主侧工具白名单缺陷 | 零命中。`planning_prefetch` 白名单缺 `bash`/`edit`/`write` 一事在全文未作为仓库问题写入；`.memsearch/memory/2026-10-07.md` 中虽记录了该现象，但本报告未引用为条目 |
| 性能压测与大规模基准测试 | 零命中。全文未做也未建议任何压测/基准；§1.1 与补充实测中的「耗时」数据（35.481s、35.745s、141.691s）仅作为原样执行输出记录，未作为性能结论 |
| 新增功能需求 | 零命中。全文未提出任何新功能；所有条目均为既有代码/配置/文档的缺陷或文档缺口（F6-02 是「为**已实现**能力补文档」，不含新功能） |
| 他人未提交改动的收尾 | 零命中。全文未建议、未执行对这 6 个未提交改动（及实测发现的 3 个 QML 改动、`.memsearch/`、`CLAUDE.md`）的提交、暂存、回滚、格式化或清理；§7 仅作索引标注 |

### §9.5 T14b 无定位泛泛条目零命中复查

按任务给定的执行口径（非阻塞建议 1），本项收敛为：**「无定位且未标注「推测、待验证」的泛泛/套话条目」零命中**。

复查方式：逐条检查 §2–§6 全部 20 个条目的「证据」字段是否含具体 `路径:行号` 或最小可核对片段（含实测命令与原始输出）。

- 复查结果：**20/20 条目均含具体仓库定位**（每条至少 2 处 `路径:行号`，多数附实测命令输出或 `git`/`grep` 实测结论）；**无定位且未标注「推测、待验证」的条目命中数为 0**。
- 未出现「建议增加测试」「注意安全」「代码太长建议拆分」这类无定位套话；§2–§6 未出现任何未附证据的结论性段落。
- 关于复杂度条目（F5-03）：已按要求不以行数判缺陷，明确写出「问题不在行数本身」并给出两项可观测后果（内联导入位置与静默兜底分支）及其 `路径:行号` 证据。
- 关于「有意设计」的两处（`plugin_bridge.py:102` 的异常收敛、`dsh_config.py:56` 的环境变量注入）：前者未凑条目（在 §7 明确记为「未发现本次维度内问题」），后者（F4-03）以「属设计取舍」定性并只提收窄建议，未无据指为缺陷。

### §9.6 T14c 无证据条目标注复查

复查方式：检索全文是否存在「无法在仓库中定位证据、却以确定语气书写」的条目。

- 复查结果：**不存在以确定语气书写却无证据的条目**。
- 本报告**未产生**需要标注「推测、待验证」的条目：全部 20 条均具备可在仓库中定位的证据（`路径:行号` 与实测输出），因此在 §2–§6 中未出现「推测、待验证」标注——这是「无需标注」而非「标注缺失」。
- 需要说明的边界的边界：§1.2 对 `scripts/run_tests_writable_tmp.py` 的「未解决」结论基于两组实测对照（§1.2 证据 1–3），§1.3 对 `.tmp/` 的判定基于实测异常与 §1.1 复用结果，二者均为实测证据而非推测。§0.5 关于 `probe.md` 的「规划期残留」定性来自该文件自述内容，已附文件实测行数与原文要点。

---

## §10 附：本轮不产生条目的取证结论（供后续建链参考）

以下为本轮实测得到、按单源规则与 T10 边界**不产生条目**的正面结论，集中记录以免读者误以为未取证：

1. `tests/test_version.py` 的防复发机制在当前代有效：`__version__ = "0.3.0"` 与 `docs/releases/v0.3.0.md` 对应，`README.md`/`docs/*.md` 无 `0.2.2` 陈旧残留（其能力边界见 F6-01）。
2. `src/codex_switch/proxy/sanitize.py:6-26` 已有敏感头与 `sk-`/`api_key=` 文本的脱敏实现，脱敏规则覆盖面本身未发现缺陷（其未接入 API Key 注入路径见 F4-03）。
3. `src/codex_switch/ui_v2/plugin_bridge.py:88-105` 的 `_call` 把插件异常收敛为 `{"ok": False}` 属**有意设计**（第三方代码隔离），本轮未发现实际缺陷，故不凑条目。
4. `tests/test_encoding.py:11-41` 已对「Python 文件 UTF-8 无 BOM」与「requirements 文件纯 ASCII」建立回归保护，本轮实测通过（该测试在 643/1096 两个口径下均未进入失败集）。
5. `src/codex_switch/dsh_instances.py:625-633` 的 `_close_stream` 与 `:671`/`:802`/`:870` 三处调用说明「关闭子进程 stdout 句柄」的意图已被显式表达并实现（其覆盖缺口见 F2-04）。
6. `src/codex_switch/proxy/**`（`server.py`、`translator.py`、`sanitize.py`）中 `server.py:285-295`、`:560-572` 的 `except Exception` 均在捕获后**记录并重新抛出/返回明确错误载荷**（非静默吞并），本轮未发现该处的实际缺陷。
7. 工作区 6 个未提交改动中，`src/codex_switch/ui_v2/plugin_bridge.py` 与 `scripts/run_tests_writable_tmp.py` 经通读未发现本次五个维度内的问题（见 §7）。

---

## §11 关联文档

- 上游需求澄清清单：`wiki/queries/checklists/codex-switch-muy2vg71.md`
- 计划产物：`proposal.md`（交付物定义 / 范围 / 维度优先级 / 协议遵循 / A1–A12 / 需求对齐映射）、`design.md`（§0–§8 大纲 / 条目模板 / 只读边界 / 五维度取证方法 / 单源规则）、`tasks.md`（T1–T12 + T13a/T13b + T14a/T14b/T14c）
- KB 同步页：`wiki/sources/ch_1_muy2z7pm/t_4_muy7pke1.md`（本地库根 `C:\Users\fan\.dsh\storages\kanban\wiki`）
