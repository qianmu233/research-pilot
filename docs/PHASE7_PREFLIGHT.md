# Phase 7 接入准备；模型下载待确认

2026-10-20。本阶段未完成，不能据此声称真实 LLM、事实质量或 Docker/Qwen 闭环通过。

## 实际环境检查

**历史记录说明：本页为下载确认前的准备状态。随后用户已明确确认；实际安装、真实模型/HTTP/Docker验收和保留失败见[Phase7结果](PHASE7_LOCAL_LLM.md)。不再等待同一次下载确认。**

- 未找到 Ollama 命令、进程或默认模型目录；尚未安装/启动 Ollama。
- CPU：Ryzen 9 8945HX，16核/32线程。
- RTX 5060 Laptop：8151 MiB 总显存、5604 MiB 空闲、2296 MiB 使用，驱动617.14；这是检查时快照。
- 系统内存约31.3 GiB，总可用约15.15 GiB。
- C/D/E 空闲约38.4/77.9/21.5 GiB。
- Docker Desktop/独立测试 PostgreSQL 沿用既有环境；本轮未更改监听或部署镜像。容器到宿主机 Ollama 连接还未实测。

选定候选仅一个：`qwen3:4b-instruct-2507-q4_K_M`。[Ollama 官方模型页](https://ollama.com/library/qwen3:4b-instruct-2507-q4_K_M)标注4.02B、Q4_K_M、约2.5GB、Apache-2.0、短摘要`0edcdef34593`。未下载，因此完整本地摘要、许可证文件与推理身份尚未核验，不能将标签当作固定权重证明。

[Qwen 官方配置](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/cdbee75f17c01a7cc42f958dc650907174af0554/config.json)为36层、8个KV头、head_dim128；FP16 KV缓存理论上4K约576MiB、8K约1.125GiB，尚不包括权重、计算缓冲和驱动开销。先按4K、单请求预计约4–5GiB显存、至少6–8GiB可用系统内存规划，实际以加载测量为准。安装/下载临时文件及模型共预留约6–8GB磁盘；不下载其他聊天模型。

[官方 Ollama v0.40.6](https://github.com/ollama/ollama/releases/tag/v0.40.6) Windows standalone ZIP约1.37GB，发行摘要`e359637575302f288d76c0007c408a4be9c7376d59c4f28684d63b232a44b427`，尚未下载或本地校验。GitHub API查询曾受公共IP限流，改用官方发行页核对，没有使用凭据。

用户要求下载前一次确认，已提交确认问题；收到明确答复前不下载聊天权重。未来服务仅绑定127.0.0.1，禁用云端、单并行请求；容器侧须先验证`host.docker.internal`能否访问，不擅自改为局域网或公网监听。

## 已准备的实现

- `config.py`：显式ollama模式、本地URL限制、上下文/输出/调用数/总时限配置。
- `schema.py`：结构化计划、判断、逐条来源与摘录的报告，以及API研究字段。
- `local_llm.py`：复用ChatOpenAI的JSON Schema路径、严格解析、输入预算、来源/摘录校验、程序渲染报告。
- `workflow.py`：复用原图；首轮使用计划第一条查询，不足时模型提出最多两条补充查询，最多三轮。保存计划、历轮判断与检索，保持来源合法与事实真实的区分。
- `store.py/runtime.py/api.py`：研究状态持久化、跨恢复调用预算与安全调用事件、HTTP字段、SDK超时分类。
- `.env.example`：只增加注释示例，没有读取或修改真实配置。
- `tests/test_phase7_contracts.py`：8项离线协议测试，不是Ollama/真实模型验收。

原39项回归先通过（23.91秒）。新增传输合约首次6通过/2失败，发现结构化Runnable的invoke参数未进入SDK请求。改为在with_structured_output绑定timeout/max_tokens，检查HTTP请求读取超时及输出token上限后8通过（1.44秒）。最终完整回归47 passed（21.33秒），0 failed、0 skipped。保留：

- `data/acceptance/phase7-baseline.xml`
- `data/acceptance/phase7-contracts-wire-first.xml`（失败记录，不覆盖）
- `data/acceptance/phase7-contracts-wire-fixed.xml`
- `data/acceptance/phase7-preflight-full.xml`

合约覆盖语义不足后补检索、候选非空仍拒答、计划/checkpoint一致、调用失败恢复仍计数、持久deadline、非法来源/摘录/回答状态、输入预算/端点，以及真实SDK解析模拟非法JSON/超时。它们使用脚本化模型或模拟HTTP传输；原有真实Embedding/PgVector测试仍实际运行。

最终Ruff检查`research_pilot tests scripts`通过，`pip check`通过；没有新增依赖或改锁文件。

## 确认后的必要验收，尚未执行

1. 下载并核验官方Ollama包与这一个模型，记录完整digest、许可证、量化、服务参数和实际资源。
2. 实测中文生成、JSON、无效模型、超时、4K输入预算/截断。当前字节上界包含schema/模板/输出预留，可能过于保守；需真实tokenizer或服务数据校准，不能放任静默截断。没有自动压缩证据。
3. 固定公开来源材料并逐条核查；执行单来源、跨文档、补检索、无答案、注入、故障六类任务。合成攻击和故障材料须明确标注。
4. 完成至少一个真实TCP FastAPI→LangGraph→Qwen→中文PgVector→报告→校验→持久化，单列真实模型测试与报告质量核查。
5. 实测容器访问和Docker/HTTP；若只能扩大无认证监听，先报告阻塞，不自行暴露服务。

目前不满足第一版封板条件。没有真实LLM结果、模型质量结论或Phase7容器验收；未调用收费服务，未修改P1/P2/P3，未推送远端。
