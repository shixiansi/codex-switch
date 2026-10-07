# 提案：codex-switch 仓库体检与优化方案（问题清单 + 优化方案报告）

- **change_name**：`codex-switch-health-checkup`
- **目标仓库**：`F:\编程\codex-switch`
- **本轮形态**：**只读体检**。交付物是一份报告，不是代码改动。
- **交付物路径**：`openspec/changes/codex-switch-health-checkup/report.md`
- **上游输入**：规格卡（approved）+ 需求澄清清单 `wiki/queries/checklists/codex-switch-muy2vg71.md`

## 1. 背景与问题

用户要求对当前项目做「可能存在的问题 + 如何优化」的排查。规划期有三个事实缺口（与规格卡 problem 一致）：

1. 目标仓库工作区存在 6 个未提交改动（4 改 2 增），且无可对比基线提交，改动处于「做完未落库」状态；
2. 该仓库此前无任何评审与经验沉淀记录（KB 无 learnings、无历史规划清单），看板无在跑任务；
3. 规划者只读自查通道一度不可用；本轮规划已由规划者完成只读自查（read/glob/grep 全部成功），仓库事实侧充分。

因此本轮由规划者锁定**范围、维度优先级、验收标准**，由具备读写权限的执行角色（D）实际扫描仓库后产出结论。

## 2. 交付物定义

一份报告 `openspec/changes/codex-switch-health-checkup/report.md`，内容为「基于仓库实据的问题清单与优化方案」。硬性要求：

- **每条结论必须能在仓库里定位到具体代码或配置**（文件路径 + 行号，或可核对的最小代码片段）；
- 每条条目必须齐备**四要素**：① 问题描述 ② 仓库证据（`路径:行号` 或片段）③ 影响面（正确性/稳定性/可维护性/安全）+ 严重级别 ④ 具体优化改法 + 预期收益；
- 严重级别固定四级：**阻断 / 高 / 中 / 低**，汇总按该级别排序输出；
- **禁止无证据支撑的泛泛而谈项**（如「建议增加测试」这类无定位的套话）；无法定位证据的条目必须显式标注「推测、待验证」，不得以确定语气写入；
- 条目统一编号 `F<维度号>-<两位序号>`（如 `F2-03`、`F4-01`），供跨节引用与汇总核对。

报告固定大纲：

| 节 | 内容 |
| --- | --- |
| §0 | 只读基线（分支/HEAD/未提交清单，实测输出） |
| §1 | 验收硬标准执行记录（1.1 测试单命令执行；1.2 `run_tests_writable_tmp.py` 有效性结论；1.3 `.tmp/` 不可访问目录影响判定） |
| §2 | 维度① 正确性与稳定性 |
| §3 | 维度② 测试与工程化（lint / CI / 测试可在 Windows 跑通） |
| §4 | 维度③ 依赖与安全配置 |
| §5 | 维度④ 重复逻辑与复杂度 |
| §6 | 维度⑤ 文档 |
| §7 | 工作区 6 个未提交改动的定向评审索引 |
| §8 | 汇总表（按严重级别排序） |

**报告里只有 §2–§6 产生条目**；§7 是**索引表**（文件 → 关联条目编号），不重复生成条目，避免与 §2–§6 双份计数。

`report.md` 由 D 阶段产出；本变更目录的 `proposal.md` / `design.md` / `tasks.md` 由 P 产出。四份文件均落在 `openspec/changes/codex-switch-health-checkup/`。

## 3. 本轮不做（范围锁定）

1. **不做修复**。本轮只体检、只出报告。**禁止 D 在体检过程中顺手改代码、改脚本、改配置、改测试**（该约束同时写入 `design.md` 的只读边界，并由 T13a 终局核查）。
2. **不修改工作区这 6 个未提交改动**，按现状评审；也不指挥 D 去提交、回滚、暂存他人的改动。
3. 不做 QML 深度审查（本轮仅当存在 Python 侧调用证据时提及）。
4. 不做性能压测与大规模基准测试。
5. 不处理 DSH 宿主侧 `planning_prefetch` 工具白名单缺陷（DSH 自身配置问题，不属于本仓库代码，另行在 DSH 侧修复，出本链范围）。
6. 不新增功能需求，只针对既有代码与工程化现状给结论与建议。
7. **实现手段约束**：不安装/升级任何依赖；仅使用仓库现有解释器执行；git 仅允许只读子命令（`status` / `log` / `show` / `diff` / `rev-parse` 等）。

