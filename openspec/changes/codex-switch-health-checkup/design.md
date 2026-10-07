# 设计：codex-switch 体检报告的结构、取证方法与执行边界

- **change_name**：`codex-switch-health-checkup`
- **对应提案**：`proposal.md`
- **本文件用途**：规定 D 阶段要产出的 `report.md` 的**结构、每节取证方法、只读边界执行规则**，以及本计划自身的工程原则判断。

## 1. 交付物结构（report.md 固定大纲）

| 节 | 内容 | 条目来源 |
| --- | --- | --- |
| §0 | 只读基线 | 无条目，纯事实记录 |
| §1 | 验收硬标准执行记录 | 无条目，纯事实与结论 |
| §2 | 维度① 正确性与稳定性 | 唯一条目来源之一 |
| §3 | 维度② 测试与工程化 | 唯一条目来源之一 |
| §4 | 维度③ 依赖与安全配置 | 唯一条目来源之一 |
| §5 | 维度④ 重复逻辑与复杂度 | 唯一条目来源之一 |
| §6 | 维度⑤ 文档 | 唯一条目来源之一 |
| §7 | 6 个未提交改动定向评审索引 | **不产生条目**，仅索引 |
| §8 | 汇总表 | **不产生条目**，仅聚合 §2–§6 |

**单源规则**：一个问题只在它所属维度的那一节展开完整四要素；若同一根因在多个维度都有影响，在主维度给完整条目，其他维度只写一行「见 `F<x>-<nn>`」，不复制四要素。这样 §8 的 ID 集合与 §2–§6 天然一致（A10）。

### 条目模板（四要素，逐条照抄）

```
### F<维度号>-<两位序号> <一句话标题>
- **问题**：<一句话说清错在哪/差在哪>
- **证据**：`<仓库相对路径>:<行号>`（必要时附 ≤10 行片段）；多处引用逐条列出
- **影响面 / 严重级别**：<正确性|稳定性|可维护性|安全> / <阻断|高|中|低>
- **建议改法**：<具体到改哪个函数、改成什么；说明预期收益>
```

### §7 索引表列定义

| 列 | 取值 |
| --- | --- |
| 文件 | 6 个未提交文件之一（路径与规格卡逐字一致） |
| 关联条目 | 指向 §2–§6 的 ID，逗号分隔；无则填「已通读、未发现本次维度内问题」 |
| 备注 | 该文件是否为工作区新增（`dsh_config.py`、`run_tests_writable_tmp.py`）或修改 |

### §8 汇总表列定义

| 列 | 取值 |
| --- | --- |
| ID | `F<x>-<nn>` |
| 严重级别 | 阻断 / 高 / 中 / 低 |
| 维度 | ①–⑤ |
| 改法摘要 | ≤30 字，指向 § 节完整条目 |

分组顺序固定：**阻断 → 高 → 中 → 低**；同级别内按维度序①②③④⑤。

## 2. 只读边界执行规则（必须逐条遵守）

1. 报告与所有读取均不得改动 `src/`、`scripts/`、`tests/`、`main.py`、`build.ps1`、`CodexSwitch.spec`、`pyproject.toml`、`requirements*.txt`、`.github/`、`.gitignore`、`docs/`、`README.md`、`AGENTS.md`；
2. 唯一允许写入的位置是 `openspec/changes/codex-switch-health-checkup/`；
3. **禁止** `git add` / `commit` / `push` / `stash` / `checkout` / `restore` / `clean` / `reset` / `worktree`；只允许只读子命令；
4. **禁止**一切依赖安装/升级（`pip install`、`npm i` 等）——测试若因缺依赖跑不起来，如实记录为环境事实，不得为跑通而装包；
5. **禁止**「顺手修复」：报告里发现的任何缺陷，只写进报告，不改代码；
6. 测试执行若产生临时文件，应落在仓库既有临时根（`.test-temp/`、`.tmp/`），这两者已在 `.gitignore:11-12` 中忽略，不构成对仓库的改动；
7. 收尾必须复核：`git status --porcelain` 的未提交集合仍为 T1 基线的原 6 个文件（A12）。

## 3. 各维度取证方法

### §0 只读基线

记录：`git rev-parse --abbrev-ref HEAD`（无提交基线时说明 mergeBase 为 null 的实测依据）、`git status --porcelain` 原样输出、6 个未提交文件的逐个 `--stat` 摘要。**只读，不产生条目。**

### §1 验收硬标准执行记录

