# ResearchPilot: Evidence-Grounded Research Agent

**ResearchPilot：多文档自主调研与报告生成 Agent**

基于 Python、FastAPI 和 LangGraph
构建的多文档研究智能体。系统将研究问题拆解为有边界的多步骤任务，通过结构化研究规划、资料检索、证据评估、报告生成和引用校验，输出附有来源信息、便于追溯的研究报告。

## 项目介绍

研究型任务通常需要围绕一个问题进行多轮资料检索与整理。ResearchPilot 使用
LangGraph 编排研究流程，通过 FastAPI
提供任务提交、状态查询、报告获取、执行轨迹查看和手动恢复接口。

系统将研究过程拆分为五个节点：`plan`、`retrieve`、`assess`、`write` 和
`validate`。当现有资料不足时，工作流可以根据评估结果补充检索；达到检索轮数、模型调用预算或任务时限后，流程按配置结束。

项目重点包括：

- 使用结构化模型输出生成研究计划、评估检索证据并组织报告。
- 通过有界条件循环执行补充检索，控制检索轮数和来源数量。
- 支持 SQLite 词面检索，以及 PostgreSQL + PgVector 语义检索。
- 为检索来源分配稳定标识，核对报告中的来源 ID 和原文摘录。
- 持久化任务状态、模型调用记录、调用预算和 LangGraph 检查点。
- 通过统一模型适配层接入 Mock、Ollama/Qwen 和 DeepSeek。

## 技术栈

| 技术                         | 用途                                     |
|:-----------------------------|:-----------------------------------------|
| Python 3.12                  | 主要开发语言                             |
| FastAPI                      | 任务提交、状态查询、报告、轨迹与恢复接口 |
| LangGraph                    | 五节点研究工作流、State 管理与条件路由   |
| LangChain、Pydantic          | 模型交互与结构化数据校验                 |
| SQLite                       | 任务记录、模型调用记录、预算及图检查点   |
| PostgreSQL、PgVector         | 可选的向量检索后端                       |
| BGE、FastEmbed、ONNX Runtime | 英文 Embedding 与语义检索                |
| PyTorch、Transformers        | 中文 Embedding 模型加载与推理            |
| Ollama、Qwen、DeepSeek       | 本地与云端模型适配                       |

依赖版本及可选安装方式见 `pyproject.toml` 和对应的依赖锁文件。

## 架构与研究流程

``` mermaid
flowchart TD
    subgraph INGEST["资料导入与索引"]
        DOC["文本资料"] --> CHUNK["解析与文本切片"]
        CHUNK --> LEX[("SQLite 词面语料")]
        CHUNK --> EMB["BGE Embedding"]
        EMB --> PG[("PostgreSQL / PgVector")]
    end

    USER["POST /api/tasks"] --> API["FastAPI 创建任务"]
    API --> TASKDB[("SQLite：任务、调用记录与预算")]
    API --> BG["FastAPI BackgroundTasks"]

    BG --> PLAN["plan：生成结构化研究计划"]
    PLAN --> RET["retrieve：执行资料检索"]
    RET --> SEARCH{"选择检索后端"}
    SEARCH --> LEX
    SEARCH --> PG
    LEX --> SOURCES["整理候选资料与来源信息"]
    PG --> SOURCES

    SOURCES --> ASSESS{"assess：评估现有证据"}
    ASSESS -->|"需要补查且未达到轮数上限"| RET
    ASSESS -->|"结束检索"| WRITE["write：生成结构化报告"]
    WRITE --> VALIDATE["validate：检查报告结构与引用"]
    VALIDATE --> DONE["保存报告、状态与执行轨迹"]
    DONE --> TASKDB

    PLAN -.-> TASKDB
    ASSESS -.-> TASKDB
    WRITE -.-> TASKDB

    BG -.-> CHECKPOINT[("SQLite：LangGraph Checkpointer")]
    RESUME["POST /api/tasks/{id}/resume"] --> RUNTIME["Runtime 恢复执行"]
    CHECKPOINT -.-> RUNTIME
    RUNTIME --> BG

    QUERY["GET 状态 / 报告 / 轨迹"] --> TASKDB
    TASKDB --> RESULT["返回任务信息与研究结果"]
```

研究流程由五个节点组成：