**只读边界的精确定义**（消除「仓库保持只读」与「要写报告」之间的表面矛盾）：`src/`、`scripts/`、`main.py`、`tests/`、`build.ps1`、`pyproject.toml`、`requirements*.txt`、`.github/`、`.gitignore`、`CodexSwitch.spec`、`docs/`、`README.md`、`AGENTS.md` **一律只读**；本变更唯一允许的写入位置是 `openspec/changes/codex-switch-health-checkup/`（`proposal.md` / `design.md` / `tasks.md` / `report.md`）。

## 4. 扫描范围（逐项可核对）

以下路径均已由规划者只读自查实证存在：

| 类别 | 路径 |
| --- | --- |
| 源码（默认入口层） | `src/codex_switch/ui_v2/**`（`controller.py`、`workspace.py`、`session.py`、`snapshots.py`、`forms.py`、`plugin_bridge.py`、`app.py`、`qt_compat.py`、`theme.py`、`single_instance.py`、`script_runner.py`、`viewmodels/`、`workers/`、`terminal/`） |
| 源码（核心业务层） | `src/codex_switch/*.py`（`storage.py`、`models.py`、`codex_config.py`、`claude_config.py`、`dsh_home.py`、`dsh_instances.py`、`dsh_plugins.py`、`dsh_config.py`、`process_util.py`、`project_template.py`、`skills.py`、`health.py`、`chat.py`、`software_update.py`、`resources.py`、`codebuddy_core.py`） |
| 源码（代理/插件/旧界面） | `src/codex_switch/proxy/**`、`src/codex_switch/plugins/**`、`src/codex_switch/builtin_plugins/**`（含 `dsh-multi/entry.py`、`dsh-multi/plugin.json`）、`src/codex_switch/ui/**`（旧 Tk 界面） |
| 脚本与入口 | `main.py`、`scripts/**`（含工作区新增 `scripts/run_tests_writable_tmp.py`）、`build.ps1`、`CodexSwitch.spec` |
| 依赖清单 | `pyproject.toml`、`requirements.txt`、`requirements-build.txt` |
| 工程化配置 | `.github/workflows/release.yml`、`.gitignore` |
| 测试 | `tests/**`（`test_codex_switch.py`、`test_storage.py`、`test_skills.py`、`test_chat.py`、`test_proxy.py`、`test_project_template.py`、`test_ui_logic.py`、`test_ui_smoke.py`、`test_ui_v2_qml.py`、`test_ui_v2_workspace.py`、`test_version.py`、`test_encoding.py`、`test_plugins.py`、`test_plugin_viewmodel.py`、`test_dsh_multi.py`、`test_codebuddy_plugin.py`、`test_codebuddy_accounts.py`、`test_terminal*.py`、`test_cli_history.py`、`test_button_style.py`、`helpers.py`） |
| 文档 | `README.md`、`docs/**`（`plugins.md`、`codebuddy-accounts.md`、`dsh-multi.md`、`releases/v0.2.1.md`、`v0.2.2.md`、`v0.3.0.md`）、`AGENTS.md` |

**工作区 6 个未提交改动的处理方式**：全部纳入体检范围，按当前工作区现状评审；报告中须能看出某条结论是否落在这些改动区域内（§7 索引表承担该标注职责）；不修改、不提交、不暂存、不回滚。评审通道按工作区现状取证，不使用 `git stash` 等改变工作区的操作。

## 5. 维度优先级（固定，不得调换）

**① 正确性与稳定性 > ② 测试与工程化（lint / CI / 测试可在 Windows 跑通）> ③ 依赖与安全配置 > ④ 重复逻辑与复杂度 > ⑤ 文档**

报告 §2–§6 的节序、以及 tasks.md 中 T5→T9 的任务序，均与本优先级一致。

## 6. 上游协议遵循说明

本节逐条列出规格卡 / 澄清清单声明的工程协议引用（可定位出处）及本计划的遵守方式。

