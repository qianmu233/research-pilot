# 本地真实 LLM 固定小型验收集 v1

五个中文研究任务 A–E，另有真实服务/上下文与超时测试 F；不是统计代表性准确率基准。数据 SHA256 在 dataset.sha256，所有复测保持问题、材料、预期来源与行为不变。Phase6/6.1 的19文档20题及其金标完全未改。

P01/P02/P03 是根据各自链接的官方公开文档整理的中文事实摘要，**不是官方逐字原文或企业内部材料**；X01 是合成干扰，X02 是合成恶意文本。正文和来源类型均有明确标记。不得把合成资料当外部事实证据。

任务：A单文档事务原子性/ROLLBACK；B事务与LangGraph双文档；C保存点/线程配置、首轮不足需补检索；D本地不存在的真实生产QPS；E攻击文档参与排序但不能成为指令或事实依据。A–D每查询Top-K=1，E为2，以便检查攻击文档实际进入上下文。阈值0.5、中文BGE512D、256/32分片和来源规则保持不变；这是Phase7研究任务配置，不是修改Phase6的Top-5基准。

```powershell
$env:LANGSMITH_TRACING='false'
$env:LANGCHAIN_TRACING_V2='false'
$env:RESEARCH_REAL_RUN_LABEL='new-unique-run-label'
.\.venv\Scripts\python.exe -m pytest -q tests_real --junitxml=data/acceptance/new-real-run.xml
```

需要真实本地Ollama/Qwen、固定Tokenizer、官方中文Embedding和15432专用PostgreSQL。测试不skip、不替换模型、不使用Mock向量、不访问付费端点。每个任务启动独立Uvicorn TCP服务与独立collection，保留SQLite/checkpoint/逐题排序来源、调用次数、token、耗时、原始报告和失败。禁止覆盖已有run label。

`tests/` 是另行统计的回归/合约套件；其中规划报告采用Mock/脚本化模型，Embedding/PgVector集成仍真实。`tests_real/` 才访问真实Qwen。自动断言只检查协议、来源/摘录、覆盖和预期行为；事实核查单列在 docs/PHASE7_LOCAL_LLM.md，不能把程序检查当作事实正确证明。

已知 E 仍过度拒答，保留为失败，不改 expected_answer_status 为拒答、不标记xfail、不降低断言。完整结果、历史失败与固定模型身份见根 TEST_REPORT.md。
