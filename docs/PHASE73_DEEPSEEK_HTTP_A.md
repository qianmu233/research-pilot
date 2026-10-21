# Phase 7.3：公开合成A的真实HTTP验收与最终核验

2026-10-21，feat/deepseek-provider；main仍为0304f7783700636f14b494a30745388069f20f3b。**用户已执行公开合成A，完整HTTP闭环成功；本次仅只读核验已有证据，没有新增收费请求。** 原Qwen B/E失败及48项历史测试不变；DeepSeek B/E未测试。

## 最终实际结果（覆盖下方准备期的未完成状态，不删除历史失败）

用户恢复Docker后，版本只读确认29.8.1 / linux，ResearchPilot专用postgres healthy。原phase73-local-recheck.xml实际为4 passed、0 failed、0 skipped、10.730秒；包含本机模拟DeepSeek成功/401路径及真实BGE/PgVector/HTTP重开，不是4个真实模型质量任务。原首次2失败的XML和Docker启动失败说明保留。

真实任务 `9e6e89bd429e4151906408b8d2160a6d`，证据目录 `data/phase72-paid-8421922ca7b2/A-http/`；status=completed、error_code=null、无tool_errors、answer_status=answered。创建到完成3.177295秒；HTTP3/5、检索1/3轮，总时限300秒。固定上下文8192、最大输出768、temperature=0；实际协议由既有适配器使用json_object、thinking.disabled、无工具、无自动重试。

实际轨迹：`plan → retrieve:1:1 → assess:model_sufficient → write → validate:OK`。三次HTTP均200、finish_reason=stop、应用节点均completed。逐次Token与SQLite调用账及trace模型事件完全一致，唯一对应如下：

| HTTP / 节点 | 输入Token | 输出Token | 总Token | 请求/响应模型 | 节点耗时秒 |
|---|---:|---:|---:|---|---:|
| 1 / plan | 296 | 63 | 359 | deepseek-flash / deepseek-flash | 1.125 |
| 2 / assess | 550 | 68 | 618 | deepseek-flash / deepseek-flash | 1.204 |
| 3 / write | 716 | 137 | 853 | deepseek-flash / deepseek-flash | 0.812 |
| 合计 | **1562** | **268** | **1830** | Provider=deepseek；别名，不是固定权重身份 | 3.141 |

实际规划目标为“依据公开合成演示笔记，核实演示组件保存单个线程图状态的方式。”，questions包含保存方式问题，queries为“演示组件 保存 单个线程 图状态”和“合成演示笔记 线程 图状态 保存”；原图按既有规则仅执行第一条。assess认为笔记明确说明检查点保存状态和相同线程标识读取此前状态，sufficient=true、source_ids=[S1]、missing_information/next_queries均空；无补检索或额外条件。

### 来源及逐条事实核查

来源标题“公开合成演示笔记（不是企业资料）”，本地标识 `synthetic:phase72-public-A`，没有外部网页真实性主张。导入ID `731f8ce2b5c04de7bb4d1a64e5591f6e`，唯一分片 `731f8ce2b5c04de7bb4d1a64e5591f6e-0`，locator=`pgvector:731f8ce2b5c04de7bb4d1a64e5591f6e-0`，工作流来源编号S1。工作流检索cosine分数0.7969270702513597；与导入ID、预检命中分片和PUBLIC_DOCUMENT完整正文一致，没有截断或来源错配。

| 报告原始结论 | 引用及原文摘录 | ID存在 / 来源映射 / 内容支持 | 结论 |
|---|---|---|---|
| 演示组件通过检查点保存单个线程的图状态。 | [S1]；“演示组件通过检查点保存单个线程的图状态。” | 三项分别核对，原文直接逐字支持，无扩大范围 | supported |
| 使用相同的线程标识可以读取该线程此前保存的状态。 | [S1]；“使用相同的线程标识可以读取该线程此前保存的状态。” | 三项分别核对，原文直接逐字支持，无扩大范围 | supported |

这是助手对既有公开合成来源的有限语义复核：本次技术claims为**2 supported、0 unsupported、0 uncertain**，没有过度拒答或材料外结论。两项limitations准确说明合成/非生产属性、缺少性能商业数据及未经独立核实；不据此认证任何真实系统性能或外部事实。报告保留`evidence_status=unverified`、`citation_valid=true`、`facts_verified=false`，不修改原始summary中pending_manual_review或原报告；审核结论另存本文。历史Qwen七条事实6 supported/1 uncertain独立保留，不合并成新准确率。

