"""Agent 层：中心单 Agent + ReAct + Graph Workflow。

架构约定（硬约束）：不使用 CrewAI / AutoGen 等多 Agent 框架；
所有写操作必须经工具调用回到业务服务层执行，LLM 绝不直接写库。
V1 落地 LLM 接入层；V4 已实现 ReAct 循环与工具集（见 react.py / tools/registry.py）。
"""