1.  `plan`：根据研究问题生成结构化研究计划和待执行查询。
2.  `retrieve`：执行当前待执行查询，获取候选资料并整理来源信息。
3.  `assess`：评估当前资料是否足以支持研究；需要补充资料时生成补查查询，并通过条件边返回
    `retrieve`。
4.  `write`：根据研究状态和检索证据生成结构化报告。
5.  `validate`：检查报告结构、来源 ID 和引用摘录，校验通过后保存报告。

首轮检索执行研究计划中的第一条查询；后续补查由评估节点根据当前证据生成，单次最多增加两条补查查询。检索轮数、单轮来源数量和图递归深度均受到配置约束。

### 状态与持久化关系

- `task_id` 与 LangGraph `thread_id`
  使用同一任务标识，便于将任务记录与图执行状态关联。
- 任务 SQLite 保存任务状态、模型调用记录和调用预算。
- LangGraph Checkpointer 使用独立 SQLite 文件保存图状态与执行检查点。
- Plan、Assess 和 Write
  等模型调用共享任务预算；失败尝试同样计入预算，恢复任务不会重置已消耗额度。
- `/resume`
  根据原任务标识读取检查点并继续执行，任务状态与检查点通过运行时对账协调。

## 核心实现

### 1. LangGraph 状态管理与有限检索循环

`research_pilot/workflow.py` 使用 `StateGraph`
组织研究节点、状态传递和条件边。

各节点围绕结构化 State 协作，主要字段包括：

- `task_id`、`question`、`scope`：任务标识、研究问题与范围。
- `queries`、`iteration`：待执行查询与检索轮次。
- `sources`、`tool_errors`：累计来源和检索工具错误。
- `report`、`report_status`：报告内容与生成状态。
- `trace`、`evidence_status`、`research`：执行轨迹、证据状态和结构化研究信息。

首轮按计划执行第一条查询；评估节点判断是否需要补查，并在允许的范围内生成补充查询。流程通过最大检索轮数、来源数量限制和
LangGraph `recursion_limit` 控制执行范围。

### 2. 资料检索与向量模型管理

`research_pilot/retrieval.py` 负责检索流程，`research_pilot/vector.py`
负责 Embedding 模型和 PgVector 操作。

项目提供两类检索后端：

- **词面检索**：基于 SQLite
  本地语料执行中文字符片段和英文词项检索，不生成神经网络向量。
- **语义检索**：使用 Embedding 模型生成向量，通过 PostgreSQL + PgVector
  执行余弦距离检索。

当前支持的向量模型配置：

| 模型                     | 推理方式                 | 向量维度 |
|:-------------------------|:-------------------------|:--------:|
| `BAAI/bge-small-en-v1.5` | FastEmbed / ONNX Runtime |   384    |
| `BAAI/bge-small-zh-v1.5` | PyTorch / Transformers   |   512    |

向量集合按模型身份和维度隔离。切换 Embedding
模型后，需要使用匹配的模型配置和向量集合重新导入资料。检索结果保留文档、分片、来源定位、查询和检索时间等元数据，供报告引用与执行轨迹使用。

### 3. 来源标识与引用摘录校验

`research_pilot/evidence.py`
负责来源标识、引用和摘录检查，`research_pilot/schema.py`
定义研究计划、资料评估和报告的数据结构。

- 检索来源使用稳定的 `S1`、`S2` 等标识。
- 来源去重依据 locator 和 excerpt。
- 报告中的 `source_id` 必须属于本轮允许的检索来源集合。
- 报告引用摘录会与对应检索记录中的原文进行匹配检查。
- 结构化报告需要满足预定义 Schema。

系统将引用
ID/摘录校验与人工事实核查分开记录。引用校验用于确认报告引用对应实际检索材料；人工事实核查状态独立保存，不会因为引用格式通过就自动标记为事实已核实。

### 4. 任务持久化、调用预算与手动恢复

`research_pilot/runtime.py`
负责任务执行与运行时控制，`research_pilot/store.py`
管理任务状态、调用记录和相关持久化数据。

任务通过 `task_id` 与 LangGraph 的 `thread_id`
关联。任务记录、模型调用记录和预算保存在任务 SQLite 中；LangGraph
Checkpointer 使用独立 SQLite 文件保存图状态。

