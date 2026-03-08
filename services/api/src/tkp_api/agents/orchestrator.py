"""Agent 编排器。

协调工具调用、沙箱执行、Guardrail 检查。
"""

import logging
from typing import Any
from uuid import UUID, uuid4

from tkp_api.agents.guardrail import GuardrailService
from tkp_api.agents.sandbox import SandboxExecutor
from tkp_api.agents.tools import ToolRegistry, create_default_tools

logger = logging.getLogger("tkp_api.agents.orchestrator")


class AgentRun:
    """Agent 运行记录。"""

    def __init__(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        task: str,
        status: str = "running",
    ):
        """初始化运行记录。"""
        self.run_id = run_id
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.task = task
        self.status = status
        self.steps = []
        self.result = None
        self.error = None


class AgentOrchestrator:
    """Agent 编排器。"""

    def __init__(
        self,
        *,
        openai_api_key: str,
        openai_api_base: str | None = None,
        model: str = "gpt-4o-mini",
        allowed_tools: list[str] | None = None,
        enable_sandbox: bool = True,
        enable_guardrail: bool = True,
        max_iterations: int = 10,
    ):
        """初始化 Agent 编排器。

        Args:
            openai_api_key: OpenAI API 密钥
            openai_api_base: OpenAI API 基础 URL（可选）
            model: 使用的模型
            allowed_tools: 允许的工具列表
            enable_sandbox: 是否启用沙箱
            enable_guardrail: 是否启用 Guardrail
            max_iterations: 最大迭代次数
        """
        from openai import OpenAI

        self.client = OpenAI(api_key=openai_api_key, base_url=openai_api_base if openai_api_base else None)
        self.model = model
        self.max_iterations = max_iterations

        # 初始化工具注册表
        self.tool_registry = ToolRegistry()
        for tool in create_default_tools():
            if allowed_tools is None or tool.name in allowed_tools:
                self.tool_registry.register(tool)

        # 初始化沙箱
        self.sandbox = SandboxExecutor() if enable_sandbox else None

        # 初始化 Guardrail
        self.guardrail = (
            GuardrailService(
                allowed_tools=allowed_tools or [t.name for t in create_default_tools()],
                max_calls_per_minute=60,
            )
            if enable_guardrail
            else None
        )

        logger.info(
            "agent orchestrator initialized: model=%s, tools=%d, sandbox=%s, guardrail=%s",
            model,
            len(self.tool_registry.list_tools()),
            enable_sandbox,
            enable_guardrail,
        )

    def run(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> AgentRun:
        """运行 Agent 任务。

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            task: 任务描述
            context: 上下文信息

        Returns:
            Agent 运行记录
        """
        run_id = uuid4()
        agent_run = AgentRun(
            run_id=run_id,
            tenant_id=tenant_id,
            user_id=user_id,
            task=task,
        )

        logger.info("agent run started: run_id=%s, task=%s", run_id, task)

        # Guardrail 检查输入
        if self.guardrail:
            validation = self.guardrail.validate_agent_input(str(user_id), task)
            if not validation["valid"]:
                agent_run.status = "failed"
                agent_run.error = f"Input validation failed: {validation['issues']}"
                logger.warning("agent run failed validation: %s", validation["issues"])
                return agent_run

        # 构建初始消息
        messages = [
            {
                "role": "system",
                "content": "You are a helpful AI assistant with access to various tools. "
                "Use the tools to help complete the user's task.",
            },
            {"role": "user", "content": task},
        ]

        # 迭代执行
        for iteration in range(self.max_iterations):
            logger.info("agent iteration %d/%d", iteration + 1, self.max_iterations)

            try:
                # 调用 LLM
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    functions=self.tool_registry.get_openai_functions(),
                    function_call="auto",
                    temperature=0.7,
                )

                message = response.choices[0].message

                # 记录步骤
                step = {
                    "iteration": iteration + 1,
                    "type": "llm_response",
                    "content": message.content,
                    "function_call": None,
                }

                # 检查是否有函数调用
                if message.function_call:
                    function_name = message.function_call.name
                    function_args = eval(message.function_call.arguments)

                    step["function_call"] = {
                        "name": function_name,
                        "arguments": function_args,
                    }

                    logger.info("function call: %s(%s)", function_name, function_args)

                    # Guardrail 检查工具调用
                    if self.guardrail:
                        tool_check = self.guardrail.validate_tool_call(function_name, function_args)
                        if not tool_check["valid"]:
                            agent_run.status = "failed"
                            agent_run.error = f"Tool call validation failed: {tool_check['issues']}"
                            agent_run.steps.append(step)
                            return agent_run

                    # 执行工具
                    tool = self.tool_registry.get(function_name)
                    if tool:
                        try:
                            tool_result = tool.execute(**function_args)
                            step["tool_result"] = tool_result

                            # 添加工具结果到消息历史
                            messages.append(message)
                            messages.append(
                                {
                                    "role": "function",
                                    "name": function_name,
                                    "content": str(tool_result),
                                }
                            )
                        except Exception as exc:
                            logger.exception("tool execution failed: %s", exc)
                            step["tool_error"] = str(exc)
                            messages.append(message)
                            messages.append(
                                {
                                    "role": "function",
                                    "name": function_name,
                                    "content": f"Error: {exc}",
                                }
                            )
                    else:
                        logger.warning("tool not found: %s", function_name)
                        step["tool_error"] = f"Tool '{function_name}' not found"

                    agent_run.steps.append(step)
                    continue

                # 没有函数调用，任务完成
                agent_run.steps.append(step)

                # Guardrail 检查输出
                if self.guardrail and message.content:
                    output_check = self.guardrail.validate_agent_output(message.content)
                    if not output_check["valid"]:
                        agent_run.result = output_check["sanitized_output"]
                        logger.warning("agent output sanitized: %s", output_check["issues"])
                    else:
                        agent_run.result = message.content
                else:
                    agent_run.result = message.content

                agent_run.status = "completed"
                logger.info("agent run completed: run_id=%s", run_id)
                return agent_run

            except Exception as exc:
                logger.exception("agent iteration failed: %s", exc)
                agent_run.status = "failed"
                agent_run.error = str(exc)
                return agent_run

        # 达到最大迭代次数
        agent_run.status = "max_iterations_reached"
        agent_run.error = f"Reached maximum iterations ({self.max_iterations})"
        logger.warning("agent run reached max iterations: run_id=%s", run_id)

        return agent_run


# 全局编排器实例
_orchestrator = None


def get_orchestrator(
    *,
    openai_api_key: str,
    openai_api_base: str | None = None,
    model: str = "gpt-4o-mini",
    allowed_tools: list[str] | None = None,
) -> AgentOrchestrator:
    """获取全局编排器实例。"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator(
            openai_api_key=openai_api_key,
            openai_api_base=openai_api_base,
            model=model,
            allowed_tools=allowed_tools,
        )
    return _orchestrator