**§1.1 测试单命令跑通（A3）**：以仓库既有入口执行一次，记录**原样命令、退出码、`Ran N tests` 行、`OK`/`FAILED` 行、失败用例名清单**。按 `README.md:168-171` 的既有入口取证。**命令口径唯一收敛**：验收硬标准一的**判定命令**是

```powershell
python -m unittest discover -q -s tests
```

其退出码**单独决定**验收硬标准一是否满足。同节另行的

```powershell
python -m compileall -q main.py src tests
```

仅为**前置编译检查的单独记录**，其退出码**不计入**硬标准，不得与判定命令并列充当硬标准证据。若判定命令失败，必须把失败用例名与首条 traceback 摘要写入报告——**失败也要如实记录**，不得为凑「跑通」而改测试或装依赖。

**§1.2 `scripts/run_tests_writable_tmp.py` 有效性（A4）**：该脚本 `scripts/run_tests_writable_tmp.py:26-36` 覆写 `tempfile.mkdtemp` 为 `os.mkdir(name, 0o777)`，并在 `main()` 里 `tempfile.mkdtemp = _writable_mkdtemp`。判定方法：对比「直接 `python -m unittest discover -q -s tests`」与「经该 runner 执行同一组测试」的结果差异——其中「直接执行」一组**复用 §1.1 同一次执行的命令与结果**（同一命令串、同一 `-q` 标志），**不另跑改良版命令**；随后给出**单一结论**：有效（解决了不可写导致的失败）/ 部分有效（只解决部分）/ 未解决。结论必须附两组执行的命令与结果对照。**注意**：该脚本自身属工作区新增未提交文件，其存在即为评审对象之一（§7 索引）。

**§1.3 `.tmp/` 不可访问目录影响（A5）**：只读遍历仓库时已实测 `F:\编程\codex-switch\.tmp\test-dsh-multi\test_concurrent_submission_is_refused-9l54vloh` 触发「拒绝访问（os error 5）」，使 `glob` 整体失败。需判定该目录是否会导致常规判定命令 `python -m unittest discover -q -s tests` 失败或异常退出——判定所依据的 `unittest discover` 执行结果**复用 §1.1 的同一次执行**（同一命令串、同一 `-q` 标志），不另跑改良版命令；给出**单一判定**并附证据。**不要求也不允许修改这些目录权限**——只判定、只记录。

### §2 维度① 正确性与稳定性

取证面：异常吞并（`except Exception` / `except (...)` 的覆盖面与实际后果）、静默失败、资源未释放、路径与编码边界、并发与进程树管理、代理协议转换的正确性边界。规划期已定位的**候选**评审面（D 需自行复核并给出准确行号，不得照抄本清单当作结论）：

- `src/codex_switch/ui_v2/script_runner.py`、`process_util.py`：子进程/整树结束与日志编码；
- `src/codex_switch/proxy/**`（`server.py`、`translator.py`、`sanitize.py`）：协议转换与请求清洗的边界处理；
- `src/codex_switch/dsh_instances.py`、`dsh_plugins.py`：进程状态机与异步任务；
- `src/codex_switch/dsh_config.py:28-57`：`write_profile_to_dsh` 的校验与错误路径；
- `src/codex_switch/ui_v2/plugin_bridge.py:88-105`：`_call` 把插件异常收敛为 `{"ok": False}`（第三方代码隔离，属有意设计——若无实际问题不得凑条目）。

**判据**：每条必须指出「触发条件 → 错误后果」，不能只写「可能有问题」。

### §3 维度② 测试与工程化（lint / CI / 测试可在 Windows 跑通）

规划期已实证的评审面：

- **无 lint / 类型检查配置**：全仓库 grep `ruff|flake8|mypy|black|isort|pytest` **零命中**（`pyproject.toml` 25 行仅 setuptools 打包与动态版本，无 `[tool.ruff]`/`[tool.mypy]` 等）；亦无 `.flake8`、`.pre-commit-config.yaml`、`.editorconfig`。→ 需给出可定位的证据与具体改法（如在哪加哪个配置、覆盖哪些目录、预期收益）。
- **CI 覆盖面**：`.github/workflows/release.yml:54-57` 仅 `python -m unittest discover -v -s tests`（且只在 `workflow_dispatch` 与 `v*` tag 触发，无 PR/push 到主干的日常校验）；:39-44 为 Linux 装 Qt 运行库；无 lint 步骤。→ 给出具体改法（触发条件、新增步骤、矩阵）。
- **测试入口与 Windows 可跑通**：`README.md:166-171` 给出 `compileall` + `unittest discover`；`tests/helpers.py:25` 用 `Path.cwd()/".test-temp"`，`tests/test_dsh_multi.py:32,41`、`test_plugins.py:36,45`、`test_codebuddy_plugin.py:26,35`、`test_codebuddy_accounts.py:24,36`、`test_cli_history.py:29,34` 用 `PROJECT_ROOT/".tmp"/...` + `tempfile.mkdtemp(dir=...)`——**两套临时根并存**且都要求仓库目录可写；`tests/test_plugins.py:42`、`test_terminal_review.py:243` 有注释说明「受限环境下系统临时目录会被拒绝写入」。→ 这是「测试可在 Windows 跑通」的核心取证面。
- **`tests/__pycache__/_leak_guard.cpython-313.pyc` 残留**：`tests/__pycache__/` 下有 `_leak_guard.cpython-313.pyc`，但仓库内 grep `_leak_guard` **零命中**（无对应 `.py`）→ 疑似已删模块的陈旧产物；`.gitignore:2` 已忽略 `__pycache__/`，需判定其是否影响测试收集，给出改法或标注为「推测、待验证」。