运行时对模型调用次数、任务总时限、节点执行时间和输出长度设置上限。失败尝试同样占用模型调用预算，恢复任务继续使用原任务的预算记录。

系统提供手动 `POST /api/tasks/{id}/resume` 接口。恢复时，Runtime
读取原任务的图检查点，并对任务记录、来源和执行轨迹进行状态对账。进程重启后，未完成任务通过该接口显式恢复。

### 5. 本地与云端模型适配

项目通过统一模型适配入口支持不同运行方式：

| 模式          | 作用                                                     |
|:--------------|:---------------------------------------------------------|
| Mock          | 离线演示任务流转、接口行为和状态管理                     |
| Ollama / Qwen | 使用本地模型完成结构化计划、检索评估和报告生成           |
| DeepSeek      | 调用云端模型接口，需要配置 API Key，并按实际调用产生费用 |

`research_pilot/local_llm.py` 和 `research_pilot/deepseek.py`
负责相应模型调用与错误处理，`research_pilot/model.py` 提供模型适配入口。

模型输出经过结构化解析与 Pydantic 校验。对于非法
JSON、格式不符、截断、认证失败、限流或超时等情况，系统将其转换为受控错误，并记录相应任务状态和调用信息。

## HTTP API

| 接口                          | 功能                 |
|:------------------------------|:---------------------|
| `GET /health`                 | 检查应用进程状态     |
| `POST /api/documents/text`    | 导入文本资料         |
| `POST /api/tasks`             | 提交研究任务         |
| `GET /api/tasks/{id}`         | 查询任务状态         |
| `GET /api/tasks/{id}/report`  | 获取已完成的研究报告 |
| `GET /api/tasks/{id}/trace`   | 查看节点轨迹         |
| `POST /api/tasks/{id}/resume` | 手动恢复任务         |

新任务提交后返回任务
ID，客户端可以轮询任务状态。报告完成并通过校验后，可通过 `/report`
获取；执行过程可通过 `/trace` 查看。

## 本地运行

### 环境要求

- Python 3.12
- 可选：Docker 与 Docker Compose
- 可选：PostgreSQL + PgVector
- 可选：本地 Ollama 模型或云端模型 API Key

### 1. 创建 Python 环境

在仓库根目录执行：

``` powershell
python -m venv .venv

.\.venv\Scripts\python.exe -m pip install -r requirements.lock

.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

### 2. 启动离线演示

``` powershell
$env:RESEARCH_MODEL_BACKEND = "mock"
$env:RESEARCH_SEARCH_BACKEND = "none"
$env:RESEARCH_RETRIEVAL_BACKEND = "lexical"

.\.venv\Scripts\python.exe -m uvicorn research_pilot.api:app --host 127.0.0.1 --port 8010
```

打开 `http://127.0.0.1:8010/docs` 查看接口。

也可以在 Docker 环境中运行：

``` bash
docker compose up --build
```

默认 Compose 演示使用 Mock
模型和词面检索，服务绑定本机回环地址，不需要云端模型密钥。

### 3. 导入资料并提交任务

以下 PowerShell 示例使用公开的合成资料：

``` powershell
$base = "http://127.0.0.1:8010"

$doc = @{
    title = "演示资料"
    content = "演示组件使用检查点保存研究线程状态。"
    source_ref = "synthetic:readme-demo"
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "$base/api/documents/text" `
    -ContentType "application/json; charset=utf-8" `
    -Body ([Text.Encoding]::UTF8.GetBytes($doc))

$request = @{
    question = "演示组件怎样保存研究线程状态？"
} | ConvertTo-Json

$task = Invoke-RestMethod `
    -Method Post `
    -Uri "$base/api/tasks" `
    -ContentType "application/json; charset=utf-8" `
    -Body ([Text.Encoding]::UTF8.GetBytes($request))

Invoke-RestMethod "$base/api/tasks/$($task.task_id)"
```

任务完成后，可以通过以下接口获取报告和执行轨迹：

``` powershell
Invoke-RestMethod "$base/api/tasks/$($task.task_id)/report"
Invoke-RestMethod "$base/api/tasks/$($task.task_id)/trace"
```

### 4. 启用中文向量检索

