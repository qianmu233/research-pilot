# ResearchPilot 工程冻结归档

归档日期：2026-10-21（Asia/Shanghai）。**工程 MVP 已完成；真实模型质量验收未完全通过；B/E 为保留的已知失败。** 工程冻结表示当前工程范围停止开发，不表示模型质量全过，也不是生产级可靠的深度研究系统。历史“不能封板”指质量验收条件尚未满足，不妨碍此次带已知失败的工程MVP归档。

## Git 与归档完整性

后续本地Git基线更新（2026-10-21）：用户另行授权在本目录建立main分支的工程预览初始提交，67项冻结文件保持原字节，不设远端、不推送。过程与API兼容性只读核验见[专项说明](LOCAL_BASELINE_AND_API_AUDIT.md)。下面“不是Git仓库”是先前归档检查的历史事实；FREEZE_MANIFEST中的git_repository=false也保留该历史时点，不改写原始记录。当前状态以本地git status/log为准。

在项目根目录实际执行git rev-parse、git status --short --branch、git log，均返回“not a git repository”。当前目录及其父目录不提供可用Git仓库；没有当前分支、HEAD/提交或可比对工作区。**不能宣称Git clean，也不能凭现有文件推断此前没有任何意外改动。** 本轮未初始化仓库、创建提交/远端或推送GitHub。

Phase7.1既有记录中的8个文件（local_llm.py、两份数据集、真实模型测试、Phase7合约测试、三份依赖锁）逐个哈希一致。本轮归档前对85个项目文件建立快照，结束再比对；变化仅允许为归档文档，产品源码、Prompt、参数、测试、金标、配置、许可证和依赖锁保持字节不变。

公开的[冻结清单](FREEZE_MANIFEST.json)保存67个非Markdown源码/测试/配置/基准等文件的SHA256，全部与本轮修改前一致；另保存28份既有本地验收证据的路径/哈希引用，不包含其正文、运行数据库、私钥或权重。它是文件完整性清单，不是Git提交、签名或正确性证明。本机审计证据在`data/archive-20261021/`，包含修改前清单、文件分类/脱敏扫描结果和最终比对。没有创建新压缩包、wheel或镜像，既有build/egg-info为历史生成物，不应当作本次冻结构建交付。

## 成果与验证边界

| 分类 | 可核实事实 | 不能据此声称 |
|---|---|---|
| 已实现 | FastAPI导入/任务/报告/轨迹/手动resume；同一张五节点LangGraph；SQLite任务与SQLiteSaver；显式Mock/本地Ollama；调用预算/截止时间；来源ID/原文校验 | 自动事实验证、通用智能研究能力、任意工具执行 |
| 已实现且有真实依赖验收 | BGE英384维/中文512维独立PgVector表，token切片、余弦检索、完整来源元数据、事务回滚；词面显式降级；独立HTTP/Docker和重启查询 | 大规模ANN性能、自动索引迁移/故障切换、生产QPS |
| 真实模型通过的有限场景 | A单文档、C有限补检索、D无答案拒答、F即时超时；真实结构化计划/判断/报告与持久化在这些样本实际执行 | 同类问题一定通过、F真实模型任意长迟到回调已全面观察 |
| 质量失败/不确定 | B/E过度拒答保留；原E重复0/3，D2/2；历史7条事实6 supported、1 uncertain；温度0仍波动 | 100%报告准确率、稳定跨文档问答、普遍抗Prompt Injection |
| 尚未实现/验证 | 生产认证、持久队列、自动崩溃调度、多实例一致性、通用语义蕴含验证、规模性能；P3 MCP/多Agent；收费服务适配器的真实远端调用 | 生产级可靠、多智能体协同、已经接入P3或付费搜索 |

沿用最后实际结果：48项回归/合约通过；独立真实A/B/C/D/E/F为4通过/2失败，E/D追加1通过/1失败。不是54项混合全通过。Ruff、宿主机/容器pip check及Docker/HTTP/持久化/重启查询为前次实际验收，本次只核验既有证据/文件，没有重跑这些测试或模型评测。详见[TEST_REPORT](../TEST_REPORT.md)、[Phase7.1原始终审](PHASE71_FINAL_REVIEW.md)。

