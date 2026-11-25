# ResearchPilot 多智能体发布前验收

2026-11-25，验收环境为 Windows、Python 3.12 和仓库锁定的 LangGraph 1.2.16。结果对应开发分支 `feature/multi-agent-research` 的 `205d86a`。发布副本沿用同一源码、测试与新实验记录，并保留既有公开主分支的提交历史。

## 实现与改动文件

| 范围 | 实际文件 |
|---|---|
| API、配置、新旧流程路由 | `research_pilot/api.py`、`config.py`、`runtime.py`、`schema.py`、`.env.example` |
| 多 Agent 工作流 | `research_pilot/multi_workflow.py`、`research_agent.py`、`multi_schema.py`、`multi_mock.py` |
| 结构化模型接入与 SQLite | `research_pilot/model.py`、`local_llm.py`、`store.py` |
| 验证 | `tests/test_multi_agent.py`、`tests/helpers/multi_crash_worker.py` |
| 对照实验 | `scripts/evaluate_multi_agent.py`、`benchmarks/multi_agent_v1/` 中的原 Mock 题目与记录、独立真实验收题、结果和人工复核 |
| 项目展示 | `README.md`、`docs/MULTI_AGENT_FLOW_ZH.md`、本验收 |

原模式仍由五节点 StateGraph 在一个上下文中完成任务，原导入、查询、报告、轨迹和恢复路由继续可用。多模式按问题动态拆分并并行执行局部 StateGraph。全局 Review 只在需要时把补查发给对应子任务。原中文 BGE、PgVector、SQLite 词面检索、模型 Provider 和引用检查继续使用。

| 流向 | 实际行为 |
|---|---|
| 数据流 | `question/scope` → 结构化子任务 → 局部查询、证据和评估 → 去重后的全局来源 → 引用报告 |
| 控制流 | Runtime 按任务模式选图。多模式执行 Supervisor → Send → Worker → Merge → Review。存在缺口时限量补查，完成后写作与程序校验 |
| 状态流 | `task_id/thread_id` 对应主图检查点。子任务表以 `task_id + subtask_id` 持久化独立游标。SQLite 模型账本原子预占，调用时间、次数和可用 Token 共用同一主任务账本 |

## 本轮质量修复

- **计划与检索。** 明确列出的候选产品和维度沿用用户原词，首查以产品名定位候选。候选规格之外的自由主题仍由模型动态拆分。
- **补查与预算。** 全局评估触发补查时，具名比较优先在模型未覆盖或原文未出现相应词项的维度按“候选名 + 维度”检索。词项提示只改变检索调度。补查没有新增原文时复用既有局部评估。证据合并优先保留各 Worker 用过的来源，再按任务轮询填入其他候选。
- **报告与引用。** 本地 Qwen 先选择具体原文段落的编号，程序按该选择还原原文和来源 ID，并执行原有引用校验。结构化冲突需指向两个不同来源的段落，作为待核对判断。模型输出为空或达到上限时，候选材料保留在 API 结果，程序不会把它们写成模型结论。
- **原单 Agent 的 B/E。** 发布前记录确认 B 已检得 PostgreSQL 与 LangGraph 两份资料，E 已检得 PostgreSQL 正常来源。旧评估将命令、组件和含义扩大成 WAL、回滚存储机制或运行时终止流程等额外要求。现在本地 Qwen 先按原问提取各项直接答案，再判断是否缺证据，检索计划只保留线索。B 恢复两轮检索后的回答，E 使用正常来源回答，C 补查和 D 无答案行为仍满足原断言。历史记录见[既有 Qwen 诊断](QUALITY_QWEN_20261022.md)。

## 启动、演示与复现

先遵循 [README 的配置与启动](../README.md)。本机演示可使用仓库虚拟环境。

```powershell
$env:RESEARCH_MODEL_BACKEND='mock'
$env:RESEARCH_SEARCH_BACKEND='none'
$env:RESEARCH_RETRIEVAL_BACKEND='lexical'
$env:RESEARCH_DATA_DIR='./data/multi-agent-demo'
$env:RESEARCH_MAX_MODEL_CALLS='8'
$env:RESEARCH_RETRIEVAL_TOP_K='1'
.\.venv\Scripts\python.exe -m uvicorn research_pilot.api:app --host 127.0.0.1 --port 8010
```

