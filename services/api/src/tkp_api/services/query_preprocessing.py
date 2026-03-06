"""Query 预处理增强服务。

提供查询预处理功能：
- 语言识别
- 拼写纠错
- 查询规范化
"""

import logging
import re
from typing import Any

logger = logging.getLogger("tkp_api.query_preprocessing")


class QueryPreprocessor:
    """查询预处理器。"""

    def __init__(
        self,
        *,
        enable_language_detection: bool = True,
        enable_spell_correction: bool = True,
        openai_client=None,
    ):
        """初始化查询预处理器。

        Args:
            enable_language_detection: 是否启用语言识别
            enable_spell_correction: 是否启用拼写纠错
            openai_client: OpenAI 客户端（用于高级纠错）
        """
        self.enable_language_detection = enable_language_detection
        self.enable_spell_correction = enable_spell_correction
        self.openai_client = openai_client

        # 初始化语言检测器
        self.language_detector = None
        if enable_language_detection:
            try:
                from langdetect import detect, detect_langs
                self.detect = detect
                self.detect_langs = detect_langs
                logger.info("language detection enabled")
            except ImportError:
                logger.warning("langdetect not installed, language detection disabled")
                self.enable_language_detection = False

        # 初始化拼写纠错器
        self.spell_corrector = None
        if enable_spell_correction:
            try:
                from spellchecker import SpellChecker
                self.spell_corrector = SpellChecker()
                logger.info("spell correction enabled")
            except ImportError:
                logger.warning("pyspellchecker not installed, spell correction disabled")
                self.enable_spell_correction = False

    def preprocess(self, query: str) -> dict[str, Any]:
        """预处理查询。

        Args:
            query: 原始查询

        Returns:
            预处理结果，包含：
            - original_query: 原始查询
            - processed_query: 处理后的查询
            - language: 检测到的语言
            - language_confidence: 语言置信度
            - corrections: 拼写纠错列表
            - normalized: 是否进行了规范化
        """
        if not query or not query.strip():
            return {
                "original_query": query,
                "processed_query": query,
                "language": None,
                "language_confidence": 0.0,
                "corrections": [],
                "normalized": False,
            }

        result = {
            "original_query": query,
            "processed_query": query,
            "language": None,
            "language_confidence": 0.0,
            "corrections": [],
            "normalized": False,
        }

        # 1. 语言识别
        if self.enable_language_detection:
            language_info = self._detect_language(query)
            result["language"] = language_info["language"]
            result["language_confidence"] = language_info["confidence"]

        # 2. 拼写纠错
        corrections = []
        corrected_query = query
        if self.enable_spell_correction:
            correction_result = self._correct_spelling(query, result.get("language"))
            corrected_query = correction_result["corrected_query"]
            corrections = correction_result["corrections"]
            result["corrections"] = corrections

        # 3. 查询规范化
        normalized_query = self._normalize_query(corrected_query)
        if normalized_query != corrected_query:
            result["normalized"] = True

        result["processed_query"] = normalized_query

        logger.debug(
            "query preprocessed: lang=%s, corrections=%d, normalized=%s",
            result["language"],
            len(corrections),
            result["normalized"],
        )

        return result

    def _detect_language(self, query: str) -> dict[str, Any]:
        """检测查询语言。"""
        if not self.enable_language_detection:
            return {"language": None, "confidence": 0.0}

        try:
            # 检测语言
            lang_probs = self.detect_langs(query)
            if lang_probs:
                top_lang = lang_probs[0]
                return {
                    "language": top_lang.lang,
                    "confidence": top_lang.prob,
                }
        except Exception as exc:
            logger.debug("language detection failed: %s", exc)

        return {"language": None, "confidence": 0.0}

    def _correct_spelling(self, query: str, language: str | None = None) -> dict[str, Any]:
        """拼写纠错。"""
        if not self.enable_spell_correction:
            return {"corrected_query": query, "corrections": []}

        corrections = []
        corrected_words = []

        # 分词
        words = query.split()

        for word in words:
            # 跳过非字母词（数字、标点等）
            if not re.match(r"^[a-zA-Z]+$", word):
                corrected_words.append(word)
                continue

            # 检查拼写
            if language == "en" or language is None:
                corrected = self._correct_english_word(word)
                if corrected != word:
                    corrections.append({
                        "original": word,
                        "corrected": corrected,
                    })
                corrected_words.append(corrected)
            else:
                # 其他语言暂不支持
                corrected_words.append(word)

        corrected_query = " ".join(corrected_words)

        return {
            "corrected_query": corrected_query,
            "corrections": corrections,
        }

    def _correct_english_word(self, word: str) -> str:
        """纠正英文单词。"""
        if not self.spell_corrector:
            return word

        try:
            # 检查是否拼写错误
            if word.lower() in self.spell_corrector:
                return word

            # 获取纠正建议
            corrected = self.spell_corrector.correction(word.lower())
            if corrected and corrected != word.lower():
                # 保持原始大小写风格
                if word.isupper():
                    return corrected.upper()
                elif word[0].isupper():
                    return corrected.capitalize()
                else:
                    return corrected

        except Exception as exc:
            logger.debug("spell correction failed for word '%s': %s", word, exc)

        return word

    def _normalize_query(self, query: str) -> str:
        """规范化查询。"""
        # 1. 去除多余空格
        normalized = re.sub(r"\s+", " ", query).strip()

        # 2. 统一标点符号
        normalized = normalized.replace("？", "?")
        normalized = normalized.replace("！", "!")
        normalized = normalized.replace("，", ",")
        normalized = normalized.replace("。", ".")
        normalized = normalized.replace("；", ";")
        normalized = normalized.replace("：", ":")

        # 3. 去除首尾标点
        normalized = normalized.strip(".,;:!?")

        return normalized

    def correct_with_llm(self, query: str) -> dict[str, Any]:
        """使用 LLM 进行高级纠错。

        适用于复杂的语法错误或语义纠错。
        """
        if not self.openai_client:
            return {"corrected_query": query, "corrections": []}

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a query correction assistant. Correct spelling and grammar errors in the user's query. Return only the corrected query without explanation.",
                    },
                    {
                        "role": "user",
                        "content": query,
                    },
                ],
                temperature=0.0,
                max_tokens=200,
            )

            corrected_query = response.choices[0].message.content.strip()

            if corrected_query != query:
                logger.info("llm correction applied: '%s' -> '%s'", query, corrected_query)
                return {
                    "corrected_query": corrected_query,
                    "corrections": [{"original": query, "corrected": corrected_query}],
                }

        except Exception as exc:
            logger.warning("llm correction failed: %s", exc)

        return {"corrected_query": query, "corrections": []}
