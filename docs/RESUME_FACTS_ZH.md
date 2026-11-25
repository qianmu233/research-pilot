# ResearchPilot 简历事实依据

**项目名称** ResearchPilot：多智能体协作式企业调研与报告生成平台

**项目背景** 企业选型和内部调研通常涉及多份资料。用户需要比较候选方案、核对来源，并知道哪些结论仍缺证据。ResearchPilot 将这些步骤编排为可查询、可恢复的研究任务，生成带来源和原文摘录的报告。

**技术栈** Python 3.12、FastAPI、LangGraph、LangChain、Pydantic、SQLite。检索可选 SQLite 词面检索或中文 BGE 与 PostgreSQL/PgVector。真实本地验证使用 Ollama 与 Qwen3 4B。

## 可以描述的项目贡献

- 保留单 Agent 默认模式，增加 Supervisor 动态拆分、`Send` 并行派发及独立 Worker 子图。Worker 分开维护查询、轮次、来源和评估。
- 合并时优先保留 Worker 已引用的来源，按 locator 与原文去重。全局 Review 将补查派回相应子任务，保留已完成部分。
- 每次模型调用前在共享 SQLite 预算账本原子预占。用主图检查点与子任务游标支持手动恢复，原任务预算和时间限制继续生效。
- 使用结构化输出、来源 ID 和原文摘录校验，并区分已保存报告、部分报告和证据不足。引用失败会阻止报告发布。

## 可引用的数字和证据

| 证据类别 | 可引用成果 | 测试条件与证据 |
|---|---|---|
| 中文 BGE 检索评测 | Recall@5 **53.125% → 100%**，MRR@5 **51.04% → 96.875%**，多文档全金标覆盖 **0/4 → 4/4** | 英文 BGE 384 维对比中文 BGE 512 维无查询指令。固定合成集 19 篇资料、20 道题，Recall/MRR 基于 16 道有答案题。见[检索评测](../benchmarks/zh_retrieval_v1/README.md)和[中文模型对照](../benchmarks/zh_retrieval_v1/PHASE61_COMPARISON.md) |
| 多 Agent Mock 编排 | 关键材料覆盖 **12/21 → 21/21**，候选与维度覆盖 **27/54 → 54/54** | 2 道企业选型合成题，每题每组 3 次，共 18 次 A/B/C。采用同一 Mock、资料和 8 次预算。固定并行对照为 15/21、48/54。见[实验说明](../benchmarks/multi_agent_v1/README.md)及[原始记录](../benchmarks/multi_agent_v1/results.json) |
| 真实本地 Qwen | 最终 RAG 单次复查 **4/4 关键材料、12/12 维度、7/7 引用匹配**，8 次调用、9,769 Token | 固定 Qwen3 4B、SQLite 词面 Top-1、合成内部纪要。报告为部分完成，人工严查 1/7 条结论完整相关且获证。可比运行 A/B/C 分别找到 2/4、3/4、3/4。见[证据复核](../benchmarks/multi_agent_v1/REAL_QWEN_REVIEW_20261125.md)和[最终复查](../benchmarks/multi_agent_v1/real_qwen_rag_recheck_20261125.json) |
| 工程回归 | **124 项默认回归、7 项真实 Qwen 回归**，均通过 | 默认回归包括并发预算、TCP HTTP、独立进程故障注入与子任务恢复。7 项为独立本地 Qwen 套件。见[验收命令与范围](MULTI_AGENT_ACCEPTANCE_ZH.md)和[多 Agent 测试](../tests/test_multi_agent.py) |

## 精简版项目经历

- 开发企业多文档调研平台，将技术选型问题拆成独立研究任务并行检索，再按证据缺口定向补查。通过原子调用预算和子任务检查点支持故障后继续执行。
- 在 18 次固定样本 Mock 对照中，关键材料覆盖由 12/21 提升至 21/21。本地 Qwen 单次复查在 8 次调用内收集到全部 4 份关键材料，生成 7 条可追溯引用。

若岗位偏检索，可将第二条改为“接入中文 BGE 与 PgVector，固定合成集 Recall@5 从英文方案的 53.125% 提高至 100%，4 道多文档题均召回全部金标”。

## 表述边界

- Recall 衡量检索命中。Mock 实验衡量固定样本上的编排和覆盖，真实 Qwen 的结果来自小规模本地运行。三组数字各有独立口径。
- 引用通过表示来源和摘录匹配。结论是否完整获证需人工核对，线上大样本准确率和稳定性暂无数据。
- 恢复是单服务显式恢复，已落盘的步骤可复用。外部请求可能重放，当前服务面向本机演示，企业认证、租户隔离与分布式调度未纳入实现。
- 项目贡献是应用编排、中文检索适配、预算、恢复及证据校验。LangGraph、BGE 与 Qwen 是第三方框架或模型。

[项目流程与面试追问](MULTI_AGENT_FLOW_ZH.md) · [README](../README.md)