**判据**：每条须落到具体文件/行号；「建议增加测试」这类无定位表述一律判为不合格。

### §4 维度③ 依赖与安全配置

规划期已实证的评审面：

- **依赖清单三处不一致**：`pyproject.toml:13-16` 只声明 `PySide6-Essentials` 与 `ttkbootstrap`；`requirements.txt:1-17` 额外含 `pywinpty>=2.0.0`、`pyte>=0.8.0`、`psutil>=5.9.0`（AI 终端所需）；`requirements-build.txt:1-9` 再多了固定版 `pyinstaller==6.19.0` 并重复前三项。即 `pip install .` 与 `pip install -r requirements.txt` 装出的环境不同 → 需给出具体改法与影响判断。
- **敏感信息与忽略规则**：`.gitignore:23-38` 忽略 `.codex/`、`.claude/`、`.env`、`*.env`、`*.local`、`*.log`、`.mcp.json` 等；`README.md:210-211`、`:256-259` 声明项目模板生成的 `.codex/local.env` 含 API Key 且不应提交，`.gitignore:44-46` 有受管忽略块。需核对是否覆盖到位（例如 `*.jsonl`、`*-trace.txt` 是否足够），给出可定位结论。
- **密钥落盘与注入方式**：`src/codex_switch/dsh_config.py:28-57` 把 API Key 写入**当前进程环境变量**（`os.environ[DSH_API_KEY_ENV] = api_key`），配置文件只存 `apiKeyEnv` 引用（:85）——属有意设计；需评估其安全含义与边界（进程生命周期、子进程继承）并给出结论，不得无据指为缺陷。
- **CI 权限面**：`.github/workflows/release.yml:9-10` `permissions: contents: write`（发布所需）、`:32/:35/:63/:80` 使用未固定 SHA 的第三方 action（`actions/checkout@v4`、`actions/setup-python@v5`、`actions/upload-artifact@v4`、`actions/download-artifact@v4`、`softprops/action-gh-release@v2`）→ 给出可定位的供应链风险结论与改法（如固定 commit SHA），并标注严重级别。

**判据**：每条须说明「配置在哪、现状是什么、风险是什么、改成什么」，不得泛泛说「注意安全」。

### §5 维度④ 重复逻辑与复杂度

规划期已实证的评审面：

- **原子写三套写法**：`src/codex_switch/dsh_config.py:201-214` 用 `tempfile.NamedTemporaryFile(dir=path.parent, delete=False)` + `os.replace`；`src/codex_switch/dsh_instances.py:485-495` 用 `path.with_name(f".{path.name}.{os.getpid()}.tmp")` 自拼名 + `os.replace`；`src/codex_switch/codebuddy_core.py:165-178` 注释明确「临时文件名自己拼而不用 `tempfile.NamedTemporaryFile`：后者在某些受限环境下……」+ `os.replace`。三处语义相同、写法各异 → DRY 与一致性评审面，需给出定位与收敛改法（含风险：合并时须保留受限环境那条约束）。
- **临时目录根两套**：`tests/helpers.py:25`（`.test-temp/`）与各测试模块自建的 `PROJECT_ROOT/".tmp"/<name>`（`test_dsh_multi.py:32`、`test_plugins.py:36`、`test_codebuddy_plugin.py:26`、`test_codebuddy_accounts.py:24`、`test_cli_history.py:29`）→ 重复模式评审面，需给出改法。
- **大文件与职责集中**：`src/codex_switch/ui_v2/workspace.py` 2668 行、`ui_v2/controller.py` 1500+ 行（`controller.py:1502` 内联 `import subprocess`）、`tests/test_dsh_multi.py` 1400 行——需以可核对依据（行数、函数数、内联导入等）评估 SRP/复杂度，给出改法。**注意**：不得仅凭行数就判为缺陷，须指出具体后果（如可测性、循环依赖、内联导入的启动成本）。
- **重复的护栏式校验/清洗**：如 `ui_v2/plugin_bridge.py:178` 与 `:206`、`:237`、`:261`、`:265` 的 `dict(payload or {})` / `str(...)` 归一化模式；`forms.py` 的 `_payload_str/_payload_bool/_payload_list` 辅助——判定其是否已足够 DRY，**避免为凑条目把合理设计指为重复**。