### 持久化、重启、费用和安全核对

报告API的markdown/sources/research与A.json相同，trace API的事件/research/model_events与任务相同。两份SQLite使用mode=ro直接查询：任务行、预算calls=3、事件及最终Checkpoint一致；该线程共7个检查点，最终report_status=completed、iteration=1。restart.json记录Runtime、SQLite和本机HTTP重开后task/report/trace相同，HTTP前后均3，没有恢复或新增调用。此为同进程服务/Runtime重开，不冒充DeepSeek进程崩溃或跨进程恢复实测。

按本实验2026-10-21价格快照的高峰未缓存价，(1562×0.30+268×1.20)/1,000,000 = **USD0.0007902**，低于USD0.02；实际账单未知，可能有缓存/非高峰差异，未查询账户。前置smoke另357 Token、估算USD0.0001656；两次实验合计4请求/2187 Token、估算USD0.0009558，不把前置请求算成A的第四个节点。

对原11个结果文件（含SQLite二进制）作不回显匹配值的凭据模式扫描，没有发现真实Key、Authorization Bearer值、私钥或非空Key字段；JSON和SQLite内容为固定合成材料、模型输出与安全元数据，无P1/P2/P3材料。目录没有日志或真实环境文件；代码默认关闭日志/Tracing。此为有限模式/内容检查，不声称通用DLP保证，也未读取当前进程真实Key。SQLite只读WAL连接生成了零字节WAL及SHM辅助文件，保留且继续被data/忽略；原数据库与原结果文件未改写，不清理用户运行数据。

关键原件SHA256（本次核验不修改原件）：

| 文件 | SHA256 |
|---|---|
| A.json | e6c5f4d46815776c52a4f39296701c8edd9a6f417abf6b356ce08fa0886959ca |
| http-attempts.json | 48f445cff629e742f1218d20264c8fcd289b735a095d86a5fe8e80745f698b5c |
| report-api.json | 2807bf1c556d48769c6a7ca4ec46937da1bcef1d0a105aa5baaafaaea3004a33 |
| trace.json | 825638f14a9d3c33af476c1e1fbe2212be70167fca0f95667269a23bd4eb6566 |
| restart.json | cace5c1b8202b4b84df10cb0f72149aaedd6610b3d018fffd019244481d515af |
| tasks.sqlite3 | 7453b5be0dfd36a5cca7da0207fb79ef31db6cb04ad22606320554db6013f463 |
| checkpoints.sqlite3 | 20e600d388d6171050bd0ad149845e5d6b2ef97fdb2bbb427dc8e97eb58918f5 |

本轮只更新文档并准备分支本地提交，不追加模型调用、A/B/E评测或新功能。Qwen完整链路已验证但B/E失败保留；DeepSeek仅一次JSON规划和一条公开合成A闭环通过，B/E没有证据，不声称生产级可靠性或绝对准确。

### 本地提交准备

审查feat/deepseek-provider相对基线的16项文件：6份说明文档、空密钥.env.example、5份Provider/运行时代码、2份实验脚本、2份离线测试；仅按明确路径暂存。扫描发现的Bearer/API Key赋值仅为已明确标记的合成测试字符串，未发现可疑真实凭据。运行data/、SQLite/WAL/SHM、真实.env、模型权重、缓存和日志不进入暂存区；原48项测试、tests_real、依赖锁、冻结清单与benchmark不改。main提交不变，不合并或推送。

本次仅准备、审核暂存区，**不创建提交**；建议提交标题：`feat: add bounded DeepSeek provider and verify synthetic HTTP A`。提交说明应保留“Qwen B/E失败、DeepSeek B/E未测试、单条A来源支持核查通过”的边界，不将准备暂存称为已经提交。

以下为准备期记录：其中阻塞、未授权和未来执行命令仅描述当时状态；本次已执行结果在上方，不要再次执行收费命令。

## 执行入口及边界

原scripts/deepseek_preview.py的A仅调用Runtime，没有FastAPI和重启查询。保留原文件，新入口scripts/deepseek_http_a.py仅作为实验工具，复用原create_app、ResearchRuntime、五节点LangGraph、DeepSeekStructuredModel、中文BGE/PgVector与SQLite；不修改产品代码、Prompt、参数默认值或历史断言/金标。

