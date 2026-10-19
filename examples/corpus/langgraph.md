# LangGraph persistence

LangGraph checkpoints graph state at execution boundaries. A stable thread_id identifies a run. Recovery also needs idempotent external operations and persisted budgets.

LangGraph 检查点支持状态持久化和中断恢复，外部副作用仍需幂等处理，预算不能在恢复时重置。