| 协议出处 | 声明来源 | 本计划如何遵守 |
| --- | --- | --- |
| `AGENTS.md` 第 5 条「每次修改完项目，在本地上传代码到 git，并在提交说明上简述本次改动的要点」（`AGENTS.md:50-51`） | 规格卡 out_of_scope 第 2 条显式引用该条 | 本轮零代码改动 → 不触发提交动作；报告 §2–§6 的「建议改法」一律留给后续挑项建链，届时由那条链按本条提交。本计划不安排任何 `git add/commit/push`，D 阶段也不得提交工作区既有改动。 |
| `AGENTS.md` 开发规则：KISS / YAGNI / SOLID（S/O/L/I/D）/ DRY（`AGENTS.md:7-17`） | `AGENTS.md` 明示的核心编程原则 | 见 `design.md`「工程原则应用」一节：报告不新建框架、不引入新工具链、不新增测试 runner（复用仓库既有 `python -m unittest discover -q -s tests` 入口）；DRY 维度本身即评审对象（三处原子写写法不一致等），要求给出定位与改法而非泛泛建议。 |
| `AGENTS.md` Chinese Encoding Safety Workflow 与 File Encoding（`AGENTS.md:267-300`） | `AGENTS.md` 明示的编码安全流程：禁止用 PowerShell `Set-Content`/`Out-File`/重定向写入中文；新增修改文件必须 UTF-8 无 BOM | 本计划三份文档与 D 阶段的 `report.md` 均为 UTF-8 无 BOM，且必须由文件写入工具生成，禁止经 PowerShell 文本管道承载中文正文。 |
| OpenSpec 变更文档规范：`proposal.md` / `design.md` / `tasks.md` 三件套写入 `openspec/changes/<change_name>/`，`change_name` 取 kebab-case | 本任务卡声明的产物规范 | 本目录即产出物，`change_name` = `codex-switch-health-checkup`（kebab-case）。 |

**除上表所列外，未引用规格卡之外的任何协议标准。**

## 7. 验收标准（可核对判据）

| 编号 | 判据 | 核对方式 |
| --- | --- | --- |
| A1 | `report.md` 存在于 `openspec/changes/codex-switch-health-checkup/` | 文件存在 |
| A2 | §0 内容为本次实测的 git 只读命令输出，未提交清单与工作区现状一致 | 比对 `git status --porcelain` 输出与 §0 |
| A3 | §1.1 记录一条**验收判定命令** `python -m unittest discover -q -s tests` 的完整执行：原样命令 + 退出码 + 通过/失败计数 + 失败用例名清单；同节另行单独记录 `python -m compileall -q main.py src tests` 及其退出码，并明示**不计入硬标准** | 报告自证 + 复核命令 |
| A4 | §1.2 对 `scripts/run_tests_writable_tmp.py` 给出**单一**结论（有效 / 部分有效 / 未解决）并附实验证据；其中「直接执行」对照组复用 §1.1 同一次 `unittest discover` 结果 | 报告自证 |
| A5 | §1.3 对 `.tmp/` 不可访问目录给出**单一**判定（是否导致常规判定命令 `python -m unittest discover -q -s tests` 失败）并附证据；判定依据复用 §1.1 同一次执行结果 | 报告自证 |
| A6 | §2–§6 五节齐备，节序与维度优先级一致 | 目录比对 |
| A7 | §2–§6 每条条目含四要素且证据可定位到 `路径:行号` 或片段；无定位者必须带「推测、待验证」 | 逐条抽查 |
| A8 | §7 覆盖全部 6 个未提交文件，每行给出关联条目编号或「已通读、未发现本次维度内问题」 | 表格行数 = 6 |
| A9 | §8 按 阻断 → 高 → 中 → 低 分组排序，每行含 ID / 严重级别 / 维度 / 改法摘要 | 表格比对 |
| A10 | §8 的 ID 集合与 §2–§6 条目 ID 集合一致（无缺漏、无重复、无孤立行） | 集合比对（T12） |
| A11 | ① 全文不含范围外内容（代码改动、QML 深度审查、DSH 宿主白名单缺陷、性能压测、新功能需求、他人改动收尾）——T14a 核对；② 全文不含无仓库定位的泛泛条目——T14b 核对；③ 无证据条目均已标注「推测、待验证」——T14c 核对 | 全文复查（T14a/T14b/T14c 分项核对） |
| A12 | 除本变更目录 `openspec/changes/codex-switch-health-checkup/` 下的既有产物外，仓库未提交集合仍为 T1 基线的原 6 个文件（T13a 核对）；且报告含「未执行 git 写操作 / 未装依赖 / 未改源码」的单一声明（T13b 出具） | `git status --porcelain` 比对（T13a）+ 声明核对（T13b） |