中文检索固定19文档/20题，Phase6.1无查询指令Recall@5=1.0、MRR@5=0.96875；这是小型检索集指标，不是报告准确率、无答案拒答率或生产性能。模型固定版本/量化/哈希和GPU资源沿用[本地模型报告](PHASE7_LOCAL_LLM.md)，本次不安装/启动/更新模型。

## 三个演示与两个失败

优先只读回放历史JSON，再按需选择已有测试的单场景现场复现。完整问题、资料、命令、隔离集合、输出位置和判断标准见[演示指南](DEMO_GUIDE.md)。A展示充分证据下的单文档研究；C展示首轮不足后新增来源；D展示有候选但仍合理拒答。B/E单独列为失败复现，不用“未观察到攻击执行”代替E正常回答质量通过。

复现依赖现有本地权重、Ollama0.40.6和专用PgVector；缺少就报告环境缺失，不下载新模型、不切Mock冒充。现场运行会产生模型调用和新测试数据，冻结归档本身不执行它们。

## 简历项目事实清单

| 内容 | 归属和事实 | 证据/限定 |
|---|---|---|
| 上游参考 | 参考langchain-ai/open_deep_research的规划、检索、补查、报告思想，保留MIT来源说明 | 非复制整个仓库；不主张上游benchmark、多研究员或MCP成果为本项目贡献 |
| 框架/预训练资产 | LangGraph/LangChain、FastAPI、PgVector、BGE、Qwen、Ollama均为第三方依赖/模型 | 没有自研Agent框架、向量数据库、Embedding或训练LLM |
| 本项目实现 | 独立的有界五节点图和State、适配器接线、文本导入、元数据与引用校验、SQLite任务/检查点对账、调用预算/超时/手动恢复、HTTP接口及部署 | 源码位于research_pilot；“独立实现”针对应用工程，不针对底层依赖 |
| 本项目验证工作 | 真实图、向量模型/数据库/HTTP/Docker验收；固定中文数据集及评测；真实LLM定向场景和失败诊断 | 回归48项中有Mock/Fake/合约；真实LLM另列，B/E不隐藏 |
| 允许写的工程结果 | 中文512维模型与旧384维索引隔离；命令/参数兼容修复；实际恢复/超时/错误引用保护 | 不将数量/引用白名单表述成确定性语义充分性或事实保证 |
| 必须说明的限制 | 本地单实例研究MVP；质量验收未全过，B/E为已知失败 | 不写“生产级”“100%准确”“完全抗注入”“自动事实核验” |

适合实习简历的描述（使用者应能解释对应源码和失败）：

> **ResearchPilot｜本地研究工作流MVP（Python、FastAPI、LangGraph、PgVector）**：参考Open Deep Research思想，独立实现有界规划—检索—补查—报告流程，接入本地Qwen3 4B与中文BGE检索；实现SQLite检查点恢复、持久化调用预算、超时状态对账与来源/摘录校验。完成48项回归/合约测试及真实HTTP、数据库、Docker验收；真实模型A/C/D/F通过，B/E过度拒答作为已知质量失败保留，项目按工程MVP冻结。

篇幅有限时，保留“本地MVP”和质量边界，检索指标可不写；不要把6 supported/1 uncertain换算成系统准确率。外部来源与MIT/模型许可证见[THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md)，不得移除。

## 源码学习顺序

