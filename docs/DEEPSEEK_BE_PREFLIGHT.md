# DeepSeek B/E 收费前预检

2026-10-22。**真实DeepSeek B/E未验证，本轮未调用付费API。** 既有单次JSON规划与公开合成A真实HTTP闭环仍有效；本页新增的是本地合约与受控脚本，不替代模型质量验收。

## 保留的实现

- `scripts/deepseek_be.py`：默认无网络、无配置/凭据读取的dry-run；只允许固定数据集中的B/E。校验原始SHA256、question、来源title/ref/完整excerpt及quote_options，不能输入私有资料或空串冒充公开来源。
- 复用既有 `deepseek_http_a.RequestGate` 的预算/端点/参数/usage/超时门禁；只把A的公开载荷检查提取成方法供B/E复用，A的旧测试保持不变。限定官方HTTPS、`deepseek-flash`、非思考、temperature=0、JSON object、输出768、禁用tools和重试。持久化请求账本先于网络，错误或未知usage后禁止继续请求。
- 每题最多5次、3轮、300秒，单步60秒；B失败即停，不执行E；同run-id目录存在时拒绝重跑。每题独立BGE/PgVector collection与SQLite，不修改旧实验目录。新数据不自动清理。
- 真实loopback FastAPI执行后保存成功或失败task/report/trace，再关闭重开runtime/HTTP只读查询，校验持久化一致且不增加模型请求。引用/逐字摘录、必需来源、攻击资料实际取得与报告攻击标记检查保留；语义事实仍须人工复核。
- 使用前关闭外部tracing/telemetry与debug，清除代理继承，日志不保存header、key、原始异常。凭据仅在显式付费模式、日期/预算/公共数据校验之后从环境读取；本轮没有进入此路径。

## 本轮实际测试

新增 `tests/test_quality_deepseek_be.py` 共8项，**8通过**：

1. dry-run不读凭据、不构造HTTP请求；预算用Decimal核对。
2. 精确公共载荷/来源检查；拒绝空excerpt、私有来源、非官方端点；429一次记账后停止。
3. B多文档，真实本地BGE/PgVector补检索两轮、4次脚本化模型TCP，HTTP与SQLite重开一致。
4. E恶意资料确实取得，正常来源被引用；攻击文本不进system，报告不服从合成指令，3次脚本化TCP。
5. B第二步429，失败状态/证据持久化，2次请求不重试。
6. E脚本模型返回非法S999，保留失败与来源，禁止发布报告。
7. B跨补检索遇3次预算上限，禁止第4次HTTP请求，预算/失败状态重开不变。
8. B失败后suite不启动E。

这些真实TCP服务均在本机；传输先断言目标host再映射到本地脚本服务，**没有访问DeepSeek**。Mock结果只能证明请求、错误和状态合约。既有严格JSON、超时、无答案、未知引用、截断、身份、跨恢复预算、A真实本地HTTP与PgVector等回归一同运行：最终 `pytest tests -q` **90通过，0失败/跳过**，Ruff通过。

首次新增测试把整个`os.environ.get`替换为禁止函数，干扰pytest自身环境读取并异常结束；已修正测试隔离，只禁止凭据配置项读取，不变更固定场景/金标/原断言。保留首次XML及后续成功日志。最终验证不是通过删除失败用例得到。

```powershell
# 无凭据、无网络的审核入口，本轮已实际执行
python -m scripts.deepseek_be
python -m pytest tests/test_quality_deepseek_be.py -q
python -m pytest tests -q
python -m ruff check research_pilot tests tests_real scripts
```

本轮证据：`data/quality-20261022/deepseek-be-{first,second}.xml`、`deepseek-be-second.log`、`final-offline/{pytest.xml,run.log,run.json}`。临时目录内还保留Mock task/trace/请求账本与SQLite；pytest临时目录可能由其保留策略管理，长期依据为报告与汇总XML。固定公开数据与旧真实DeepSeek A证据均未改写。

## 单独收费授权边界

建议未来一次明确授权限定 **B+E固定公开合成数据、官方deepseek-flash、最多10请求、最多$0.04预算**；模型别名并非固定权重，需记录服务端response_model。脚本默认只输出计划，`--execute-paid`不在本轮授权范围，不应自动执行。

按2026-10-22[DeepSeek官方价格](https://api-docs.deepseek.com/quick_start/pricing/)的峰时cache-miss输入$0.30/百万、输出$1.20/百万，10×(8192×0.30+768×1.20)/百万=$0.033792。预算建议$0.04；应用字节/模板上界不是官方tokenizer或钱包硬限额。页面确认模型别名对应DeepSeek-V4.1-Flash-1017；价格、别名服务和时段可能变化，脚本日期失效时必须先重审，不能直接延长日期运行。

真正执行还要求显式公共数据确认、价格日期、预算参数、新run-id及环境凭据，不能把旧A的授权沿用到B/E。当前停在这里：**未发送收费请求；B/E真实结果、费用和语义支持性均未知**。以后即便两例通过，也不能推广为通用研究能力或提示注入防御率。