按 [README 企业 RAG 演示](../README.md#演示企业-rag-知识库技术选型)导入五份资料并提交任务。读取 `GET /api/tasks/{id}`、`/report` 和 `/trace`；需要恢复时调用 `POST /api/tasks/{id}/resume`。

## 实际测试

```powershell
docker compose -p researchpilot-multi-agent-test -f compose.yaml -f compose.vector.yaml up -d --pull never postgres
.\.venv\Scripts\python.exe -m pytest -q -rs --tb=short
.\.venv\Scripts\python.exe -m ruff check research_pilot tests tests_real scripts
git diff --check
```

分支初次运行原全量回归时，本地 PgVector 未启动，得到 81 通过、12 失败、7 报错。使用已有镜像启动独立测试库后，重新运行全部默认用例。新增用例使用真实 LangGraph、SQLite 和确定性模型，覆盖动态拆分、并发屏障、上下文隔离、稳定去重、充足直出、局部自主补查、Review 定向补查、跨连接预算原子性、可控超时、进度、重复恢复、独立进程崩溃、空资料库、引用错误和单模式兼容。

| 命令 | 结果 |
|---|---|
| `python -m pytest -q -rs --tb=short` | 124 通过、0 失败、0 跳过，58.86 秒 |
| `python -m pytest -q tests/test_api.py tests/test_core.py tests/test_langgraph_integration.py tests/test_http_integration.py tests/test_recovery_integration.py tests/test_phase7_contracts.py --tb=short` | 原单 Agent 相关回归 27 通过、0 失败、0 跳过，12.52 秒 |
| `python -m pytest -q tests/test_multi_agent.py --tb=short` | 多 Agent 24 通过、0 失败、0 跳过，8.72 秒 |
| `python -m pytest -q tests/test_multi_agent.py -k 'budget or atomic or crash or citation or validation or passage or distinct_source_pair' --tb=short` | 9 通过、0 失败、0 跳过，15 项未选择，4.07 秒 |
| `python -m pytest -q tests_real/test_local_llm.py --tb=short` | 7 通过、0 失败、0 跳过，104.11 秒，含历史失败的 B/E |
| Ruff、`git diff --check`、README 本地链接和实验数据哈希 | 通过 |

独立 Uvicorn 进程的 TCP 演示导入五份资料并提交多 Agent 请求，生成三个子任务。只有 PgVector 收到补查。任务完成时有四个来源、四条通过校验的摘录引用和八次 Mock 调用。

## A/B/C 结果

同样两题、相同资料、Mock 配置和预算，每组完成 6 次。关键证据覆盖为 A 12/21、B 15/21、C 21/21，维度覆盖为 A 27/54、B 48/54、C 54/54。实际写出的引用逐条校验为 12/12、15/15、21/21。平均调用尝试 4、5.5、7.5。Mock 不产生真实 Token。注入故障后，三个模式均完成恢复；C 在一次局部重试和一次定向补查后用完 8 次预算，发布部分报告。详见[实验口径和结果](../benchmarks/multi_agent_v1/README.md)。

发布前用新输出路径复跑 18 次，覆盖、引用和调用数与旧记录相同。原 Mock 结果保留，SHA-256 为 `507298af17300d7453523d9eeddfff9823589642a10a5a33da19a573d17b4e23`。

## 真实模型验证

使用本机 Ollama 0.40.6、固定 Qwen3 4B Instruct 和 SQLite Top-1，最多 8 次调用与 2 轮。在真实 RAG 对照里，A/B/C 分别取到 2/4、3/4、3/4 份关键材料，C 比 B 用时更久。发现 PgVector 运维被错误标为已覆盖后，增加词项检索提示，并用同一 RAG 资料单独复查最终 C。

| 三类多 Agent 验收 | 任务结果 | 调用与 Token | 证据与人工复核 |
|---|---|---|---|
| RAG 技术选型，最终复查 | `completed / partial`，35.37 秒 | 8 次，9,769 Token | 4/4 关键材料、12/12 维度。7/7 引用有效，1/7 完整相关且获证 |
| 企业内部多文档 | `completed / partial`，26.49 秒 | 8 次，8,955 Token | 2/2 关键材料、5/5 维度。4/4 引用有效，3/4 完整相关且获证 |
| 缺少生产实测 | `completed / partial`，26.85 秒 | 8 次，8,695 Token | 没有可支持实测数值的资料。4/4 引用有效且支持资料不足的说明 |

RAG 最终复查经过动态分派、并行首查、两批全局评估、定向补查、报告和引用校验。Ollama 服务一次执行一条推理请求，Worker 编排仍并行。模型在高覆盖下仍可能扩大范围或从摘录推出未经支持的判断。B/E 在原真实套件中均通过，分别用 4 次请求及 3,385 Token、3 次请求及 2,578 Token。D 仍返回证据不足且无结论。真实对照、主子任务记录及逐条人工复核见[真实 Qwen 实验](../benchmarks/multi_agent_v1/REAL_QWEN_REVIEW_20261125.md)。

本轮真实请求均发往本机。云端请求为 0。既有 [DeepSeek 历史验收](DEEPSEEK_BE_RESULTS_20261022.md)和[中文 BGE 检索评测](../benchmarks/zh_retrieval_v1/README.md)保留独立口径。

```powershell
.\.venv\Scripts\python.exe scripts/start_local_ollama.py
.\.venv\Scripts\python.exe -X utf8 scripts/evaluate_multi_agent.py --local-quality-suite --output data/multi-agent-validation/quality-suite-reproduction.json
```

## 实现边界

- 支持单进程 FastAPI 和显式手动恢复。断点可能停留在 `running`，由客户端重新提交恢复。进程内去重可防重复请求绕过活跃集合，SQLite 账本能在并发连接下保持调用上限。
- 多模式只用配置好的本地资料库。当前 API 无企业认证、文档 ACL 或租户隔离。环境变量指定的集合是 Runtime 的资料边界。
- 原文校验只验证来源与摘录，范围覆盖和冲突判断依赖模型及资料质量，`facts_verified=false`。同步提供方即使未响应取消，迟到结果也不会写入图，外部请求可能仍在运行。外部调用在崩溃后可能重放。
- 当前支持 `single` 和 `multi`，进度通过轮询获取。自动决策分流、SSE、可视化前端和互联网搜索未作为本次多模式交付。

源码、合成示例和实验记录达到公开代码与本机演示的发布条件。决策报告的适用范围仍取决于模型、资料和人工复核。现有 HTTP 服务面向本机测试和演示。

## 简历与面试

使用 FastAPI、LangGraph 和 SQLite 实现企业选型研究平台，支持 Supervisor–Worker 并行检索、定向补查、原子调用预算及子任务级崩溃恢复。固定合成题的 18 次 Mock A/B/C 对照中，关键材料覆盖由单 Agent 的 12/21 提至动态模式的 21/21。真实 Qwen RAG 单次复查在 8 次调用内检索到 4/4 关键材料，生成 7 条可追溯引用。

[小白版中文完整流程](MULTI_AGENT_FLOW_ZH.md)
