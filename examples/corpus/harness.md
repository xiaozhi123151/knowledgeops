# Agent Harness

The Harness limits execution steps, tool attempts, model calls and token budgets. Timeouts and bounded retries prevent uncontrolled loops. SDK implicit retries must be disabled when the application owns retry accounting.

Agent 执行护栏限制步数、工具次数、模型调用和 Token 预算，超时和有限重试避免无限循环。