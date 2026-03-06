"""Agent 工具编排模块。

支持多种工具的注册、调用和编排。
"""

import logging
from typing import Any, Callable

logger = logging.getLogger("tkp_api.agents.tools")


class Tool:
    """工具定义。"""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, Any],
        function: Callable,
        requires_approval: bool = False,
    ):
        """初始化工具。

        Args:
            name: 工具名称
            description: 工具描述
            parameters: 参数定义（JSON Schema）
            function: 工具函数
            requires_approval: 是否需要用户批准
        """
        self.name = name
        self.description = description
        self.parameters = parameters
        self.function = function
        self.requires_approval = requires_approval

    def execute(self, **kwargs) -> Any:
        """执行工具。"""
        try:
            return self.function(**kwargs)
        except Exception as exc:
            logger.exception("tool execution failed: %s", exc)
            raise

    def to_openai_function(self) -> dict[str, Any]:
        """转换为 OpenAI Function 格式。"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """工具注册表。"""

    def __init__(self):
        """初始化工具注册表。"""
        self.tools = {}

    def register(self, tool: Tool):
        """注册工具。"""
        self.tools[tool.name] = tool
        logger.info("tool registered: %s", tool.name)

    def get(self, name: str) -> Tool | None:
        """获取工具。"""
        return self.tools.get(name)

    def list_tools(self) -> list[Tool]:
        """列出所有工具。"""
        return list(self.tools.values())

    def get_openai_functions(self) -> list[dict[str, Any]]:
        """获取 OpenAI Functions 格式的工具列表。"""
        return [tool.to_openai_function() for tool in self.tools.values()]


# 内置工具定义

def retrieval_tool(query: str, kb_ids: list[str], top_k: int = 5) -> dict[str, Any]:
    """检索工具。

    Args:
        query: 查询文本
        kb_ids: 知识库 ID 列表
        top_k: 返回结果数

    Returns:
        检索结果
    """
    # 这里应该调用实际的检索服务
    logger.info("retrieval tool called: query=%s, kb_ids=%s, top_k=%d", query, kb_ids, top_k)
    return {
        "hits": [],
        "message": "Retrieval tool executed (placeholder)",
    }


def calculator_tool(expression: str) -> dict[str, Any]:
    """计算器工具。

    Args:
        expression: 数学表达式

    Returns:
        计算结果
    """
    try:
        # 安全的数学表达式求值
        import ast
        import operator

        operators = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.USub: operator.neg,
        }

        def eval_expr(node):
            if isinstance(node, ast.Num):
                return node.n
            elif isinstance(node, ast.BinOp):
                return operators[type(node.op)](eval_expr(node.left), eval_expr(node.right))
            elif isinstance(node, ast.UnaryOp):
                return operators[type(node.op)](eval_expr(node.operand))
            else:
                raise ValueError(f"Unsupported operation: {type(node)}")

        tree = ast.parse(expression, mode="eval")
        result = eval_expr(tree.body)

        return {
            "result": result,
            "expression": expression,
        }
    except Exception as exc:
        logger.exception("calculator tool failed: %s", exc)
        return {
            "error": str(exc),
            "expression": expression,
        }


def web_search_tool(query: str, num_results: int = 5) -> dict[str, Any]:
    """网络搜索工具。

    Args:
        query: 搜索查询
        num_results: 返回结果数

    Returns:
        搜索结果
    """
    logger.info("web search tool called: query=%s, num_results=%d", query, num_results)
    # 这里应该调用实际的搜索 API
    return {
        "results": [],
        "message": "Web search tool executed (placeholder)",
    }


def datetime_tool(operation: str) -> dict[str, Any]:
    """日期时间工具。

    Args:
        operation: 操作类型（now/today/timestamp）

    Returns:
        日期时间信息
    """
    from datetime import datetime

    if operation == "now":
        return {
            "datetime": datetime.now().isoformat(),
            "timestamp": datetime.now().timestamp(),
        }
    elif operation == "today":
        return {
            "date": datetime.now().date().isoformat(),
        }
    elif operation == "timestamp":
        return {
            "timestamp": datetime.now().timestamp(),
        }
    else:
        return {
            "error": f"Unknown operation: {operation}",
        }


def create_default_tools() -> list[Tool]:
    """创建默认工具集。"""
    return [
        Tool(
            name="retrieval",
            description="Search knowledge base for relevant information",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    },
                    "kb_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of knowledge base IDs to search",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return",
                        "default": 5,
                    },
                },
                "required": ["query", "kb_ids"],
            },
            function=retrieval_tool,
            requires_approval=False,
        ),
        Tool(
            name="calculator",
            description="Evaluate mathematical expressions",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The mathematical expression to evaluate",
                    },
                },
                "required": ["expression"],
            },
            function=calculator_tool,
            requires_approval=False,
        ),
        Tool(
            name="web_search",
            description="Search the web for information",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            function=web_search_tool,
            requires_approval=True,
        ),
        Tool(
            name="datetime",
            description="Get current date and time information",
            parameters={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["now", "today", "timestamp"],
                        "description": "The operation to perform",
                    },
                },
                "required": ["operation"],
            },
            function=datetime_tool,
            requires_approval=False,
        ),
    ]


# 全局工具注册表
_tool_registry = None


def get_tool_registry() -> ToolRegistry:
    """获取全局工具注册表。"""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
        # 注册默认工具
        for tool in create_default_tools():
            _tool_registry.register(tool)
    return _tool_registry
