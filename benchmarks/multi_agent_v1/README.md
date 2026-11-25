# 多 Agent 企业选型对照实验 v1

两道题分别比较企业 RAG 知识库技术（PgVector、Milvus、Elasticsearch）和日志平台（OpenSearch、Loki）。[资料与人工标注](dataset.json)为虚构企业的公开合成材料，每题都有候选概览、至少一份需要定向检索的详细资料和一份干扰资料。文档内容只用于演示内部决策流程。

## 实验设置

| 组别 | 实际执行路径 |
|---|---|
| A 原单 Agent | 原五节点结构化 StateGraph。第一次检索使用完整问题，局部评估最多再给出一条缺口查询 |
| B 固定并行 | 使用相同主图与 Worker，规划阶段返回题目预先给出的候选列表。关闭局部重查和 Review 定向补查 |
| C 动态多 Agent | 使用生产多 Agent 工作流。确定性 Mock 从问题拆分候选，Review 针对未覆盖的目标和维度提出补查 |

每组采用同一个脚本化 Mock 模型系列、SQLite 词面检索和相同资料，配置每次 Top-1、最多 2 轮、8 次模型尝试及 8 条合并来源。B 保留一次规划计数，所以表中包含固定规划响应。A 的 `generate` 使用同一套关键词判定适配原有 Schema；B/C 的 `generate_multi` 使用多模式 Schema。Mock 规则明确依赖样例中的产品名和维度词。正常实验对每题每组重复 3 次，共 18 次运行。另对 RAG 各注入一次模型评估服务错误，再重开 Runtime、使用原任务 ID 恢复。

## 实测结果

| 指标 | A | B | C |
|---|---:|---:|---:|
| 关键证据覆盖 | 12/21（57.1%） | 15/21（71.4%） | 21/21（100%） |
| 候选 × 维度覆盖 | 27/54（50.0%） | 48/54（88.9%） | 54/54（100%） |
| 程序可校验引用 | 12/12 | 15/15 | 21/21 |
| 完成报告 | 6/6 | 6/6 | 6/6 |
| 总耗时中位数 | 73.30 ms | 103.56 ms | 131.55 ms |
| 平均模型调用尝试 | 4 | 5.5 | 7.5 |
| Token | 不适用 | 不适用 | 不适用 |

覆盖率统计实际进入合并证据的材料 ID 及其人工标注的「候选 × 维度」联合覆盖。引用有效率逐条匹配报告结构中的引用 ID 和原文子串。耗时包含工作流和 SQLite 持久化，排除初始化及资料导入。结果反映固定语料下的编排和取证，不推导通用研究正确率、生产时延或模型费用。

注入故障后，A 从失败的评估节点继续，调用次数从 2 增至 5。B 只重试 PgVector 曾失败的评估，调用数 4 → 7。C 同样只重试该评估，随后给 PgVector 补查运维，调用数 4 → 8，达到上限后发布部分报告。三组恢复均复用了已持久化的检索。C 的 PgVector 三次执行包括首次、一次恢复以及一次补查；Milvus 和 Elasticsearch 各执行一次。

复跑命令和逐次记录见下方。中文 BGE 的 Recall 和排名评测保留在[中文检索基准](../zh_retrieval_v1/README.md)。

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/evaluate_multi_agent.py --output data/multi-agent-eval.json
```

[已执行实验的原始结果](results.json)

## 2026-11-25 本地 Qwen 验收

保留上面的 Mock 原始结果与题目。真实 A/B/C 使用同一份 RAG 题、语料、模型、词面检索和总预算。B 的固定分派占一次预算额度，未请求模型，局部自主检索和全局补查均关闭。C 执行实际动态规划和定向补查。每组一次，另外执行一份多文档流程综合题和一份缺乏生产实测值的题。[附加题目](quality_cases.json)

```powershell
.\.venv\Scripts\python.exe scripts/start_local_ollama.py
.\.venv\Scripts\python.exe -X utf8 scripts/evaluate_multi_agent.py --local-quality-suite --output data/multi-agent-validation/quality-suite-reproduction.json
```

模型为固定本地 Ollama 0.40.6 的 Qwen3 4B Instruct，模型输出上限 768 Token，任务最多 8 次预算尝试、2 轮、300 秒。模型调用与 Token 来自本机请求和提供方用量记录。计时排除工作流初始化和资料导入。LangGraph 并行执行 Worker，本次 Ollama 配置一次推理，服务端可排队。

关键材料及维度覆盖统计进入最终合并集合的人工标注文档。RAG 维度以候选与维度组合计数。无实测值的用例没有答案金标，覆盖率和无引用用例的引用率均按无分母处理。人工复核逐条区分引用原文匹配和语义支持。即使原文真实，只要结论加入了原文不支持的判断，或句子与问题无关，也单独标出。

可比运行中 A、B、C 的关键材料分别是 2/4、3/4、3/4，C 的调用和耗时较高。最终代码以相同条件单独复查 C，找齐 4/4 材料并生成 7 条有效引用，报告仍有需人工核对的推论。详见[真实结果与逐条证据复核](REAL_QWEN_REVIEW_20261125.md)。
