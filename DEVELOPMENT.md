# ResearchPilot 开发与复现

> ?????2026-10-21?????????? [README](README.md)??????????????/???????????????/???/???????? Git ??????????? Git ??????? 78 ???? 4 ???????????

**工程冻结（2026-10-21）：工程 MVP 已完成；真实模型质量验收未完全通过；B/E 为保留的已知失败。** 后续命令是历史安装/验收入口，不是继续开发或重跑全量测试的指令。冻结后按[演示指南](docs/DEMO_GUIDE.md)选择只读回放/单场景复现，当前结果以[Phase7.1审核](docs/PHASE71_FINAL_REVIEW.md)为准。

验收日期：2026-10-20。只修改本独立工程，不修改 P1/P2/P3，不推送远端，不读取真实 `.env`。公开依赖和免费权重下载之外，验收没有调用付费模型、收费搜索或 LangSmith。

## 环境与锁定

**Phase7更新：** 当前回归/合约48通过（保留原39），另列真实模型6通过/1失败/0跳过；Ollama/Qwen与独立中文Docker部署已经实测。完整固定身份、命令、边界与E质量失败见 [Phase7记录](docs/PHASE7_LOCAL_LLM.md)。运行真实测试必须另外执行`pytest -q tests_real`，不能只报默认tests目录通过；E当前会使其退出码非零，不使用skip/xfail。后文较早阶段的数量与“未授权LLM”均为历史记录。

Windows Python 3.12.3（本机 `python` 来自 Anaconda），项目隔离虚拟环境 `.venv`。不需要修改全局 Conda 环境，也不依赖 `py`/`uv`。

- `requirements.lock`：基础应用及开发工具的实际安装版本。
- `requirements-vector.lock`：包含 vector extra 的完整实际安装版本；Windows 专用依赖带平台条件。
- `requirements-chinese.lock`：完整中英文测试环境，包含官方 CPU PyTorch、Transformers 与 safetensors。
- `pyproject.toml`：声明允许范围；复现应优先安装锁文件，再 `pip install --no-deps -e .`。
- Docker 使用同样锁文件，Python 与 PgVector 基础镜像固定摘要。构建工具的隔离环境由 pip 管理，应用依赖锁文件不是带哈希的供应链证明。

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-chinese.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e '.[dev,chinese]'
.\.venv\Scripts\python.exe scripts/download_embedding.py --cache-dir data/models
.\.venv\Scripts\python.exe scripts/download_embedding.py --model BAAI/bge-small-zh-v1.5 --cache-dir data/models
docker compose -p researchpilot-acceptance -f compose.yaml -f compose.vector.yaml up -d --wait postgres
$env:LANGSMITH_TRACING='false'
$env:LANGCHAIN_TRACING_V2='false'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check research_pilot tests scripts
```

完整测试直接连接测试库并加载真实模型，不用 skip、Mock 向量或词面检索代替。测试库默认只连接 `127.0.0.1:15432/researchpilot_demo`，可用 `RESEARCH_TEST_POSTGRES_DSN` 指向另一专用测试库，禁止指向真实业务库。测试使用独立 collection 并清理自己的行；事务失败测试会临时增加仅作用于该 collection 的约束。请串行运行此套数据库测试。

Phase 6 当前 suite 为 33 项；新增中文基准见 `benchmarks/zh_retrieval_v1/README.md`。模型加载要求 `embedding.lock.json` 指定的 revision 与五个文件哈希完全一致，缓存缺失须执行既有下载脚本，不能改为未校验的 main。评测脚本示例：

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_zh_retrieval.py --label rerun --output data/phase6/rerun.json
.\.venv\Scripts\python.exe -m pytest -q --junitxml=data/acceptance/phase6-pytest.xml
```

脚本拒绝覆盖输出，dataset.sha256 校验固定文档与标注。不要为消除低指标修改金标或阈值；程序测试成功不等于中文检索质量合格。本轮未重新构建/部署 Docker，既有容器仍是 Phase 5 镜像；新代码的模型锁打包已用实际 wheel 检查。

