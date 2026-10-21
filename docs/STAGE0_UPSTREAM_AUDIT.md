# Stage 0：上游与当前环境核验（2026-10-20）

## 可由公开网页核实的事实

上游：https://github.com/langchain-ai/open_deep_research

- 仓库在 2026-08-21 已归档、只读（GitHub 仓库页面）。
- 根许可证为 MIT；保留版权和许可证声明后允许使用、修改和再分发。
- `pyproject.toml` 项目版本 0.0.16，声明 Python >=3.10，以及 `langgraph>=0.5.4` 等众多模型与搜索依赖；并未证明其直接符合本项目要求的 LangGraph 1.x 固定基线。
- `langgraph.json` 指向 `src/open_deep_research/deep_researcher.py:deep_researcher`，设置 Python 3.11；README 建议通过 `langgraph dev` 运行。
- 上游现有研究工作流、多提供商和 MCP 的代码结构可参考，但对仅需一个受控、面试可讲的 MVP 来说，整体迁移成本较高。

## 未核验/不能声称的事项

- **没有克隆上游仓库并执行其测试**。当前沙箱 `git ls-remote` 因 GitHub DNS 无法解析而失败，无法固定实际克隆到的 commit SHA。
- **无法核验上游完整运行行为或维护者近期修复质量**。归档意味着不能期望上游继续常规维护。
- 对依赖的安全漏洞未做漏洞数据库扫描。
- 未访问任何付费模型服务、搜索 API 或 LangSmith 托管平台。

## 当前代码环境

- 当前隔离环境仅有 Python 3.13.5（不同于目标 Python 3.11/3.12）。
- 未安装 LangGraph、LangChain、LangChain OpenAI；尝试查询包索引未成功，GitHub DNS 不通。
- 已有 FastAPI、Pydantic、httpx、pytest，可测试独立组件。
- 没有 Docker 可执行程序，不能完成容器真实启动验收。

## 决策

采用用户任务书允许的备选：**参考上游架构独立实现一个范围受控的 LangGraph 状态化研究工作流**，而不是把归档项目的复杂多提供商/并行研究员/MCP 框架整套迁过来。

原则：
- 不复制上游代码和评测结果；保留源码来源和 MIT 声明。
- 第一版从 API / 单个 Graph / 本地可核验资料 / 引用白名单开始。
- PgVector 和 MCP 是下一阶段加分项，须真实完成才可宣称。
- 只有在 Windows Codex 环境下完成 LangGraph 真实集成与 Docker 验收后才有资格标注为可演示第一版。

参考资料：
- https://github.com/langchain-ai/open_deep_research
- https://github.com/langchain-ai/open_deep_research/blob/main/LICENSE
- https://github.com/langchain-ai/open_deep_research/blob/main/pyproject.toml
- https://github.com/langchain-ai/open_deep_research/blob/main/langgraph.json
- https://reference.langchain.com/python/langgraph.checkpoint.sqlite/SqliteSaver

## 2026-10-20 Windows 接手后的环境补充

以上“当前代码环境”记录初版生成时的隔离容器历史，不代表本机现状。
本机 Python 3.12.3、真实 LangChain/LangGraph 1.x、SQLiteSaver 与免费本地
ONNX Embedding 已安装，Docker Desktop 引擎已启动，专用 PgVector 数据库已验收。
最新运行证据、测试数量和容器结果以根目录 TEST_REPORT.md 为准。
本轮没有重新克隆或重新审计上游，也没有修改上面的上游审计结论。