1. README、本文、TEST_REPORT与DEMO_GUIDE：先分清工程实现、真实验证和保留失败。
2. `schema.py`→`config.py`：任务/来源/计划/判断/报告Schema，以及默认Mock和显式后端/限额。
3. `api.py`→`runtime.py`：HTTP边界、后台运行、服务资源、任务收口与恢复入口。
4. `workflow.py`：同一张五节点图、真实/Mock分支、有限循环、模型调用预留和节点deadline。
5. `retrieval.py`→`vector.py`：词面/神经检索、分片、模型固定身份、维度隔离、事务和来源字段。
6. `evidence.py`→`local_llm.py`→`chat_tokens.py`→`model.py`：稳定ID、引用/摘录校验、结构化请求、Tokenizer预算、Mock/兼容适配器。模型assessment不等于事实验证。
7. `store.py`再回看`runtime.py`：SQLite持久预算、事件、状态/checkpoint对账与失败恢复。两个SQLite文件没有跨库原子事务。
8. `tests/test_langgraph_integration.py`、`test_pgvector_integration.py`、`test_recovery_integration.py`、`test_phase7_contracts.py`；再读`tests_real/test_local_llm.py`及固定benchmark：区分真实依赖、模拟传输、固定故障与真实模型质量。
9. 最后读PHASE71_FINAL_REVIEW、原始B/E JSON和候选失败，练习解释为何“ID合法”仍可能不足/不正确。

文件路径均相对于research_pilot目录或项目tests目录，阅读不需要启动服务或调用模型。

## 本机文件与敏感信息检查

2026-10-21只做本项目范围检查；80份源码/配置/文档/测试/benchmark文本未命中所查provider token或私钥正文模式，未发现实际`.env`/`.env.*`文件（`.env.example`是空密钥模板）。源码中的数据库账号为专用本地公开demo，Ollama兼容适配器使用无秘密占位值，未读取进程环境中的真实API Key。模式扫描不等于完整密钥审计或无秘密担保。

| 本机存在的文件 | 本次处理 | 对外源码/归档边界 |
|---|---|---|
| data/约6.18GB（十进制，盘点时含权重/工具/证据） | 保留，未清理 | 整目录排除，不打包/上传；历史JSON/XML可先单独脱敏审核再选择导出 |
| data/models、data/ollama-models、data/tools | 模型权重/Tokenizer/便携Ollama保留 | 不随源码复制；保留官方身份锁与下载说明 |
| data下SQLite、checkpoint、日志/失败快照 | 保留全部真实记录 | 不是源码；可能含提问/资料，不盲目整体分享 |
| data/ollama-home/.ollama/id_ed25519 | **发现私钥文件路径，仅做元数据检查，未读取内容、未删除** | 本地Ollama生成的运行身份私钥，必须排除；本次未曝光或导出，不能因位于测试目录就公开 |
| .venv约0.98GB、build、egg-info、Python/pytest/Ruff缓存 | 保留 | 生成物不随源码交付，不复用旧包当新归档 |
| Docker运行数据库/任务卷 | 本轮未访问或修改内容，前阶段已验收 | 卷不在源码清单内，不导出、不删除；冻结不等于停止服务 |

`.gitignore`和`.dockerignore`已有env/data/虚拟环境/日志/生成物排除规则，Dockerfile也仅显式复制源码/锁/说明。**当前无Git仓库，这些规则并不证明任何文件从未被提交；也不约束手工压缩整个文件夹。** 对外源码应使用明确允许清单：research_pilot、scripts、tests、tests_real、benchmarks、examples、docs（不含运行目录），根README/ARCHITECTURE/DEVELOPMENT/TEST_REPORT/INTERVIEW_GUIDE、LICENSE/THIRD_PARTY_NOTICES、pyproject、三份requirements锁、Dockerfile/Compose和ignore模板。不得一键压缩整个含data的工作目录。

发现运行私钥和体积较大的生成物已在此报告，但没有进行删除、迁移、密钥轮换或修改用户数据；后续如需清理必须另获明确指示。此次只完成本地文档归档，没有上传、发布或新建远端。

## 冻结后的未解决问题

B/E充分性判断会增加额外要求，缺乏可靠修复；温度0不能保证一致输出；A3表述仍uncertain；引用/原文合法不是蕴含或事实真值验证；小型中文集高Recall不能保证无答案证据安全。没有生产认证/持久队列/自动崩溃调度/多实例/性能保障，Python同步超时不能强杀底层线程，任务表与checkpoint非同一事务。MCP、多Agent、前端、付费模型/搜索均不扩展。

除用户明确开启新的工作外，不继续功能开发、Prompt优化、模型替换或重复全量评测。所有历史失败保留；工程MVP按上述边界冻结。