## 实际 HTTP

启动命令、两种检索模式的设置见 README。`scripts/smoke_graph.py` 使用 TestClient，只是进程内 ASGI；`tests/test_http_integration.py` 才是启动独立 Uvicorn 的 TCP 测试。`scripts/smoke_http.py --backend lexical|pgvector --output data/acceptance/result.json` 可验收一个已经运行的服务器。

## Compose

```powershell
docker compose -p researchpilot-acceptance -f compose.yaml -f compose.vector.yaml config --quiet
docker compose -p researchpilot-acceptance -f compose.yaml -f compose.vector.yaml build
docker compose -p researchpilot-acceptance -f compose.yaml -f compose.vector.yaml up -d --wait
.\.venv\Scripts\python.exe scripts/smoke_http.py --backend pgvector --output data/acceptance/docker-vector.json
docker compose -p researchpilot-acceptance -f compose.yaml -f compose.vector.yaml down
```

词面容器使用单独 `-p researchpilot-lexical -f compose.yaml`，顺序运行以避免端口冲突。模型缓存只读挂载到容器 `/app/models`；任务和 checkpoint 保存在本项目命名卷中。`.dockerignore` 排除真实 `.env`、虚拟环境、数据库与模型缓存，许可证和第三方声明复制进镜像。

首次构建遇到 Docker Hub token 网络超时；原错误见 `docs/DOCKER_FIRST_FAILURE.txt`。通过 Docker 引擎直接拉取同一官方 Python 镜像后固定摘要重试，无系统网络配置改动。最终结果以 TEST_REPORT 为准。

## 故障与恢复

运行时使用 `durability="sync"`、同一 `thread_id=task_id`、真实 SQLiteSaver。运行时从图输出更新可查询状态；异常后从 checkpoint 对账。完成后清除旧错误码。图仍有下一节点时可继续；图已到 END 时直接收口任务，避免重复写报告。

`tests/helpers/crash_worker.py` 只对 pytest 临时数据执行 `os._exit(73)`，生产入口没有环境变量故障开关。进程崩溃留下的 running 不会自动续跑，调用 `/resume` 才会继续。同步节点超时不能强杀底层调用；包装器拒绝超时后返回的状态更新，具体 I/O 仍有独立超时。

## 外部服务的明确 opt-in

默认 `mock` + `none`。ChatOpenAI 需要显式模型名和密钥；Tavily 需要显式后端和密钥。当前任务没有授权真实付费调用，未执行这两种外部服务测试。P3 MCP 仍未实现，不能以源码适配器或当前测试宣传已集成。

## Phase 6.1：完整环境与显式中文 profile

当前全套为 39 项，需要 `requirements-chinese.lock` 和两套固定缓存。上述 Phase 6 的 vector-only 安装只适用于原英文部署。安装中文依赖后，先分别执行：

```powershell
.\.venv\Scripts\python.exe scripts/download_embedding.py --model BAAI/bge-small-en-v1.5
.\.venv\Scripts\python.exe scripts/download_embedding.py --model BAAI/bge-small-zh-v1.5
```

新中文模型为官方 safetensors CPU 路径，固定六文件哈希，512D 写独立表；不复用旧384D列。`RESEARCH_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5` 显式选择，查询指令默认 false；有/无指令复测都保留。应用须重新导入目标集合，旧默认不静默变化。

`compose.yaml + compose.vector.yaml + compose.zh.yaml` 已通过 config 校验，未构建/启动新中文容器。当前运行的旧容器不代表新代码已部署。完整测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --junitxml=data/acceptance/phase61-pytest.xml
.\.venv\Scripts\python.exe -m ruff check research_pilot scripts tests
.\.venv\Scripts\python.exe -m pip check
```

39 passed in 22.80s，Ruff/pip check 通过。双模型清单已用实际 wheel 验证。pytest 的临时 collection 自动清理；带 --keep-index 的正式 benchmark collection 保留、拒绝覆盖非空集合。不得删除旧表或修改金标来追求指标。
