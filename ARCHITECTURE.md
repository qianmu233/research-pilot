# ResearchPilot 架构说明

当前实现包含 Ollama 与显式 DeepSeek Provider；DeepSeek 已有一条公开合成 A 的真实 HTTP 闭环证据，B/E 未验证，Qwen B/E 失败保留。测试历史见 [TEST_REPORT](TEST_REPORT.md)。以下早期 Phase 记录保留其当时口径。

## 运行链路

Phase7.2开发分支新增显式deepseek模式：DeepSeekStructuredModel复用LocalStructuredModel的消息构造、三份Schema和同一5节点图，只替换Provider预检、输入预算计数与请求协议（json_object、本地严格Pydantic，禁用thinking，输出max_tokens）。调用预算/300秒deadline/失败恢复由原结构化路径执行；任务记录Provider、请求模型/端点，事件记录响应模型/用量/结束原因，恢复时禁止身份漂移。新错误分类只持久化安全码，不保留SDK异常原文。原Ollama身份/Tokenizer/json_schema保留，旧openai模式仍为历史适配器，不等同新DeepSeek。新增30项离线TCP合约通过，用户一次真实规划冒烟和一条公开合成A的HTTP完整研究成功；详见[Phase7.2](docs/PHASE72_DEEPSEEK_PREVIEW.md)。[Phase7.3](docs/PHASE73_DEEPSEEK_HTTP_A.md)仅增加受控HTTP实验脚本，不改变本图；Docker恢复后4项离线预检通过，A实际plan/retrieve/assess/write/validate、1轮3请求。下面冻结架构为main历史；单条成功不覆盖Qwen B/E失败或证明生产可靠性。

**工程冻结状态（2026-10-21）：工程 MVP 已完成；真实模型质量验收未完全通过；B/E 为保留的已知失败。** 本文描述冻结实现；历史测试结果以[最终审核](docs/PHASE71_FINAL_REVIEW.md)为准，归档范围见[工程归档](docs/ENGINEERING_ARCHIVE.md)。不将工程冻结称为质量全部通过或生产级可靠。

显式ollama路径已经完成真实HTTP与Docker验收，复用本图、ChatOpenAI与SQLiteSaver。固定Qwen manifest和官方Tokenizer；ChatOpenAI通过extra_body.max_tokens发送Ollama实际执行的输出上限。输入按官方Tokenizer计数，保留输出及128-token模板余量，超过预算提前失败，不静默截断证据。结构化报告语法枚举原文摘录，随后程序复核来源与摘录；不可信文档只在human数据中，不进入system。JSON解析错误不静默修复或回退。早期[接入准备](docs/PHASE7_PREFLIGHT.md)仅作历史记录。

真实模型以充分性判断控制补检索，最多3轮；研究状态持久化到research_json。model_budgets在请求前预留调用数，失败/恢复不归零，并记录安全调用事件；验收参数最多5次、300秒，从首次调用计时，恢复不重置，节点前后检查截止时间。固定验收上下文4096、输出768、temperature=0、reasoning_effort=none，单并行；默认Mock与词面后端保留，不会静默切到真实模型。

报告要求逐条 source_id 与原文 quote；校验 ID 和摘录后更新 research.citation_valid，research.facts_verified 始终 false。模型 assessments[].sufficient、程序引用检查与事实核查相互独立；不足时允许无 claim 拒答。原 Mock 与旧 openai 行为保留。下文为已验收 Phase 6.1 的实现说明。

```text
HTTP 文本导入 -> lexical: SQLite 字符分片
             -> pgvector: 模型 token 分片 + BGE (英文ONNX / 中文PyTorch) + PostgreSQL
HTTP 任务提交 -> SQLite tasks -> FastAPI BackgroundTasks
  -> LangGraph START -> plan -> retrieve -> assess -> write -> validate -> END
                                  ^          |
                                  +----------+ ollama判断不足且有补查词、未达轮次上限
  -> SQLiteSaver checkpoints + SQLite tasks 报告/状态/轨迹
```

Mock分支按候选数量控制收集停止，不声称语义充分；ollama分支使用模型assessment。两者均可能以evidence_status=unverified完成，模型认为充分不等于程序证明事实正确。

`config.py` 从环境读取、校验后端及限额；默认离线 Mock 与词面检索。密钥和 DSN 不出现在 Settings 的 repr。
`store.py` 负责本地任务、字符语料和工具错误，兼容旧 tasks 表自动增加 `tool_errors_json`。
`vector.py` 提供真实本地 Embedding、token 分片、数据库事务和 pgvector 余弦检索。
`retrieval.py` 合并本地与可选外部结果；`evidence.py` 稳定分配来源 ID 并去重。
`workflow.py` 定义五节点图、有界分支与节点超时输出拒绝。
`runtime.py` 负责图执行、checkpoint 和任务表对账；`api.py` 提供 HTTP。

## 两种检索模式

`lexical`是SQLite上的中文二元字符/英文词项余弦检索，不生成神经向量。`pgvector`有两个显式profile：旧英文BAAI/bge-small-en-v1.5使用FastEmbed/ONNXRuntime、384维；当前中文演示使用官方BAAI/bge-small-zh-v1.5 safetensors、CPU PyTorch/Transformers、512维。均采用CLS/L2归一化，经Psycopg保存并用`<=>`余弦距离排序。384/512维表及集合身份隔离，旧模型/数据保留。当前为精确扫描，没有HNSW或规模性能保证。

