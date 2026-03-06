"""智能文本切片模块。

支持按字符数切片，保持段落完整性。
"""

import logging
import re
from typing import Iterator

logger = logging.getLogger("tkp_worker.chunker")


class TextChunker:
    """文本切片器。"""

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 200):
        """初始化切片器。

        Args:
            chunk_size: 每个切片的目标字符数
            chunk_overlap: 切片之间的重叠字符数
        """
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        logger.info("initialized chunker: size=%d, overlap=%d", chunk_size, chunk_overlap)

    def chunk_text(self, text: str) -> list[str]:
        """将文本切分成多个块。

        Args:
            text: 输入文本

        Returns:
            切片列表
        """
        if not text.strip():
            return []

        # 先按段落分割
        paragraphs = self._split_paragraphs(text)

        chunks = []
        current_chunk = []
        current_length = 0

        for para in paragraphs:
            para_length = len(para)

            # 如果单个段落超过 chunk_size，需要强制切分
            if para_length > self.chunk_size:
                # 先保存当前累积的块
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = []
                    current_length = 0

                # 强制切分长段落
                for sub_chunk in self._split_long_paragraph(para):
                    chunks.append(sub_chunk)
                continue

            # 如果加上这个段落会超过 chunk_size
            if current_length + para_length > self.chunk_size:
                # 保存当前块
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))

                # 计算重叠部分
                overlap_chunks = []
                overlap_length = 0
                for prev_para in reversed(current_chunk):
                    if overlap_length + len(prev_para) <= self.chunk_overlap:
                        overlap_chunks.insert(0, prev_para)
                        overlap_length += len(prev_para)
                    else:
                        break

                # 开始新块，包含重叠部分
                current_chunk = overlap_chunks + [para]
                current_length = sum(len(p) for p in current_chunk)
            else:
                # 继续累积
                current_chunk.append(para)
                current_length += para_length

        # 保存最后一个块
        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        logger.info("chunked text: input_len=%d, chunks=%d", len(text), len(chunks))
        return chunks

    def _split_paragraphs(self, text: str) -> list[str]:
        """按段落分割文本。"""
        # 按双换行符或多个换行符分割
        paragraphs = re.split(r"\n\s*\n", text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _split_long_paragraph(self, paragraph: str) -> Iterator[str]:
        """强制切分超长段落。"""
        # 尝试按句子分割
        sentences = re.split(r"([。！？.!?]+)", paragraph)

        current = []
        current_length = 0

        for i in range(0, len(sentences), 2):
            sentence = sentences[i]
            punctuation = sentences[i + 1] if i + 1 < len(sentences) else ""
            full_sentence = sentence + punctuation

            if current_length + len(full_sentence) > self.chunk_size:
                if current:
                    yield "".join(current)
                    # 添加重叠
                    overlap_text = "".join(current)[-self.chunk_overlap :]
                    current = [overlap_text, full_sentence]
                    current_length = len(overlap_text) + len(full_sentence)
                else:
                    # 单个句子就超长，强制按字符切分
                    for sub_chunk in self._split_by_chars(full_sentence):
                        yield sub_chunk
                    current = []
                    current_length = 0
            else:
                current.append(full_sentence)
                current_length += len(full_sentence)

        if current:
            yield "".join(current)

    def _split_by_chars(self, text: str) -> Iterator[str]:
        """按字符强制切分（最后的手段）。"""
        for i in range(0, len(text), self.chunk_size - self.chunk_overlap):
            yield text[i : i + self.chunk_size]


def create_chunker(chunk_size: int = 800, chunk_overlap: int = 200) -> TextChunker:
    """创建文本切片器的工厂函数。"""
    return TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)