固定材料直接导入原PUBLIC_DOCUMENT，问题直接复用PUBLIC_QUESTION。来源为synthetic:phase72-public-A，明确属于公开合成演示材料，不代表外部真实技术文档。只导入该材料；专用本机15432演示数据库与新collection phase73-8421922ca7b2，不读取其他collection、本地知识库、P1/P2/P3或真实.env。BGE锁定现有官方中文512维模型，缓存加载/文件校验，无下载；无查询指令，Top-K1、cosine、最低分0.5、256/32 token切片沿用。

顺序：配置/成功smoke/Git/价格日期 → 新建唯一A-http目录 → 加载现有BGE/连接PgVector → 本机TCP Uvicorn启动 → HTTP健康/导入 → 真实BGE/PgVector预检 → **HTTP提交一次任务，首次收费请求从此处才可能发生** → 原图plan/retrieve/assess/(有限补检索)/write/validate → HTTP状态/报告/轨迹查询 → 关闭并重新打开Runtime、两份SQLite和HTTP服务器 → 仅GET查询一致性。

这是同一进程中Runtime和HTTP服务重启，不冒充操作系统进程崩溃恢复。历史独立进程崩溃验收仍是旧测试。新实验不调用/resume，失败不补跑。已有A-http目录即拒绝重新执行，不删除旧结果以解锁重试。

## 请求与费用保护

