"""Intent classification for chat path.

Uses a lightweight LLM call to determine whether the user's question
requires knowledge-base retrieval or can be answered directly.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from tkp_api.services.pipeline.types import IntentResult

logger = logging.getLogger("tkp_api.pipeline.intent_classifier")

INTENT_SYSTEM_PROMPT = """\
你是一个意图分类器。用户正在使用一个知识库问答系统，系统中存储了用户自己上传的文档。
根据用户的当前问题和最近的对话历史，判断用户的意图类型。

重要原则：
- 用户使用的是知识库系统，大多数问题都可能与知识库内容相关
- 只有明确的闲聊（如"你好"、"谢谢"）才应判定为不需要检索
- 如果有任何可能与知识库文档相关，都应设为 needs_retrieval=true
- 宁可多检索也不要遗漏

意图类型：
- knowledge_query: 可能需要检索知识库的问题（默认选择，包括任何可能在文档中有答案的问题）
- chitchat: 明确的闲聊、问候、感谢（仅限"你好"、"谢谢"、"你是谁"等明确闲聊）
- conversation_context: 基于对话上下文的问题（如"帮我总结刚才说的"、"上一个问题换个说法"）
- clarification: 对之前回答的澄清请求（如"你说的第二点是什么意思"）

请用JSON格式回复：
{"intent": "...", "confidence": 0.0-1.0, "needs_retrieval": true/false, "reasoning": "..."}
"""


class IntentClassifier:
    """Classify user intent to decide whether retrieval is needed."""

    def __init__(self, *, client: Any, model: str = "gpt-4o-mini"):
        self.client = client
        self.model = model

    def classify(
        self,
        query: str,
        history: list[dict] | None = None,
    ) -> IntentResult:
        """Classify intent. Returns IntentResult.

        Falls back to knowledge_query on any error (conservative strategy).
        """
        try:
            messages: list[dict[str, str]] = [
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            ]

            # Add recent history for context (last 2 pairs)
            if history:
                for msg in history[-4:]:
                    messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")[:500]})

            messages.append({"role": "user", "content": query})

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
                max_tokens=200,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content
            data = json.loads(raw)

            intent = data.get("intent", "knowledge_query")
            confidence = float(data.get("confidence", 0.5))
            needs_retrieval = data.get("needs_retrieval", True)
            reasoning = data.get("reasoning", "")

            # Conservative: only chitchat with high confidence skips retrieval
            if intent != "chitchat" or confidence < 0.85:
                needs_retrieval = True

            result = IntentResult(
                intent=intent,
                confidence=confidence,
                needs_retrieval=needs_retrieval,
                reasoning=reasoning,
            )
            logger.info(
                "intent classified: intent=%s, confidence=%.2f, needs_retrieval=%s",
                intent, confidence, needs_retrieval,
            )
            return result

        except Exception as exc:
            logger.warning("intent classification failed, defaulting to knowledge_query: %s", exc)
            return IntentResult(
                intent="knowledge_query",
                confidence=0.0,
                needs_retrieval=True,
                reasoning=f"fallback due to error: {exc}",
            )