中文向量检索需要准备 `requirements-chinese.lock`、中文 Embedding 模型和
PgVector 环境，并按照 [演示指南](docs/DEMO_GUIDE.md)
配置数据库连接与独立集合。

修改模型或检索配置后，需要重新导入相应资料。默认词面检索模式使用 SQLite
本地语料，不会自动切换为中文向量检索。

### 5. 配置真实模型

使用 Ollama 时，需要先准备本地模型并设置对应的模型地址；使用 DeepSeek
时，需要显式启用相应 Provider，并通过进程环境注入 API Key。

不要将真实 API Key 写入代码、提交到 `.env.example`
或放入公开测试数据中。真实模型调用与默认离线演示分别执行。

## 测试与验证

项目测试覆盖研究工作流、结构化输出、来源校验、向量检索、HTTP
接口、任务持久化、预算控制、超时与恢复等部分。

### 1. 自动化回归

截至 2026-10-22，测试报告记录的完整离线回归结果为：

| 测试范围                |              结果               |
|:------------------------|:-------------------------------:|
| 完整离线回归            | 100 passed，0 failed，0 skipped |
| 日期与时区专项          |     7 passed，3 deselected      |
| Ruff 静态检查           |              通过               |
| PowerShell 静态语法检查 |              通过               |

离线回归覆盖业务逻辑、脚本化 HTTP 合约、真实本地 BGE/PgVector 和 SQLite
相关测试；该结果不包含新的真实模型质量样本。

### 2. 中文语义检索评测

基于固定检索基准比较英文 BGE 与官方中文 BGE。评测集包含 19 篇文档、20
道问题，其中 16 道有答案、4 道无答案，另有 4 道需要多文档证据。

| 评价指标         | 英文 BGE（384D） | 中文 BGE（512D，无查询指令） |
|:-----------------|:----------------:|:----------------------------:|
| Recall@5         |     53.125%      |             100%             |
| MRR@5            |      51.04%      |           96.875%            |
| 多文档完整覆盖@5 |       0/4        |             4/4              |
| 无答案问题零候选 |       0/4        |             1/4              |

中文模型在该固定测试集上提升了相关文档召回和多文档覆盖效果。4
道无答案问题中，中文模型仍有 3
道返回候选资料，因此检索指标用于衡量候选资料召回，不等同于最终回答准确率或正确拒答率。

### 3. 真实模型与任务闭环验证

使用本地 Qwen3 4B 和云端
DeepSeek，在固定公开合成场景中验证研究流程、检索补查、报告生成、引用校验和任务持久化。

| 模型与场景           | 验证结果                                                  |
|:---------------------|:----------------------------------------------------------|
| Qwen3 4B：A、C、D、F | 流程验证通过                                              |
| Qwen3 4B：B、E       | 出现过度拒答，作为已知失败保留                            |
| DeepSeek：A          | 单文档真实 HTTP、BGE/PgVector、引用与 SQLite 查询闭环通过 |
| DeepSeek：B          | 两轮检索，4 次 HTTP 200；三条结论由正常来源支持           |
| DeepSeek：E          | 一轮检索，3 次 HTTP 200；三条结论由正常来源支持           |

DeepSeek B/E 共完成 7 次请求，累计 6,028
Token。两项任务均完成报告生成与校验，任务记录、SQLite 预算、LangGraph
Checkpointer 和 API
查询结果保持一致；重新查询没有增加模型请求次数。DeepSeek C、D、F
尚未单独进行真实模型验收。

当前记录将来源 ID/摘录校验与人工事实核查分开保存：真实验收报告中的
`facts_verified=false` 和 `fact_review=pending_manual_review`
状态保持不变。

## 许可证与第三方来源

本项目采用 MIT License。工作流设计参考 [LangChain Open Deep
Research](https://github.com/langchain-ai/open_deep_research)，并保留相应的第三方来源说明。

项目使用的模型权重、运行时、向量检索组件和 Python
依赖均有各自的许可要求。模型权重需按项目文档单独下载，不属于本仓库源码的一部分。

- [架构说明](ARCHITECTURE.md)
- [开发说明](DEVELOPMENT.md)
- [演示指南](docs/DEMO_GUIDE.md)
- [测试报告](TEST_REPORT.md)
- [第三方来源与许可](THIRD_PARTY_NOTICES.md)
