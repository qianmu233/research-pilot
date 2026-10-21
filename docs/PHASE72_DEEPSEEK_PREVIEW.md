# Phase 7.2：DeepSeek 兼容接入与付费验证准备

日期2026-10-21。**单次真实DeepSeek JSON规划冒烟已由用户执行成功；后续公开合成A也已完成真实HTTP闭环，详见[Phase7.3最终核验](PHASE73_DEEPSEEK_HTTP_A.md)。** 当前开发在feat/deepseek-provider，main仍固定为工程预览基线0304f7783700636f14b494a30745388069f20f3b。此次仅核对已有文件，不追加收费调用。原Qwen的B/E质量失败、7条事实中1条uncertain及所有历史原始记录保持，不将单条A或模拟服务的通过写成整体模型质量改善。

## 首次真实冒烟归档（只读核验，未重跑）

原始文件位于忽略目录 `data/phase72-paid-8421922ca7b2/`，不提交运行数据库、真实环境或日志。实际读取smoke.json及smoke-check.json确认：

| 项目 | 实际结果 |
|---|---|
| Provider / 请求模型 / 响应模型 | deepseek / deepseek-flash / deepseek-flash（别名，不是固定权重身份） |
| HTTP尝试 / 应用模型调用 | 1 / 1 |
| 退出码 / 错误码 / 状态 | 0 / null / completed |
| 输入 / 输出 / 总Token | 292 / 65 / 357；finish_reason=stop |
| 耗时 | 1.078秒 |
| 返回结构 | ResearchPlan的objective、questions、queries；同一适配器严格Pydantic校验成功 |

完整公开合成规划内容：

```json
{
  "objective": "核实公开合成笔记中演示组件保存单个线程图状态的方式。",
  "questions": ["公开合成笔记中，演示组件通过什么保存单个线程的图状态？"],
  "queries": ["演示组件 保存 单个线程 图状态", "合成笔记 线程 图状态 保存"]
}
```

按2026-10-21官方高峰、未命中缓存价格，已观测Token估算USD0.0001656；不是账户实扣账单，未读取账户/Key。仅证明一次真实JSON规划兼容，不证明assess/write、完整研究或B/E质量。

SHA256：smoke.json `b863a2b1c7e4d5266d1c304e128bfa066debabbbb6b12efef0d7517a36c75837`；smoke-check.json `d810f4a17124deb13142f9197bee522a0a719b3805053d4274323870b07835ce`；budget.json `1dcabe1c563095f4786b306bc2ccdb5291b2ad7a7f37a4976711eafb35cd27cf`。原件保持不变。

后续A改用[Phase7.3受控HTTP实验入口](PHASE73_DEEPSEEK_HTTP_A.md)：原脚本A直接调用Runtime，不能作为FastAPI端到端验收。以下离线结果和“尚未执行”说明保留为首次冒烟前的历史记录，不代表当前真实调用数仍为0。

## 实际改动与复用边界

| 文件 | 作用 |
|---|---|
| research_pilot/deepseek.py | 新显式DeepSeekStructuredModel，通过同一ChatOpenAI/OpenAI SDK请求；仅官方HTTPS地址和deepseek-flash；JSON对象输出、本地严格Pydantic、白名单错误/用量信息 |
| config.py、.env.example | deepseek后端与安全空密钥模板；限定最多5调用、300秒、768输出Token，不扩大原图轮数上限 |
| local_llm.py | 抽取provider预检、输入计数与请求三个小方法；共用原有三节点Prompt、Pydantic Schema、quote_options和报告校验，不修改问题/金标 |
| runtime.py | 工厂接线、创建任务即记录模型身份、恢复时拒绝Provider/模型/端点漂移、明确状态分类 |
| workflow.py | 沿用原5节点/SQLite预算，只补失败调用的安全用量入账；没有第二张图，没有自动重试 |
| tests/test_deepseek_contracts.py | 真实SDK→本机TCP模拟DeepSeek→真实LangGraph/SQLite的30项合约；不使用真实凭据/真实模型 |
| scripts/deepseek_preview.py | 默认dry-run，打印计划而不读取凭据/调用服务；将来获授权才可一次smoke，再单独执行公开合成A |

三份requirements锁、原48项测试文件、tests_real、本地模型锁、两套固定benchmark与评测标准不变。FREEZE_MANIFEST保留main冻结历史，不修改成新功能的验收证明；开发分支源码的授权变动不声称仍全部匹配旧冻结清单。

## 请求协议与状态

DeepSeek实际传输response_format={"type":"json_object"}、max_tokens、thinking.type=disabled，temperature=0、stream=false；不发送Ollama的json_schema或reasoning_effort参数，不调用/api/tags。官方[JSON输出](https://api-docs.deepseek.com/guides/json_mode/)说明json_object，不代表服务端验证本项目Pydantic Schema，Schema仍放在系统指令中、本地用strict=True验证。空内容、非法/残缺JSON、缺字段、类型不符、额外字段、截断、工具型或非正常结束均拒绝；不自动修JSON或切Mock。

Ollama仍走原json_schema、Qwen官方Tokenizer、身份预检和既有参数；3个节点都有本地TCP传输合约，原Phase7合约也保留。不在本轮重新运行真实Qwen质量任务，不能声称本次真实模型B/E变好。

DeepSeek没有下载Tokenizer：使用系统消息+用户JSON的UTF-8字节数作为保守应用输入上限，额外留128及输出额度；超限发送前拒绝，不截断资料。它不是精确DeepSeek Token计数，actual input/output/total来自提供商usage；没有返回usage时保持未知，不伪造为0。预览A配置8192输入预算、768输出上限；API名义1M上下文不作为本项目预算。

所有structured调用先在SQLite预留预算，再发网络请求，失败也计数，恢复不归零；SDK max_retries=0，当前无自动重试。手动恢复是新尝试，仍受原总5次和首次调用起300秒约束，轮数最多3。模型身份保存provider、请求model、官方base_url，事件另存响应model、用量、finish_reason、elapsed和completed/failed；远端别名不等于固定权重，不主张锁定DeepSeek内部版本。不同Provider/模型/端点恢复直接失败，不会把结果混算。

| 故障 | 安全错误码/状态 |
|---|---|
| 401 / 403 | MODEL_AUTHENTICATION_FAILED / MODEL_PERMISSION_DENIED，failed，无自动重试 |
| 429 / 5xx | MODEL_RATE_LIMITED / MODEL_SERVER_ERROR，failed；不擅自等待后再扣费重试 |
| 请求超时 / 连接失败 | MODEL_TIMEOUT（timed_out）/ MODEL_CONNECTION_ERROR（failed） |
| 空响应 / JSON字段错误 | MODEL_EMPTY_RESPONSE / MODEL_JSON_SCHEMA_INVALID，failed |
| finish_reason=length | MODEL_OUTPUT_TRUNCATED，failed；包括SDK提前抛LengthFinishReasonError的路径，保留可取得的用量 |
| 非预期HTTP / 响应 | MODEL_HTTP_ERROR / MODEL_RESPONSE_INVALID，failed |
| 恢复身份不符 / 缺少历史身份 | MODEL_IDENTITY_MISMATCH / MODEL_IDENTITY_MISSING，failed，不调用Provider |

任务与检查点仍对账，未知引用、伪造摘录、assessment不足却answered等原程序保护不变。evidence_status=unverified、citation_valid、facts_verified=false含义不变。失败报告不经report接口发布，内部trace/research仍保留诊断。没有认证失败自动降级或创建新任务无限重试。

不保存Key或Authorization，SDK异常原文/响应体不会进入安全错误码；HTTP客户端不继承环境代理、不跟随重定向。启用LangSmith/LangChain tracing时拒绝新远端模式；标准日志不输出请求头。模型响应/资料本身仍须按不可信输入处理，这不是通用脱敏保证。

## 离线验收与真实失败记录

本地TCP模拟服务与真实SDK验证：三个正常节点的JSON字段/参数确实进入HTTP；空/坏/缺字段/额外字段/类型/截断；401/403/429/500/503；真实延迟读超时和主动断连；无额外HTTP重试；状态/检查点/引用、3轮5调用、预算耗尽、跨恢复deadline与Provider身份保护；Ollama三个原请求合约；默认dry-run不读取设置/凭据。**30项DeepSeek新增合约全部通过，真实DeepSeek执行数0。**

首轮28项为26通过/2失败（phase72-contract-first.xml）：SDK在截断时提前抛异常造成分类丢失；Windows闭端口测试得到超时而非预期连接异常。前者补专门处理，后者改为本地模拟服务主动断连以固定故障，不放宽断言。修复后合并原9项合约为37通过（phase72-contract-fixed.xml）；新增严格类型/dry-run两项后为30通过（phase72-contract-final.xml）。

第一次全回归为64通过/5失败/7错误，Docker未运行导致12项原PgVector测试连不上，原始XML保留（phase72-regression-first.xml）。只启动现有Docker Desktop和ResearchPilot专用postgres后，数据库测试通过；下一次全套77通过/1失败（phase72-regression-final.xml），原恢复测试Uvicorn随机端口绑定出现Windows Errno13，原代码单独复测1通过（phase72-recovery-port-recheck.xml）。当前端口排除列表不能解释当时49298的失败，不宣称已定位或修复系统原因；不改测试、网络/权限配置、不删除失败证据。

最终完整套件**78通过、0失败、0跳过，38.01秒**（phase72-regression-release.xml），保留全部原48项；Ruff、pip check通过。没有重跑真实Qwen/DeepSeek质量用例。历史回归/合约不等于真实模型质量。数据库通过真实PgVector，新增模型服务则为模拟响应，必须分开描述。

## 尚未执行的付费实验（按顺序逐次审批）

只允许用户在ResearchPilot独立进程安全注入环境变量；不复制P2 .env或其他项目凭据，不读取真实.env，不打印密钥。所需名称：RESEARCH_MODEL_BACKEND=deepseek、RESEARCH_OPENAI_BASE_URL=https://api.deepseek.com、RESEARCH_OPENAI_MODEL=deepseek-flash、RESEARCH_OPENAI_API_KEY（仅运行时提供）、RESEARCH_SEARCH_BACKEND=none、LANGSMITH_TRACING=false、LANGCHAIN_TRACING_V2=false。Settings不自动读取.env；模板见根.env.example。

### 1. 现在可执行的无费用预览

```powershell
Set-Location E:\codeplace\llm-agent\research-pilot
.\.venv\Scripts\python.exe scripts/deepseek_preview.py
```

该默认路径不会调用Settings.from_env或模型，已实际运行并由测试验证；不会创建真实凭据文件。

### 2. 首次真实验证：仅一次规划JSON冒烟

**本轮不得执行。** 未来需用户先批准最多1请求、费用预算USD0.002及公开合成问题外发，才可在已安全注入环境的独立终端执行：

```powershell
.\.venv\Scripts\python.exe scripts/deepseek_preview.py --mode smoke --execute-paid
```

这不是简单文本生成：经同一适配器请求ResearchPlan JSON并校验；input allowance4096、输出128、最多1次、30秒、无重试。只发送固定公开合成问题，无企业/历史私密材料。结果保存data/phase72-paid-<唯一值>/smoke.json及SQLite调用记账。空/坏/截断或认证/限流失败立即停，不能自动重跑；报告实际响应model、usage、耗时/状态后再讨论A。CLI开关只是防误触，不替代用户的费用授权。

### 3. 冒烟通过后，单独批准一条A

需先审核成功smoke.json、实际用量和费用，另批准最多5请求、USD0.02及同一公开合成材料外发后才执行：

```powershell
.\.venv\Scripts\python.exe scripts/deepseek_preview.py --mode A --execute-paid --smoke-result data/phase72-paid-<唯一值>/smoke.json
```

尖括号路径是替换占位符。脚本检查本项目data中的成功smoke，A只能创建一次新目录；固定公开合成“演示组件通过检查点保存线程图状态”笔记，不描述真实企业。它是Phase7.2的单文档链路任务，不替换原Phase7 A金标或宣称官方事实。专用项目PgVector15432、新随机collection、中文BGE512D、Top-K1；现有模型缓存/数据库需先就绪，不自动下载。3轮/5调用/300秒、输出768；全程原图/引用校验/SQLite保存，失败停止不补跑。

### 预算估算与未来A/B/E（不运行）

2026-10-21[官方价格](https://api-docs.deepseek.com/quick_start/pricing/)：deepseek-flash高峰、缓存未命中输入USD0.30/百万Token，输出USD1.20/百万Token；按更贵档估算，不计缓存或非高峰优惠。官方当前将该别名指向DeepSeek-V4.1-Flash-1017；仍须在付费前重查价格/账户可用模型，实际响应标识另记。

| 计划 | 最大HTTP请求 | Token预算（输入/输出） | 按预算估算金额 | 待批准测试预算 |
|---|---:|---|---:|---:|
| 仅smoke | 1 | 4096 / 128 | USD0.0013824 | USD0.002 |
| 仅A | 5 | 每次8192 / 768，共40960 / 3840 | USD0.016896 | USD0.02 |
| smoke+A | 6 | 两项相加 | USD0.0182784 | USD0.03（总预留，仍分步批准） |
| 未来B或E，各一条 | 各5 | 各40960 / 3840 | 各USD0.016896 | 各需另行批准，不包含在本轮 |
| 未来A/B/E各一条（含前置smoke） | 16 | 126976 / 11648 | USD0.0520704 | USD0.06，未授权 |

这些是基于应用输入上限、输出参数和价格快照的保守估算，**不是钱包硬上限或账单保证**：没有官方Tokenizer本地精确计数，也无法代替供应商参数/计费实际执行。程序硬限制请求预留数、输入字节/输出设置和时限；若供应商用量异常、usage缺失或价格变化，停止，不继续下一步。失败请求也可能计费，已预留次数不返还；无API余额查询或自动充值。B/E比较暂不执行，不能为了拿到更好结果循环扣费重试。

当前代码/离线验证具备准备条件，真实兼容性、实耗费用和模型研究质量均未验证。首次付费调用前停止，等待用户明确批准**仅smoke**的次数、费用和公开资料外发；本轮不请求或使用实际Key，不推送GitHub，不改P1/P2/P3或调优RAG。