向量分片使用实际模型 tokenizer 的原文 offsets，默认 256 tokens、重叠 32，预留特殊 token 空间；不改变推理 tokenizer 的截断设置。数据库 collection 记录模型名与维度，防止混用模型类型。每份文档所有分片在一个数据库事务内插入，第二片插入失败也整体回滚。模型权重下载与服务启动分开，启动仅使用本地缓存。

两个后端的文档索引独立；选择词面模式是显式降级路径，需要重新导入相应文档。未实现自动数据复制与故障时自动切换。向量库/本地语料故障使任务失败，可选外部搜索失败记录安全工具错误并保留已有本地证据。Phase6使用旧英文模型时，固定20题中文Recall@5为0.53125，4个无答案题均有候选；Phase6.1使用官方中文模型改善了检索，但不据此认定报告质量合格。

Phase 6 增加 `embedding.lock.json`，强制固定 ONNX snapshot 与五份文件 SHA256 后加载；没有替换模型或查询编码。查询与文档走同一编码器，均不加前缀，FastEmbed 作 CLS/L2 编码。返回结果新增保存的 document_id/chunk_id/source_ref/score，并保留完整已切分向量片段；API Schema 用可空字段兼容旧来源。相同距离时按 source_ref、chunk_id 排序。评测与原始失败记录见 `benchmarks/zh_retrieval_v1/`。

Phase 6.1 增加显式中文 profile：官方 `BAAI/bge-small-zh-v1.5` safetensors，独立 `embedding-zh.lock.json` 六文件哈希，CPU PyTorch CLS/L2 输出 512 维，写入 `researchpilot_vector_chunks_512` / `researchpilot_vector_collections_512`。模型指纹/维度均验证，384 维旧表不迁移、不删数据。中文查询可选官方指令，文档不加；两种模式的文档向量摘要相同。工厂保留英文默认，`RESEARCH_EMBEDDING_MODEL` 显式选择中文。

Mock数量路由只表示候选收集完成，trace使用assess:candidates_collected；真实ollama路由使用assess:model_sufficient/insufficient。任务表/API的evidence_status为unassessed/no_evidence/unverified；即便模型认为充分，有候选仍保持unverified。completed只描述流程/检查完成，不保证事实正确。图拓扑未变，没有用金标指导运行时。中文基准及近主题无答案风险见docs/PHASE61_CHINESE_EMBEDDING.md。

## State、有界性和来源

State包含`task_id/question/scope/queries/iteration/sources/tool_errors/report/report_status/trace/evidence_status/research`。真实ResearchPlan保存在State/checkpoint，首轮只执行第一条计划查询，后续由模型给出最多两条补查词；每轮来源受max_sources限制，循环最多max_rounds（1–3），另有recursion_limit=20。模型assessment仅是模型判断；本次B/E正是在已取得足够正文后增加了问题之外的条件而拒答。

来源稳定编号 `S1...`；去重依据 locator 和 excerpt。词面来源 locator 为 `local:`，向量来源为 `pgvector:`。引用验证只证明 ID 属于实际检索集合，不证明事实真实或论据蕴含结论。Mock 报告明确标识为确定性摘录。

## 持久化与状态一致性

任务表与 checkpoint 是两个 SQLite 文件，不存在跨库原子事务。运行时以 `thread_id=task_id` 执行 `graph.stream(..., durability="sync")`，异常后读取 checkpoint 对账来源与轨迹。恢复成功会清除旧错误码。若 checkpoint 已到 END，直接将其报告收口到任务表，无需再执行节点。

状态包括 pending、running、completed、failed、timed_out、interrupted。图仍有后续节点但主动暂停时是 interrupted；超时不发布报告；引用失败不发布报告。进程硬退出可能留下 running，重启不会自动调度，需手动 `/resume`。同一进程内 active 集合防止同一个 task 重入；不同任务可在后台线程中执行。SQLiteSaver 与 LocalStore 各自保护数据库连接，不能据此宣称多 worker 或分布式保证。

LangGraph step_timeout限制等待，节点包装器还检查实际执行耗时，拒绝迟到结果写入pending checkpoint。ollama另有持久化整任务deadline和调用预算。Python同步线程不能被强杀，任务收口可能等待提供者退出；提供者必须保持自身HTTP/SQL超时，不能将deadline描述为对底层I/O的硬终止。

## 已验证与未验证

真实图、独立HTTP、神经Embedding/PgVector、SQLite中断/异常/超时/进程硬退出和恢复见TEST_REPORT。真实模型定向A/C/D/F通过，B/E为已知失败；七条历史事实由助手核对为6 supported、1 uncertain，不是自动事实验证或用户签字。部署仍为单实例本地演示，未实现生产认证、持久队列、自动恢复、多实例协调、通用报告质量保证、P3 MCP或并行研究员。没有任意URL抓取或Shell/SQL写工具。兼容接口已连接免费本地Ollama，DeepSeek 已有一条公开合成 A 的真实 HTTP 验证，B/E 未验证；Tavily 未实测。
