# ResearchPilot 演示资料（本地自编示例，不是外部事实核验来源）

LangGraph 通过 StateGraph 显式定义研究工作流的节点、状态和条件边。研究任务可以经过计划、检索、评估和报告生成阶段。

LangGraph Checkpointer 用于保存图执行的中间状态，便于针对同一个 thread_id 查看执行进度并在满足条件时继续执行。

需要注意，持久化检查点不等于任务完成保证，也不保证调用外部工具的副作用具备 exactly-once 语义。