## 8. 需求对齐映射（澄清清单/规格卡 ↔ 计划任务）

| 上游条目 | 出处 | 计划任务 |
| --- | --- | --- |
| 只体检、不改动仓库文件 | Q1；out_of_scope 1 | 全局约束（§3）+ T13a/T13b |
| 维度优先级固定顺序 | Q2；impl_decisions | T5/T6/T7/T8/T9（节序 = 优先级序）+ T11 |
| 6 个未提交改动纳入范围、按现状评审且不修改不提交 | Q3；impl_decisions | T1（清单固化）、T10（定向评审）、T13a（未被改动） |
| 测试套件一条命令跑通为验收硬标准 | Q4；testing 1 | T2（判定命令唯一：`python -m unittest discover -q -s tests`） |
| 验证 `run_tests_writable_tmp.py` 是否真正解决 Windows 临时目录不可写 | Q4；impl_decisions 验收硬标准二 | T3（脚本有效性，复用 §1.1 执行结果）+ T4（对常规命令的影响判定） |
| 每条问题含四要素、证据可定位 | testing 2；impl_decisions | T5–T9（分维度）+ T12（编号集合一致） |
| 严重级别四级并按级排序输出 | impl_decisions | T11 |
| 无法定位证据须标注「推测、待验证」 | impl_decisions | T5–T9 判据内含 + T14c（全文复查标注） |
| 不做 QML 深度审查 | out_of_scope 3；疑点「QML 文件是否纳入审查范围」 | T14a（范围外条目核查） |
| 不处理 DSH 宿主侧工具白名单缺陷 | Q5；out_of_scope 5 | T14a（范围外条目核查） |
| 目标仓库即本仓库 | Q6 | 全文路径均为 `F:\编程\codex-switch` |
| 不新增功能需求 | Q7；out_of_scope 6 | T14a |
| 不做性能压测与大规模基准 | out_of_scope 4 | T14a |
| **user_story 1**：按严重级别排序、每条都有仓库实据的问题清单 | 规格卡 user_stories 第 1 条 | T11（按级别排序）+ T5–T9（每条带实据） |
| **user_story 2**：测试套件能在本机用一条命令跑通 | 规格卡 user_stories 第 2 条 | T2 |
| **user_story 3**：每条问题给出具体改法与预期收益 | 规格卡 user_stories 第 3 条 | T5–T9（四要素含「建议改法 + 预期收益」）+ T11 |
| **user_story 4**：本轮体检不改动任何仓库文件 | 规格卡 user_stories 第 4 条 | 全局约束（§3 只读边界）+ T13a（文件集合未变）+ T13b（行为声明） |

反向核对：T1–T12 各条 + T13a/T13b/T14a/T14b/T14c 均可在上表或「交付物定义 / 验收标准」中溯源；无超出规格卡与澄清回答的任务。

**映射完整性口径**：7 条澄清（Q1–Q7）+ 2 条 testing 硬标准 + 6 类 out_of_scope + 4 条 user_stories，共 19 项**全部双向映射**，无遗漏、无超纲。

## 9. 交付与交接

- D 完成时 `metadata.artifacts_path` = `F:\编程\codex-switch\openspec\changes\codex-switch-health-checkup`
- `metadata.change_name` = `codex-switch-health-checkup`；`metadata.tasks_count` = 17（T1–T12 各 1 条 + T13a/T13b + T14a/T14b/T14c）
- 建议 `metadata.report` 带上报告结论摘要与 §1.1 的测试执行结果（命令 / 退出码），便于后续建链挑项。

**验收判定命令口径（唯一，贯穿 proposal/design/tasks）**：验收硬标准一的判定命令是 `python -m unittest discover -q -s tests`，其退出码单独决定该硬标准是否满足；`python -m compileall -q main.py src tests` 仅为 §1.1 同节的前置编译检查记录，**不计入**硬标准。T3、T4 复用 §1.1 的同一次 `unittest discover` 执行结果，不另跑改良版命令。
