"""LLM 生成服务模块。

使用 OpenAI Chat API 生成基于检索上下文的回答。
"""

import logging
import re
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
        history_messages: list[dict[str, str]] | None = None,
        include_confidence: bool = False,
    ) -> dict[str, Any]:
        """基于检索上下文生成回答。

        Args:
            query: 用户查询
            context_chunks: 检索到的文档块列表
            system_prompt: 可选的系统提示词
            history_messages: 历史对话消息（用于上下文记忆）
            include_confidence: 是否要求 LLM 提供置信度评分

        Returns:
            包含 answer、usage、citations、llm_confidence 的字典
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
            if include_confidence:
                system_prompt = (
                    "你是一个专业的知识助手。请基于提供的文档内容回答用户问题。\n"
                    "要求：\n"
                    "1. 仅使用提供的文档内容回答，不要编造信息\n"
                    "2. 如果文档中没有相关信息，明确告知用户\n"
                    "3. 回答要准确、简洁、有条理\n"
                    "4. 在回答中引用文档编号（如[文档1]）来标注信息来源\n"
                    "5. 注意上下文，如果用户提到'上次'、'刚才'等，参考历史对话\n"
                    "6. 在回答末尾用 [CONFIDENCE: X.XX] 格式提供你对答案的置信度（0.00-1.00）"
                )
            else:
                system_prompt = (
                    "你是一个专业的知识助手。请基于提供的文档内容回答用户问题。\n"
                    "要求：\n"
                    "1. 仅使用提供的文档内容回答，不要编造信息\n"
                    "2. 如果文档中没有相关信息，明确告知用户\n"
                    "3. 回答要准确、简洁、有条理\n"
                    "4. 在回答中引用文档编号（如[文档1]）来标注信息来源\n"
                    "5. 注意上下文，如果用户提到'上次'、'刚才'等，参考历史对话"
                )

        # 构建消息
        messages = [
            {"role": "system", "content": system_prompt},
        ]

        # 添加历史对话（短期记忆）
        if history_messages:
            # 限制历史消息数量，避免超出上下文窗口
            max_history = 10  # 最多保留最近 10 轮对话
            recent_history = history_messages[-max_history * 2:] if len(history_messages) > max_history * 2 else history_messages
            messages.extend(recent_history)

        # 添加当前问题和检索上下文
        messages.append({
            "role": "user",
            "content": f"参考文档：\n\n{context_text}\n\n用户问题：{query}",
        })

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

            # 提取 LLM 置信度（如果有）
            llm_confidence = None
            if include_confidence:
                llm_confidence = self._extract_confidence(answer)
                # 移除置信度标记
                answer = self._remove_confidence_marker(answer)

            logger.info(
                "generated answer: query_len=%d, answer_len=%d, tokens=%d, llm_confidence=%s",
                len(query),
                len(answer) if answer else 0,
                usage["total_tokens"],
                f"{llm_confidence:.2f}" if llm_confidence is not None else "N/A",
            )

            return {
                "answer": answer or "",
                "usage": usage,
                "citations": citations,
                "model": self.model,
                "llm_confidence": llm_confidence,
            }

        except Exception as exc:
            logger.exception("failed to generate answer: %s", exc)
            raise RuntimeError(f"LLM generation failed: {exc}") from exc

    def _extract_confidence(self, text: str) -> float | None:
        """从文本中提取置信度分数。

        Args:
            text: LLM 生成的文本

        Returns:
            置信度分数（0-1），如果未找到则返回 None
        """
        # 匹配 [CONFIDENCE: X.XX] 格式
        pattern = r'\[CONFIDENCE:\s*([0-9]*\.?[0-9]+)\]'
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            try:
                confidence = float(match.group(1))
                # 确保在 0-1 范围内
                return max(0.0, min(1.0, confidence))
            except ValueError:
                logger.warning("failed to parse confidence value: %s", match.group(1))
                return None

        return None

    def _remove_confidence_marker(self, text: str) -> str:
        """从文本中移除置信度标记。

        Args:
            text: LLM 生成的文本

        Returns:
            移除置信度标记后的文本
        """
        # 移除 [CONFIDENCE: X.XX] 标记
        pattern = r'\[CONFIDENCE:\s*[0-9]*\.?[0-9]+\]'
        cleaned_text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        # 清理多余的空白
        cleaned_text = cleaned_text.strip()

        return cleaned_text

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