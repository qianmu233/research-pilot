# ResearchPilot · LangGraph 研究工作流与证据溯源

**Phase7.2/7.3开发分支验收（2026-10-21）：** main工程预览基线保持不变；feat/deepseek-provider沿用原图/预算/来源校验。历史78项回归/合约通过（原48+新增30），用户恢复Docker后新增离线预检4通过；**DeepSeek JSON规划冒烟与一条公开合成A的完整HTTP工作流均已真实执行**。A为3请求、1轮检索、1830 Token、状态completed；报告两条结论对合成来源均supported，引用和Runtime/HTTP重启查询一致。仅限本次资料支持性核查，不等于外部事实独立验证、全部模型质量通过或生产级可靠；DeepSeek B/E未测试。本次只读复核，无新增收费请求。见[冒烟归档](docs/PHASE72_DEEPSEEK_PREVIEW.md)及[Phase7.3实际结果](docs/PHASE73_DEEPSEEK_HTTP_A.md)。分支尚未提交、未合并或推送。

**main冻结历史状态（2026-10-21）：工程 MVP 已完成；真实模型质量验收未完全通过；B/E 为保留的已知失败。** 基线48项回归/合约通过；真实A/B/C/D/E/F为4通过、2失败（B/E），原E三次拒答、D两次正确拒答。七条事实6 supported、1 uncertain，不因新离线合约改变。历史见[归档](docs/ENGINEERING_ARCHIVE.md)、[演示](docs/DEMO_GUIDE.md)、[测试报告](TEST_REPORT.md)和[Phase7.1审核](docs/PHASE71_FINAL_REVIEW.md)。