**判据**：必须给出「重复在哪几处（逐条 `路径:行号`）、为何算重复、收敛成什么」。

### §6 维度⑤ 文档

规划期已实证的评审面：

- `README.md:3` 描述与 `:20-141` 功能清单是否与当前代码一致（例如是否仍有已移除功能的描述）；
- `docs/releases/` 只有 `v0.2.1.md`、`v0.2.2.md`、`v0.3.0.md`，而 `src/codex_switch/__init__.py:1` 为 `__version__ = "0.3.0"`，且 `tests/test_version.py:85-89` 断言「当前版本的发布说明必须存在」→ 需核对版本/发布说明一致性与该断言的副作用；
- `pyproject.toml:7-9` 注释记录「版本号曾两处漂移长达三个月、203 个提交未反映」→ 可作为文档/流程评审的实例，评估是否已有防复发机制（`tests/test_version.py` 即该机制）；
- `AGENTS.md` 与 `docs/*.md` 之间是否存在陈旧描述；
- 缺 `docs/` 开发/贡献入口、无 CHANGELOG 类文件的判定（须与实际仓库结构核对后再写，不得套话）。

**判据**：每条须给出「文档说 X、代码是 Y」的具体对照（双侧行号）。

## 4. 唯一路径收敛（不留未定分支）

| 可能有分歧的选择 | 本计划采用 | 理由 |
| --- | --- | --- |
| 报告是否落到仓库外/临时目录 | 固定落 `openspec/changes/codex-switch-health-checkup/report.md` | 任务规定产物目录；唯一可写区 |
| 测试用哪条命令 | 固定：判定命令 = `python -m unittest discover -q -s tests`（其退出码单独决定硬标准一）；`python -m compileall -q main.py src tests` 仅作同节前置编译检查单独记录、不计入硬标准 | README 明载；不新增 runner（YAGNI）；口径唯一，避免 T2/A3 歧义 |
| `run_tests_writable_tmp.py` 结论怎么写 | 固定「有效 / 部分有效 / 未解决」三选一 + 两组执行对照 | 规格卡要求「给出结论」 |
| `.tmp/` 权限问题怎么处理 | 固定「判定 + 记录」，不改权限、不改代码 | 本轮不做修复 |
| 发现问题怎么办 | 固定「只写报告」 | 规格卡：体检不做修复 |
| 条目编号体系 | 固定 `F<维度号>-<两位序号>` | 保证 §8 与 §2–§6 可集合比对 |
| 同一根因跨维度 | 固定主维度写完整四要素，其余写「见 F<x>-<nn>」 | 避免双份计数导致 A10 失败 |
| 未提交改动如何体现 | 固定用 §7 索引表标注 | 不提交、不修改，但可见 |

## 5. 工程原则应用（KISS / YAGNI / DRY / SOLID）

- **KISS**：体检产物是**一份 Markdown 报告**，不建目录树、不加脚本、不定义 schema 文件、不做机器可读中间格式。固定 `§0–§8` 十节即够；编号体系只用一个正则式可核对的约定。
- **YAGNI**：不新增测试 runner、不引入 lint 工具本身（只在维度②里**建议**是否引入及其配置）、不新增 CI 工作流（只建议）、不为未来「自动化体检」预留抽象。**明确不做的过度设计**：不写报告生成器、不建模板引擎、不建指标采集脚本。
- **DRY**：① 计划内部——验收判据只在 `proposal.md` 定义一次，`tasks.md` 引用编号而不重述；② 报告内部——单源规则（§2–§6 是唯一条目来源，§7/§8 不产生条目）；③ 评审对象——「原子写三套写法」「临时根两套」本身就是被 DRY 审视的实证面。
- **SOLID**：
  - **SRP**：报告按维度分节、每条四要素，读者可按级别取用；`report.md` 只承担「体检结论」一个职责，执行记录（§0/§1）与结论（§2–§6）不混写。
  - **OCP**：维度固定五节，但**节内条目数开放**——新增一个发现只是加一条 `F<x>-<nn>`，不改结构、不改其他节。
  - **ISP**：§7/§8 分别只服务「未提交改动可追溯」与「按级别挑项」两个窄用途，不把全部条目细节塞进汇总表。
  - **DIP**：不适用（本轮无代码）。不得借此插入无关抽象。

