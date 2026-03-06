"""LLM 生成服务模块。

使用 OpenAI Chat API 生成基于检索上下文的回答。
"""

import logging
from typing import Any

logger = logging.getLogger("tkp_api.rag.llm_generator")


class LLMGenerator:
    """LLM 生成器。"""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ):
        """初始化生成器。

        Args:
            api_key: OpenAI API 密钥
            model: 聊天模型名称
            temperature: 生成温度
            max_tokens: 最大生成 token 数
        """
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("LLM generator requires 'openai' package") from exc

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        logger.info("initialized LLM generator: model=%s, temp=%.2f", model, temperature)

    def generate_answer(
        self,
        *,
        query: str,
        context_chunks: list[dict[str, Any]],
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        """基于检索上下文生成回答。

        Args:
            query: 用户查询
            context_chunks: 检索到的文档块列表
            system_prompt: 可选的系统提示词

        Returns:
            包含 answer、usage、citations 的字典
        """
        if not query.strip():
            raise ValueError("Query cannot be empty")

        # 构建上下文
        context_parts = []
        citations = []
        for i, chunk in enumerate(context_chunks, start=1):
            context_parts.append(
                f"[文档{i}] {chunk['document_title']} (相似度: {chunk['similarity']:.2f})\n{chunk['content']}"
            )
            citations.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "document_id": chunk["document_id"],
                    "document_title": chunk["document_title"],
                    "kb_name": chunk["kb_name"],
                    "chunk_no": chunk["chunk_no"],
                    "similarity": chunk["similarity"],
                }
            )

        context_text = "\n\n".join(context_parts)

        # 默认系统提示词
        if not system_prompt:
            system_prompt = (
                "你是一个专业的知识助手。请基于提供的文档内容回答用户问题。\n"
                "要求：\n"
                "1. 仅使用提供的文档内容回答，不要编造信息\n"
                "2. 如果文档中没有相关信息，明确告知用户\n"
                "3. 回答要准确、简洁、有条理\n"
                "4. 在回答中引用文档编号（如[文档1]）来标注信息来源"
            )

        # 构建消息
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"参考文档：\n\n{context_text}\n\n用户问题：{query}",
            },
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            answer = response.choices[0].message.content
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

            logger.info(
                "generated answer: query_len=%d, answer_len=%d, tokens=%d",
                len(query),
                len(answer) if answer else 0,
                usage["total_tokens"],
            )

            return {
                "answer": answer or "",
                "usage": usage,
                "citations": citations,
                "model": self.model,
            }

        except Exception as exc:
            logger.exception("failed to generate answer: %s", exc)
            raise RuntimeError(f"LLM generation failed: {exc}") from exc

    def generate_streaming_answer(
        self,
        *,
        query: str,
        context_chunks: list[dict[str, Any]],
        system_prompt: str | None = None,
    ):
        """流式生成回答（生成器函数）。

        Args:
            query: 用户查询
            context_chunks: 检索到的文档块列表
            system_prompt: 可选的系统提示词

        Yields:
            生成的文本片段
        """
        if not query.strip():
            raise ValueError("Query cannot be empty")

        # 构建上下文（与非流式相同）
        context_parts = []
        for i, chunk in enumerate(context_chunks, start=1):
            context_parts.append(
                f"[文档{i}] {chunk['document_title']} (相似度: {chunk['similarity']:.2f})\n{chunk['content']}"
            )

        context_text = "\n\n".join(context_parts)

        if not system_prompt:
            system_prompt = (
                "你是一个专业的知识助手。请基于提供的文档内容回答用户问题。\n"
                "要求：\n"
                "1. 仅使用提供的文档内容回答，不要编造信息\n"
                "2. 如果文档中没有相关信息，明确告知用户\n"
                "3. 回答要准确、简洁、有条理\n"
                "4. 在回答中引用文档编号（如[文档1]）来标注信息来源"
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"参考文档：\n\n{context_text}\n\n用户问题：{query}",
            },
        ]

        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
            )

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as exc:
            logger.exception("failed to generate streaming answer: %s", exc)
            raise RuntimeError(f"Streaming LLM generation failed: {exc}") from exc


def create_generator(
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    temperature: float = 0.7,
    max_tokens: int = 2000,
) -> LLMGenerator:
    """创建生成器的工厂函数。"""
    return LLMGenerator(
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )