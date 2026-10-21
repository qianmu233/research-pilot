# 本地工程预览 Git 基线与外部模型适配核验

日期：2026-10-21。工程MVP继续冻结，真实模型B/E失败保留。本次只建立本地Git基线和审阅适配代码，不改产品代码、Prompt、推理参数、测试断言、金标或依赖；不调用远端模型，不读取真实密钥，不下载模型。

## 本地 Git 基线

初始化前，docs/FREEZE_MANIFEST.json的67项全部逐字节匹配；原清单中的git_repository=false记录的是归档时点，保持历史原样，不据此声称新建Git不存在。原.gitignore本身也保持原哈希。

原.gitignore已覆盖当前运行文件实际所在的data/、.venv、env（仅.env.example例外）、缓存、日志、build/dist/egg-info。为避免未来把散落在其他目录的模型、数据库或私钥误加入，本地.git/info/exclude补充了权重扩展名、SQLite/DB/WAL/SHM、私钥文件名/扩展名、下载/模型缓存和根运行输出目录。补充规则是本地Git元数据，不在提交内；复制仓库时仍须遵守既有data/布局和源码允许清单。

只在ResearchPilot目录以main分支初始化，使用空模板，不创建远端。仅逐个加入审核允许清单；没有使用git add -A、git add .或强制添加忽略文件。固定benchmark中的公开历史排序/失败记录属于已审核的67项，保留；data下原始运行结果、模型权重、数据库及本地私钥不暂存。

提交前核对暂存路径、UTF-8内容、体积/类型、密钥模式、占位配置，以及每个Git blob与工作文件的字节一致性。没有把模式扫描当成完整密钥审计。初始提交命名为工程预览版本，使用明确的非个人占位作者ResearchPilot Engineering Preview（researchpilot@local.invalid），不更改全局Git身份；没有发布签名或生产版本保证。commit hash以git rev-parse HEAD为准，文件数和检查结果另存本机忽略目录data/local-baseline-20261021/，避免向提交内写入自引用hash或产生第二次提交。

最终允许清单为89个文件（包含本说明），约0.78MB。Git默认空白检查会把既有CRLF报为行尾空白；按CRLF解释后仅余受保护历史baseline-regressions.xml第20行一处真实行尾空白。原始格式警告保留在本地审计记录，没有为美化diff改写冻结源码、依赖锁或失败证据；这不是测试失败或密钥发现。

## 适配能力结论：部分支持

| 核对项 | 代码事实 | 验证边界 |
|---|---|---|
| 实际调用链 | config.Settings→runtime.ResearchRuntime工厂→LangChainOpenAIResearchModel或LocalStructuredModel→langchain_openai.ChatOpenAI→OpenAI SDK | 本地Ollama使用OpenAI-compatible聊天接口，不使用ChatOllama |
| 配置切换 | RESEARCH_MODEL_BACKEND、RESEARCH_OPENAI_BASE_URL、RESEARCH_OPENAI_MODEL、RESEARCH_OPENAI_API_KEY从环境读取 | openai模式要求model/key非空；base_url为空会采用SDK默认端点，远端测试必须显式指定 |
| Ollama约束 | 只允许本机/host.docker.internal的HTTP /v1端点；固定Qwen身份，经/api/tags检查摘要，使用无秘密占位key | 不能把ollama模式base_url直接改成DeepSeek；配置校验及本地身份预检会拒绝 |
| 远端openai模式 | 工厂构造普通LangChainOpenAIResearchModel，可以传入HTTPS兼容地址、模型名和用户环境密钥 | 仅旧版查询规划/自由文本报告路径，未运行真实远端验收；不是Phase7结构化深度研究能力等价切换 |
| 规划JSON | 旧版仅通过Prompt要求queries JSON，尝试json.loads；非法JSON/缺字段/无有效查询时退回原问题 | 没有强制response_format或Pydantic结构化计划，不能称严格JSON合约通过 |
| 报告格式/充分性 | 旧版输出自由Markdown，检查content是字符串；图按候选数量控制收集停止，保留unverified | 没有真实模型assess、StructuredReport或逐条quote校验；仍有S编号白名单检查，但不等于事实正确 |
| 超时/错误/重试 | 基类ChatOpenAI为timeout=20、max_retries=0、temperature=0；SDK异常由runtime分类保存安全错误码 | 超时为timed_out；429/认证/其他HTTP错误通常failed+异常类型，不保存异常原文；无专用Retry-After退避/限流恢复测试，不自动重试 |
| 执行预算差异 | 节点step_timeout及最多3轮仍适用于旧版；持久化模型调用计数和整任务deadline仅在structured路径生效 | 不能声称配置openai后继承5调用/300秒保护；旧版也未显式设置输出token上限或按模型Tokenizer预算输入 |
| 本地专用特性 | LocalStructuredModel使用Qwen Tokenizer、固定manifest、/api/tags、reasoning_effort=none、json_schema、Ollama所需extra_body.max_tokens | 远端提供商未必接受这些参数/JSON Schema特性；不能把该类直接当通用远端适配器 |
| 模型溯源 | ollama structured路径在research.model存模型名/manifest/GGUF等身份，另存推理参数/调用事件 | 未显式保存backend/base_url；旧openai任务不持久化模型身份，/health只显示当前配置，不能作为历史任务模型来源证明 |

依赖锁三份对应版本一致：langchain1.4.6、langchain-core1.6.12、langchain-openai1.7.2、openai3.35.1、httpx0.28.1、pydantic2.14.1、tenacity9.2.1。库中包含重试工具不等于应用启用重试；实际max_retries=0。

现有tests/test_phase7_contracts.py用真实SDK和模拟HTTP验证的是本地结构化请求的JSON Schema、无效JSON、timeout及max_tokens字段，不是DeepSeek/旧openai路径验收；tests_real只实际调用本地Qwen。没有看到远端429/Retry-After、远端结构化输出、远端任务模型身份的自动化覆盖。本次只读核对，没有以Mock成功推断远端已通过。

## 能否仅靠配置接入 DeepSeek？

**基础兼容聊天/旧版plan+draft：代码允许配置尝试，但尚未实测，属于部分支持。Phase7的结构化计划→模型充分性判断→报告/摘录校验/预算闭环：不能仅靠配置等价迁移。**

本轮只访问官方公开文档，无认证模型请求。2026-10-21官方示例给出的OpenAI格式base_url为https://api.deepseek.com，示例模型为deepseek-flash：[官方首次调用文档](https://api-docs.deepseek.com/)。模型别名和能力可能变化，正式授权测试时应重新核对账户可用型号，不宣称别名固定权重版本。

官方[JSON Output文档](https://api-docs.deepseek.com/guides/json_mode/)介绍response_format=json_object及提示要求，并说明可能有空输出；这不证明现有Ollama的json_schema/摘录枚举可原样复用。现有旧openai适配器没有发送JSON Output参数。没有调用接口确认供应商实际行为。

### 仅供未来授权测试的最小环境模板

不修改受保护的.env.example，也不创建真实.env。本段是模板，空密钥会使配置验证失败，必须由用户在未来测试进程的环境中安全提供；不要写入源码、提交、命令历史或打印它。

```dotenv
RESEARCH_MODEL_BACKEND=openai
RESEARCH_OPENAI_BASE_URL=https://api.deepseek.com
RESEARCH_OPENAI_MODEL=deepseek-flash
RESEARCH_OPENAI_API_KEY=
RESEARCH_SEARCH_BACKEND=none
RESEARCH_DATA_DIR=./data/remote-api-validation
LANGSMITH_TRACING=false
LANGCHAIN_TRACING_V2=false
```

Settings.from_env只读取进程环境，不自动加载.env文件。仅放置模板文件不会切换后端；未来应显式向启动进程注入已审核变量。默认检索是词面，不应因此宣称复用中文PgVector语义验收。若需向量演示，要显式选择对应PgVector/BGE配置和全新的只含公开合成资料的collection；不能把现有本地真实资料库直接用于远端试验。

## 最小兼容性检查与后续改动边界

未来优先补离线传输合约，确认旧openai/拟通用结构化适配器的实际URL、model/授权头不泄漏、角色/content类型、输出上限和超时进入HTTP；注入401/404/429/5xx、空content、非法/截断JSON与连接故障，验证状态/安全错误分类、无迟到发布、不意外重试。解析JSON成功不代表Pydantic Schema/引用/事实支持通过。

如要获得Phase7等价能力，最小预期改动范围是config.py（显式远端结构化profile/端点与能力约束）、model.py或local_llm.py（分离通用结构化逻辑与Ollama身份/Tokenizer/参数策略）、runtime.py（工厂选择）、workflow.py（通用模型身份及预算路径）和相关合约测试。已有Pydantic/预算/存储可复用，不需要新Agent框架；必要时在已有research JSON中记录安全的provider/model/端点来源，禁止记录key。实际改动应另行设计确认，本轮不修改这些文件。

只有未来获得明确费用/预算与外发资料授权后，才建议做一次小型真实远端测试：专用空数据目录和公开合成语料，先最小中文生成/JSON，再研究任务；记录实际响应模型名、用量、耗时、请求上限及安全错误，保持本地与远端结果分组。现有旧路径缺少完整调用/输出预算与来源溯源，优先补齐兼容性/成本控制，再决定是否执行，而不是直接用真实业务材料验证。

## 远端隐私边界

旧plan会发送问题和scope，draft会发送问题、scope、来源标题、locator及每份最多600字符摘录（合并后有字符上限）；裁剪不等于脱敏。切到远端会把这些内容传给配置的服务提供商，key作为认证头使用；不可信文档也可能包含敏感文本。当前没有自动PII脱敏、资料出境同意或远端主机允许清单，openai模式甚至未强制HTTPS。用户配置的错误端点可能接收问题/资料/密钥；不能只靠隐藏Settings.repr消除此风险。

Ollama模式的本地端点限制不会传递到openai模式。库级Tracing/代理或其他进程环境也需未来按授权单独核对；本轮未读取真实环境中的key或发送研究资料。关闭Tracing是必要配置选择，不是完整隐私保证。建议未来只用公开、可公开的合成资料，明确记录外发范围和费用，不能把“OpenAI-compatible”理解成与本地推理同等隐私。
