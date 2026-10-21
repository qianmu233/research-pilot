# ResearchPilot 下一步与验收入口

**工程冻结交接（2026-10-21）：工程 MVP 已完成；真实模型质量验收未完全通过；B/E 为保留的已知失败。** 当前不再执行后面的历史“下一步”、模型优化或全量评测。没有新任务授权就保持冻结，不把“质量未全过”解释成可自行继续开发。归档、已知失败与简历事实见[ENGINEERING_ARCHIVE](ENGINEERING_ARCHIVE.md)，固定演示见[DEMO_GUIDE](DEMO_GUIDE.md)。下文Phase7的6/1已被Phase7.1原配置4/2（B/E）及重复记录更新，历史证据不删除。

更新于 2026-10-20。原接力优先事项中的真实 LangGraph、HTTP、PgVector 与 SQLite 恢复已经执行，具体成功数和 Docker 状态以根目录 TEST_REPORT.md 为准；不再把旧初版“8 项通过”作为完整结论。

## 当前复现

**最新停止点：Phase7真实本地模型闭环与验收已执行，等待最终审核；不能封板。** 原39项保留，48项回归/合约通过，真实模型另列6通过/1失败。Qwen3 4B Q4_K_M已经下载并GPU运行，仅回环监听；E过度拒答保留为质量失败。见根TEST_REPORT与docs/PHASE7_LOCAL_LLM.md。下文Phase6/6.1的等待Phase7说明是历史，不能再次索取已经给出的模型下载授权，也不能自动下载其他模型或开启下一阶段。

1. 用 Python 3.12 创建本项目 `.venv`。
2. 按 `requirements-vector.lock` 安装，再 `pip install --no-deps -e '.[dev,vector]'`。
3. 执行 `scripts/download_embedding.py` 下载免费本地模型。
4. 用 `compose.yaml + compose.vector.yaml` 启动专用 PostgreSQL，完整执行 pytest，不跳过 vector 测试。
5. 按 DEVELOPMENT.md 分别启动词面/向量容器，以 `scripts/smoke_http.py` 验收真实 TCP。
6. 报告验收范围，区分 Mock 报告生成与真实 Embedding，保留许可证和来源。

## 后续尚未授权/尚未完成

- 中文或多语种语义检索与带人工标准答案的质量评测；当前只验收英文 BGE 小模型。
- ChatOpenAI 与 Tavily 真实外部服务验收：需要明确授权，不能自动产生费用。
- P3 MCP：未实现；若后续需要，只读核实 transport、认证及 tools schema，不得修改 P3 或绕过权限。
- 生产认证、持久任务队列、自动崩溃恢复、多实例协调、性能与事实质量评估。
- 更换向量模型前应设计模型版本/权重指纹和重建索引策略，不能混用同一 collection。

## 保持约束

只修改 `research-pilot`，不碰 P1/P2/P3，不读取真实 `.env`，不推送远端，不删除或弱化测试。遇到真实凭据风险或不能可靠修复的环境阻塞，停止并报告。当前目录没有 `.git`，没有虚构 commit 或创建远端。

## Phase 6 已完成；等待 Phase 7 确认

当前完整测试 33 passed，0 failed，0 skipped。19 文档 / 20 中文题的冻结评测已经执行，数据、金标、原始基线及最终结果在 benchmarks/zh_retrieval_v1/。Recall@3/5=0.53125，MRR@5=0.51041667，无答案零候选0/4；质量不足的失败保留。

已固定并校验既有英文 BGE 的 ONNX snapshot/tokenizer，修复来源元数据与片段完整性；没有更换模型或调整阈值，不再将中文小型基准列为“尚未执行”。前文未完成列表中的中文质量基准是 Phase 6 之前的记录。

停止继续开发真实 LLM。Phase 7 需要先确认模型身份、本地兼容端点与质量验收方案；若使用任何收费服务，必须得到明确授权。方案建议见 docs/PHASE6_CHINESE_RETRIEVAL.md，当前不得据此自动启动下一阶段。

## Phase 6.1 完成；Phase 7 仍待确认

官方中文Embedding、独立512D索引、无/有查询指令对照已执行。当前39 passed，0 failed，0 skipped；原有金标SHA256不变。主要指标与中间失败见 docs/PHASE61_CHINESE_EMBEDDING.md。

只读Ollama/硬件调查见 docs/PHASE7_ENVIRONMENT_SURVEY.md。没有安装或启动聊天模型，未调用真实LLM。下一步须用户确认本地聊天模型及部署/资源方案，才可执行Phase7；不得根据建议自动下载模型或改系统监听。