## 6. 依赖顺序（可执行性）

```
T1（只读基线固化）
 └→ T2（判定命令 `unittest discover -q -s tests` 执行） ─┬→ T3（runner 有效性结论，复用 T2 结果）
                                                          └→ T4（.tmp/ 影响判定，复用 T2 结果）
 └→ T5 ─→ T6 ─→ T7 ─→ T8 ─→ T9      # 维度①→⑤，按优先级序，各自独立取证，可串行推进
                                      └→ T10（6 文件索引，需 T5–T9 才有编号可引）
                                          └→ T11（汇总排序，需全部条目）
                                              └→ T12（编号集合一致性核对）
                                                  └→ T13a（终局仓库未变核对）
                                                      └→ T13b（收尾行为声明）
                                                          └→ T14a（范围外内容零命中复查）
                                                              └→ T14b（无定位泛泛条目零命中复查）
                                                                  └→ T14c（无证据条目标注复查）
```

- T5–T9 之间**无强依赖**（各维度独立取证），但按优先级序推进以便严重级别判定口径一致；
- T10 依赖 T5–T9（需要条目编号）；
- T11 依赖 T10；T13a–T14c 为收尾核查，必须在报告成稿后执行；
- T2 与其后续 T3/T4 的依赖是「先有判定命令的执行结果，才能判定 runner 与 `.tmp/` 的影响」——T3/T4 **复用 T2 的同一次执行结果**，不另跑改良版命令；
- T13a 只核对仓库文件集合（单一结果），T13b 只出具行为声明（单一结果）；T14a/T14b/T14c 分别只核对「范围外零命中」「无定位泛泛项零命中」「无证据条目标注」三类互不依赖的结果。

## 7. 边界与错误处理的任务映射

| 边界/异常情形 | 处理方式 | 对应任务 |
| --- | --- | --- |
| 测试跑不起来（缺依赖/环境） | 如实记录命令、退出码、失败原因；不装依赖；结论写为环境事实 | T2（`proposal.md` §3.7） |
| `compileall` 通过但判定命令失败（或反之） | 以**判定命令** `python -m unittest discover -q -s tests` 的退出码为准；`compileall` 仅作前置检查单独记录 | T2（口径唯一） |
| `run_tests_writable_tmp.py` 无法区分两种执行 | 明确写「未解决」并附两组对照，不得含糊 | T3（对照组复用 T2 结果） |
| `.tmp/` 导致遍历/收集失败 | 判定为环境事实并记录影响范围；不改权限 | T4（依据复用 T2 结果） |
| 某条结论找不到仓库证据 | 标注「推测、待验证」，不写成确定语气 | T5–T9 条目撰写 + T14c 全文复查 |
| §8 与 §2–§6 编号不一致 | 以 §2–§6 为准修正 §8，重跑集合比对 | T12 |
| 发现某问题位于 6 个未提交改动区域内 | 在 §7 索引表对应行标注，不修改该文件 | T10 |
| 扫描过程中产生临时文件 | 使用既有 `.test-temp/`/`.tmp/`（已被 `.gitignore` 忽略） | T13a 复核 |
| 收尾发现未提交集合变化 | 立即停止并说明来源，不得提交或回滚 | T13a |
| 报告含范围外内容 / 无定位泛泛项 / 无证据条目 | 分别删除或改写为合规形式，不得以「补充说明」保留 | T14a / T14b / T14c（各自单判据核查） |
| 收尾行为声明与实际执行不一致 | 说明原因后以实际执行为准修正声明 | T13b |

## 8. 已知环境事实（供 D 参考，不作为结论）

规划期只读自查中真实遇到、D 会复现的环境现象，**属环境而非仓库缺陷**，除非 D 能定位到仓库代码证据：

1. `.tmp/test-dsh-multi/test_concurrent_submission_is_refused-9l54vloh` 目录「拒绝访问（os error 5）」，使全仓 `glob` 失败（改用 grep/精确 read 可绕过）→ T4 判定；
2. 规划期 P 会话的写护栏一度拦截所有路径（已由人工重载插件进程修复，本轮写探针 `openspec/changes/probe.md` 已放行并清理）；该缺陷属 DSH 侧，**不进报告条目**（out_of_scope 5）。