- 同步ChatOpenAI.invoke → OpenAI SDK → 显式httpx.Client → RequestGate → HTTPTransport(retries=0)。SDK max_retries=0；不跟随重定向，不继承代理；异步客户端可能被SDK构造但不调用。Uvicorn在同进程线程运行；仅Git检查使用只读子进程，无子进程云端网络调用。
- RequestGate对每次HTTP尝试在I/O前写入http-attempts.json，失败也不返还名额；最多5次。只允许官方HTTPS的POST /chat/completions、deepseek-flash、json_object、thinking=disabled、temperature=0、max_tokens=768；不允许tools/functions/stream。
- 两条消息：原系统Prompt和公开问题/来源载荷。核对固定问题、source_ref及摘录属于原公开正文。输入UTF-8字节加256余量及768输出不得超过8192；这是应用保守界限，不是官方Tokenizer实测。
- 原图最多3轮、5次模型调用、300秒；HTTP门禁另设300秒截止。模型超时/认证/限流/非法JSON/引用失败按原规则收口，不自动换模型或Mock。HTTP错误、缺少usage或用量异常后门禁拒绝后续请求。
- 2026-10-21[官方价格](https://api-docs.deepseek.com/quick_start/pricing/)：高峰未缓存输入USD0.30/百万、输出USD1.20/百万；5×(8192×0.30+768×1.20)/1,000,000 = **USD0.016896 < USD0.02**。不计缓存/非高峰优惠。预期充分证据走3请求，最坏预留5；不是钱包硬限额或账单保证。失败缺usage时费用未知，不能记0。
- 日期变化即收费前停止，需重查官方价格并重新审核；不联网查询余额/模型或自动充值。DeepSeek响应model仍是别名，不声称固定权重。
- 关闭LangSmith、LangChain、OTEL、DD/WANDB及HF telemetry；禁用Python日志，不保存请求头、Key、环境快照或原始SDK异常。只将公开材料/生成内容及安全用量写入忽略的data目录。用户独立终端注入自己的Key，代理/企业中间件的外部审计不在此程序保证范围内。

## 准备期历史：离线结果与环境阻塞（后已恢复，失败原件保留）

无网络dry-run及请求次数/输入保护测试通过。首次完整测试4项中2通过、2失败：真实BGE已加载，两个完整HTTP/图/向量测试在PgVector连接初始化以ConnectionTimeout停止，模型尝试均0；phase73-preview-first.xml保存原始失败。Ruff第一次为新测试fixture导入顺序/重名报错，已调整导入写法，不放宽测试。

docker info和compose ps/up显示dockerDesktopLinuxEngine管道不存在；只有Desktop前端进程。标准start返回already running但引擎仍无；一次标准restart --timeout 45失败，前端进程未退出。停止继续改环境，没有删除容器/卷/运行数据，没有重跑全量评测。**需要用户恢复Docker Desktop Linux引擎，再通过未改断言的4项离线测试，才能视为具备收费实验条件。**

其他已完成验证：原DeepSeek30项+原Phase7合约9项+新增无网络2项，**41通过、2项数据库用例未选，18.12秒**（phase73-offline-contracts.xml）；这不覆盖之前保留的2项失败，不能写成全套通过。最终门禁单测2通过、2未选，0.93秒（phase73-guard-final.xml），另覆盖失败尝试计数及缺usage后停止。Ruff全通过、pip check通过。独立本机TCP健康检查实际200；三节点通过RequestGate与本地MockTransport的输入/输出协议预检，输入字节+余量+输出分别2872/3367/3982，小于8192，云端请求0。以上均不替代未通过的真实PgVector端到端预检。原48项、30项历史合约与tests_real文件未改，没有本轮全48重测结论。

以下仅无费用预览与离线验证，可先执行：

```powershell
Set-Location E:\codeplace\llm-agent\research-pilot
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m scripts.deepseek_http_a
docker info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker Linux引擎不可用；停止，不调用DeepSeek。' }
docker compose -p researchpilot-acceptance -f compose.yaml -f compose.vector.yaml up -d --wait postgres
if ($LASTEXITCODE -ne 0) { throw '项目PgVector不可用；停止。' }
.\.venv\Scripts\python.exe -m pytest tests/test_phase73_preview.py -q --junitxml=data/acceptance/phase73-local-recheck.xml
if ($LASTEXITCODE -ne 0) { throw '离线验收未通过；停止，不调用DeepSeek。' }
```

这些测试只使用合成测试凭据和本机TCP模拟DeepSeek，无云端调用；BGE和数据库是真实的。不得把模拟模型通过算作真实研究通过。

## 历史收费执行命令（已执行一次，保留复盘；当前禁止重复执行）

已有独立终端四个模型变量。脚本先检查存在性，支持把终端原openai值在子Python进程内切换为显式deepseek，其他模型/地址不匹配即停止。真实Key从环境读取，不回显。不复制或设置Key到文件。

只有离线4项全部通过并明确批准“仅本条公开合成A，最多5次请求、USD0.02”后，才手动执行：

```powershell
Set-Location E:\codeplace\llm-agent\research-pilot
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m scripts.deepseek_http_a --execute-paid --smoke-result data/phase72-paid-8421922ca7b2/smoke.json
if ($LASTEXITCODE -ne 0) { throw '实验停止；保留结果，不重试、不提高预算、不运行B/E。' }
```

CLI开关不是聊天中的费用授权。本轮不运行此命令。默认不加开关只输出预算，无设置/凭据读取或网络。

## 预定义交付与验收标准

所有证据存于原smoke目录的新A-http/，不提交这些运行文件：

| 文件 | 检查内容 |
|---|---|
| budget.json / http-attempts.json | 预留上限、真实HTTP次数（含失败）、状态码、逐次usage、耗时、停止原因；不含头或请求正文 |
| import.json / retrieval-preflight.json | 实际导入document_id、分片数；真实PgVector命中、完整摘录、来源标识 |
| A.json | plan、sources的S1/document_id/chunk_id/locator、每轮检索、assessments、结构化report、模型身份、逐节点用量与状态 |
| trace.json / report-api.json | API返回原轨迹、引用校验、报告；失败时报告接口应409，不发布失败报告 |
| restart.json | Runtime/SQLite/HTTP重开后任务、报告、轨迹完全相同，请求数没有增加 |
| tasks.sqlite3 / checkpoints.sqlite3 | 持久化任务、模型预算及原图状态 |
| summary.json | 成败、检查项、错误分类/阶段、总用量与价格快照估算；usage不全则金额null，事实审核待人工 |

成功必须：任务completed、answer_status=answered、citation_valid=true、正确公开来源与导入ID匹配、轮数1–3、HTTP次数与SQLite调用数一致且≤5、无工具错误、重启一致且0新增模型请求。引用存在/出处正确/结论受支持分开检查；原程序继续evidence_status=unverified、facts_verified=false。

人工逐条核对最终claims是否仅陈述笔记中的“通过检查点保存单个线程的图状态”“相同线程标识读取此前状态”。对超出材料的性能/生产能力/实现原理结论标unsupported或uncertain，记录是否过度拒答；程序不自动将摘录匹配算成事实核验成功。任何失败均保留，不反复挑选成功结果，不改变B/E历史金标。