项目将资料查询组织为：规划 → 检索 → 证据评估 → 有界补充检索 → 报告草拟 → 引用检查。真实LLM判断充分性，Mock仅控制候选收集；二者都不等于事实验证。参考 [LangChain Open Deep Research](https://github.com/langchain-ai/open_deep_research) 的工作流思想独立实现；保留上游来源与 MIT 声明，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。上游归档审计保留在 `docs/STAGE0_UPSTREAM_AUDIT.md`。

Phase7.2之前的Git基线/只读API核验保留在[历史说明](docs/LOCAL_BASELINE_AND_API_AUDIT.md)：旧openai后端仍是旧路径。新开发分支应显式选择deepseek，而非仅更换openai的地址；当前已验证一次真实规划冒烟及单条公开合成A的远端完整研究。main的67项冻结清单保持历史原样。

## 已实现与边界

**Phase 7 实际结果：** 用户确认后只下载一个Qwen3 4B Q4_K_M。真实结构化规划、充分性判断、补检索、报告与引用/原文校验已执行，修复了Ollama忽略SDK输出上限字段的问题。历史 [接入准备](docs/PHASE7_PREFLIGHT.md) 保留；当前以 [Phase7记录](docs/PHASE7_LOCAL_LLM.md) 为准。公开事实核对与程序引用检查分开统计。

| 能力 | 实际证据 |
|---|---|
| LangGraph 1.2.16 五节点图、最多 1–3 轮检索 | `tests/test_langgraph_integration.py`，真实图执行 |
| FastAPI 文本导入、任务、报告、状态、轨迹 | `tests/test_http_integration.py`，独立 Uvicorn、真实 TCP、重启查询 |
| SQLite 词面检索 | `tests/test_core.py`，保留为可选择的本地降级模式 |
| 本地 BGE Embedding + PgVector | 保留英文 ONNX 384D；新增官方中文 safetensors 512D 独立表，真实数据库验收 |
| token 分片、事务回滚、向量持久化 | 同上，使用模型 tokenizer，第二分片数据库拒写后整体回滚 |
| SQLite Checkpointer 中断、失败、超时、进程崩溃后手动恢复 | `tests/test_recovery_integration.py`，真实 StateGraph/SQLiteSaver |
| 工具错误与非法引用路径 | `tests/test_retrieval_errors.py` 及恢复测试 |
| ChatOpenAI / Tavily | 本地Ollama兼容接口已实测；Tavily未调用 |
| 中文检索基准与证据完整性 | Phase 6.1 中文 Recall@3/5=1.0、MRR@5=0.96875、多文档4/4；无答案仍有误候选，不能等同报告质量 |
| 真实模型小型质量验收 | 五个固定中文任务，Phase7.1的B/E过度拒答失败；不是通用报告准确率 |
| P3 MCP、并行研究员 | 未实现 |

## 安装与本地运行

本机已验证 `E:\anaconda3\python.exe` 为 Python 3.12.3；可使用任何已确认版本为 3.12 的 `python`。本机没有 `py` 启动器。

```powershell
cd E:\codeplace\llm-agent\research-pilot
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
$env:RESEARCH_MODEL_BACKEND='mock'
$env:RESEARCH_SEARCH_BACKEND='none'
$env:RESEARCH_RETRIEVAL_BACKEND='lexical'
.\.venv\Scripts\python.exe -m uvicorn research_pilot.api:app --host 127.0.0.1 --port 8010
```

另一个终端执行：

```powershell
.\.venv\Scripts\python.exe scripts/smoke_http.py --backend lexical
```

打开 `http://127.0.0.1:8010/docs` 可导入 `examples/research-notes.md` 并提交任务。后台任务提交返回 202，需要轮询状态；无证据时返回明确标注的无证据报告。

## 免费本地语义检索

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-vector.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e '.[vector]'
.\.venv\Scripts\python.exe scripts/download_embedding.py --cache-dir data/models
docker compose -p researchpilot-acceptance -f compose.yaml -f compose.vector.yaml up -d --wait postgres
$env:RESEARCH_RETRIEVAL_BACKEND='pgvector'
$env:RESEARCH_POSTGRES_DSN='postgresql://researchpilot_demo:researchpilot_local_demo@127.0.0.1:15432/researchpilot_demo'
$env:RESEARCH_EMBEDDING_CACHE_DIR='./data/models'
.\.venv\Scripts\python.exe -m uvicorn research_pilot.api:app --host 127.0.0.1 --port 8010
```

这是CPU上真实的预训练神经Embedding，无模型API费用。旧默认英文profile加载BAAI/bge-small-en-v1.5并校验embedding.lock.json；中文演示显式选择下面的官方512维profile，不能把英文默认配置当中文验收配置。余弦相似度阈值默认0.5，不是答案置信度。冻结归档不执行首次下载或模型替换。

Phase6历史：保持英文模型、无前缀编码、阈值与标注不变，修复来源元数据和片段完整性，阶段33项通过；当时报告为Mock，后续Phase7已接入本地真实LLM。详见[20题数据及结果](benchmarks/zh_retrieval_v1/README.md)和[Phase6复核](docs/PHASE6_CHINESE_RETRIEVAL.md)。

**Phase6.1历史结果为39项通过；冻结基线为48项回归/合约通过，真实模型另列。** 官方 `BAAI/bge-small-zh-v1.5` revision `7999e1d3359715c523056ef9478215996d62a620` 已通过 CPU PyTorch/safetensors 接入，写入独立 vector(512) 表，旧 vector(384) 与历史结果保留。同一固定集上，中文无指令 / 有指令的 Recall@3/5 都为 1.0、MRR@5 分别为 0.96875 / 0.95833。4 个无答案题仍有 3 个返回候选，任务和报告现在明确标记 `evidence_status=unverified`，不以候选数量声称语义充分。详见 [Phase 6.1 报告](docs/PHASE61_CHINESE_EMBEDDING.md)。

显式选用中文候选（旧默认保持英文，避免静默切换既有索引）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-chinese.lock
.\.venv\Scripts\python.exe scripts/download_embedding.py --model BAAI/bge-small-zh-v1.5
$env:RESEARCH_EMBEDDING_MODEL='BAAI/bge-small-zh-v1.5'
$env:RESEARCH_EMBEDDING_QUERY_INSTRUCTION='false'
$env:RESEARCH_VECTOR_COLLECTION='chinese-default-v1'
```

仍需开启pgvector并向所选集合导入文档。完整pytest要求中英文模型缓存和Chinese extra，不跳过缺环境的测试。compose.zh.yaml是早期叠加配置；真实中文/聊天模型容器验收使用compose.local-llm.yaml。Phase7早期[只读调查](docs/PHASE7_ENVIRONMENT_SURVEY.md)是安装前历史，后续已运行Ollama/Qwen；冻结演示入口以[演示指南](docs/DEMO_GUIDE.md)为准。

`lexical` 和 `pgvector` 使用各自的文档索引；切换模式需要向该索引重新导入文本。不会把向量库故障静默伪装成“无证据”，也不会自动迁移索引。

## 完整测试与容器

完整测试需要 vector 依赖、本地模型缓存及上述专用 PostgreSQL；缺少环境会真实失败，不跳过数据库测试。

Phase 6.1 完整测试请先安装 `requirements-chinese.lock` 并下载两份固定模型；`requirements-vector.lock` 仍用于只运行旧英文部署，不能满足新增中文测试。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check research_pilot tests scripts
# 纯词面容器
docker compose -p researchpilot-lexical build
docker compose -p researchpilot-lexical up -d --wait
.\.venv\Scripts\python.exe scripts/smoke_http.py --backend lexical
docker compose -p researchpilot-lexical down
# 向量容器（先下载权重）
docker compose -p researchpilot-acceptance -f compose.yaml -f compose.vector.yaml build
docker compose -p researchpilot-acceptance -f compose.yaml -f compose.vector.yaml up -d --wait
.\.venv\Scripts\python.exe scripts/smoke_http.py --backend pgvector
```

两种模式默认都使用本机 8010 端口，请顺序启动。`down` 不删除数据卷。Compose 中数据库账号仅为专用本地演示账号。

## HTTP 与恢复语义

| 路由 | 方法 | 行为 |
|---|---|---|
| `/health` | GET | 进程健康与运行模式，不是数据库就绪探针 |
| `/api/documents/text` | POST | 返回文档 ID、分片数和真实索引类型 |
| `/api/tasks` | POST | 202 提交后台研究任务 |
| `/api/tasks/{id}` | GET | 状态、来源、报告、轨迹、安全错误码和工具错误 |
| `/api/tasks/{id}/report` | GET | 完成后返回 Markdown，否则 409 |
| `/api/tasks/{id}/trace` | GET | 节点轨迹及工具错误 |
| `/api/tasks/{id}/resume` | POST | 手动继续已有 checkpoint；已完成任务返回 409 |

终态包括 `completed`、`failed`、`timed_out`；图在节点边界暂停时为 `interrupted`。进程硬崩溃可能遗留 `running`，需要显式 `/resume`。已到 END 的 checkpoint 可对账任务表，不重复生成报告；非法引用不会发布报告。只有同一进程内的同一任务具备并发去重保证。

## 仍然存在的限制

单实例 BackgroundTasks 不是持久队列；不支持多 worker 分布式调度、自动恢复或 exactly-once。节点超时会拒绝迟到结果，但 Python 线程无法硬终止阻塞的同步提供者，仍依赖 HTTP/数据库自身的超时。来源数量判定不是语义证据充分性；引用 ID 白名单不是事实或蕴含校验。API 没有生产身份认证，只监听本地演示。检索正文是不可信数据，项目不注册 Shell、SQL 写工具，也没有通用 Prompt Injection 检测。

详见 `ARCHITECTURE.md`、`DEVELOPMENT.md`、`INTERVIEW_GUIDE.md`。
