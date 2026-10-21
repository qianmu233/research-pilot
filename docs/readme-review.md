# README 正式版修订依据

审查日期：2026-10-21。修改前基线 `f807062`。本清单在 README 修改前建立。

| 原句或小节 | 问题类别 | 可核查依据 | 修改方案 |
|---|---|---|---|
| “Phase7.2/7.3开发分支验收”“分支尚未提交、未合并或推送” | 状态失效、开发日记 | 当前 main 和功能分支均已在 `f807062`；远端 main 同步 | README 描述当前实现；提交状态由 Git 与本轮汇总报告记录 |
| “main冻结历史状态”“待封板” | 阶段性用语 | `TEST_REPORT.md` 与质量报告保留失败 | 项目介绍与历史归档分开，突出实际边界 |
| `E:\anaconda3\python.exe`、本机工作目录 | 不可移植 | `pyproject.toml` 支持 Python >=3.11,<3.13，锁定环境验证为 3.12 | 快速启动使用 Python 3.12 与相对路径 |
| 39、48、78 与新 4 项散落多个小节 | 版本和统计口径混用 | 历史 XML 与 `TEST_REPORT.md` 分属不同运行 | 列明历史 78 回归、4 项环境补验及真实模型结果，绝不累计成新全量 |
| 中文 Recall@3/5=1.0 | 容易误读成报告准确率 | 20 条合成检索集，4 无答案仍有 3 条返回候选 | 标明召回任务、合成数据及与答案质量的区别 |
| ChatOpenAI/Ollama 与 DeepSeek 的区别不集中 | Provider 实现边界不清 | `local_llm.py` 的 json_schema；`deepseek.py` 的 json_object、严格本地 Pydantic 校验 | 增加 Provider 对照及错误/预算语义 |
| ARCHITECTURE 末尾“付费端点未验收且未调用” | 与新实现不一致 | DeepSeek 一次公开合成 A 真实 HTTP 记录 | 最小修订架构现状；测试流水原样保留并增加阅读提示 |

源码依据：`workflow.py` 五节点图、`runtime.py`/`store.py` 状态与预算、`vector.py` 本地模型及 PgVector、`evidence.py` 引用、`api.py` HTTP 入口。来源与许可见 [第三方说明](../THIRD_PARTY_NOTICES.md)。AI 辅助实现、工作流设计参考与个人实际贡献应分别表述。
