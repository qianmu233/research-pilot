# Phase 7 只读环境调查与待确认建议

日期：2026-10-20。本轮只读查询安装位置、注册表、进程、模型目录、默认服务端口与硬件；没有安装 Ollama、没有下载/启动聊天模型、没有发送聊天请求，也没有读取或展示 API Key。

## 实际发现

| 检查项 | 结果 |
|---|---|
| Ollama 命令 | PATH 中未找到 |
| 常见安装路径与卸载注册表 | 未发现 Ollama |
| Ollama 进程 | 未发现 |
| `127.0.0.1:11434/api/tags` | GET 被拒绝连接，未发现该默认端口的可用服务 |
| 默认 `.ollama/models` | 不存在 |
| 默认 Hugging Face / LM Studio 缓存目录 | 未发现可用聊天模型；不穷举所有磁盘/自定义端口，不能排除其他位置的便携安装 |
| CPU | AMD Ryzen 9 8945HX，16 核 / 32 线程 |
| 主机内存 | 约 31.3GiB，总量接近标称 32GB；最终采样可用约 10.6GiB |
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU，8151MiB，总显存约 8GB；最终采样空闲 5536MiB，约 5.4GiB；驱动 617.14 |
| 剩余磁盘 | C 约 38.3GiB，D 约 78.0GiB，E 约 21.5GiB |

原始硬件采样：`data/acceptance/phase61-environment.json`。空闲内存/显存是瞬时值，不能当作已为模型保留的容量。本轮 Embedding 使用 CPU，不验证 Ollama 的 GPU 驱动/后端兼容性。

## 本地模型建议（尚未下载）

优先用非 thinking 的小型中文指令模型跑规划 JSON 与短报告闭环：**`qwen2.5:3b-instruct-q4_K_M`**，先用 4K context、单并发、报告输出最多约 512 tokens。

| 候选 | 官方 Ollama 权重 | 建议容量预算，均为估计 | 当前判断 |
|---|---|---|---|
| Qwen2.5 3B Instruct Q4_K_M | 约 1.9GB，标签摘要 `357c53fb659c` | 空闲 VRAM 3–4GiB；主机可用 RAM 至少约 6GiB，含 Embedding/服务余量；磁盘预留约 6GB | 当前空闲显存和 RAM 容量适合先试，实际 GPU 支持/延迟待测 |
| Qwen2.5 7B Instruct Q4_K_M | 约 4.7GB，标签摘要 `845dbda0ea48` | 空闲 VRAM 6–7GiB；主机可用 RAM 建议 10–12GiB；磁盘预留约 10GB | 当前约 5.4GiB 空闲显存偏紧，需先释放显存或接受 CPU offload；不作为首次默认 |

这些预算不是实测峰值。依据权重大小，加上 KV cache、运行时/算子缓冲和 Embedding/数据库余量估计。按官方 config 的 FP16 KV、4K context、单序列粗算，3B KV 约 144MiB、7B 约 224MiB；实际 Ollama 会受并发、context、KV 类型和 GPU offload 策略影响。模型总 context 上限不意味着应在这台机器上直接使用最大窗口。

来源：[3B 模型与大小](https://ollama.com/library/qwen2.5:3b-instruct-q4_K_M)、[7B 模型与大小](https://ollama.com/library/qwen2.5:7b-instruct-q4_K_M)、[3B config](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/raw/main/config.json)、[7B config](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/raw/main/config.json)。两款页面声明中文与 JSON 能力，但 ResearchPilot 尚未实测。3B 标注 Qwen Research License，7B 为 Apache-2.0；如后续用途超出研究演示，应在确认模型时一并核对许可范围。

## 现有适配器能否连接

源码 `LangChainOpenAIResearchModel` 已通过 `ChatOpenAI(base_url=..., model=...)` 调用 chat messages，协议形态可以接 Ollama 的 `/v1/chat/completions`，没有必要更换 Agent 框架。现有客户端要求非空鉴权配置；本地 Ollama 忽略占位鉴权值，未来配置不需要真实 API Key。本轮没有设置任何模型鉴权值或调用该接口。

[Ollama 官方兼容说明](https://docs.ollama.com/api/openai-compatibility) 列出 messages、temperature、max_tokens、response_format 与 JSON mode 支持；[结构化输出说明](https://docs.ollama.com/capabilities/structured-outputs) 描述本地 JSON Schema 约束。现有 plan 只是提示返回 JSON 并解析，尚未启用服务端 schema；Phase 7 可最小增加规划 schema 和确定性校验，不把偶然输出合法 JSON 当可靠结构化能力。

报告节点只需要受来源约束的中文文本输出，协议上可用。但必须真实检查引用对应、事实支持、无答案拒答、上下文预算与超时；不能把模型能聊天等同于研究报告合格。当前请求 timeout=20s、图 step_timeout=30s，且未设置输出 token 上限，可能不适合首次加载本地模型。建议确认 Phase 7 后，为规划/短报告分别设置 token 预算并按实际延迟调整超时；本轮未改聊天模型超时参数。

## 本机与 Docker 地址

| ResearchPilot 所在位置 | 待配置的 base_url |
|---|---|
| Windows 本机，Ollama 也在 Windows | `http://127.0.0.1:11434/v1` |
| Docker Desktop 容器，Ollama 在 Windows | `http://host.docker.internal:11434/v1` |
| 将来同一 Compose 网络内的独立 Ollama 服务 | `http://ollama:11434/v1`（仅方案，本轮没有创建该服务） |

[官方 FAQ](https://docs.ollama.com/faq) 说明默认仅监听 127.0.0.1。容器到宿主机必须另外验证监听/防火墙路径；只改 base_url 不保证连通。若需要调整 OLLAMA_HOST，应在 Phase 7 确认监听范围并限制到本地/容器访问，不直接把服务暴露到外网。本轮没有修改系统监听、代理、防火墙或用户环境变量。

## 等待用户确认的方案

建议先确认是否采用 3B 研究演示候选，以及本机 Ollama 部署方式；之后才安装/拉取/启动并固定实际模型 digest。用现有图与中文索引执行规划 schema、报告引用/事实支持、近主题无答案三类真实验收，继续保留 `evidence_status=unverified`，直到有实际语义验证。

本轮调查不能证明本机已经具备可运行的聊天模型环境，也不代表实际性能验收。**到此停止，不自动执行 Phase 7 安装或模型调用。**
