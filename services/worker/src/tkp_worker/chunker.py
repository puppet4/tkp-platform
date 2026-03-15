"""Token-level, heading-aware, hierarchical text chunking.

Improvements over original character-level chunker:
- Measures in tokens (512/64) instead of characters (800/200)
- Detects Markdown headings to preserve document structure
- Builds title_path (cumulative heading hierarchy)
- Supports parent/child two-level chunking
- Strips Markdown image syntax noise
- Prepends title to each chunk for better retrieval
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Iterator

logger = logging.getLogger("tkp_worker.chunker")

# Heading regex: matches # through ######
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# Markdown image pattern: ![alt](path)
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")

# Approximate token count: tiktoken is optional
_ENCODING = None


def _get_encoding():
    global _ENCODING
    if _ENCODING is None:
        try:
            import tiktoken
            _ENCODING = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            _ENCODING = False  # sentinel: not available
    return _ENCODING


def _count_tokens(text: str) -> int:
    enc = _get_encoding()
    if enc:
        return len(enc.encode(text))
    # Fallback: ~1 token per 3.5 chars for mixed CJK/Latin
    return max(1, int(len(text) / 3.5))


def _clean_markdown(text: str) -> str:
    """Strip Markdown noise (images, excessive blank lines) while keeping text."""
    # Replace image syntax with alt text only (if alt text is useful) or remove entirely
    text = _IMAGE_RE.sub("", text)
    # Collapse 3+ blank lines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@dataclass
class Chunk:
    """A text chunk with structural metadata."""
    content: str
    chunk_no: int
    title_path: str = ""
    parent_chunk_id: str | None = None
    token_count: int = 0
    metadata: dict = field(default_factory=dict)


class TextChunker:
    """Token-level, heading-aware text chunker."""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        parent_chunk_size: int = 1024,
    ):
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")

        self.chunk_size = chunk_size  # tokens
        self.chunk_overlap = chunk_overlap  # tokens
        self.parent_chunk_size = parent_chunk_size  # tokens
        logger.info(
            "initialized chunker: size=%d tokens, overlap=%d tokens, parent=%d tokens",
            chunk_size, chunk_overlap, parent_chunk_size,
        )

    def chunk_text(self, text: str) -> list[str]:
        """Split text into chunks (simple string list for backward compatibility)."""
        chunks = self.chunk_text_structured(text)
        return [c.content for c in chunks]

    def chunk_text_structured(self, text: str) -> list[Chunk]:
        """Split text into structured chunks with metadata."""
        if not text.strip():
            return []

        # Clean markdown noise before chunking
        text = _clean_markdown(text)
        if not text.strip():
            return []

        sections = self._split_by_headings(text)
        chunks: list[Chunk] = []
        chunk_no = 0

        for section in sections:
            title_path = section["title_path"]
            section_text = section["content"]

            if not section_text.strip():
                continue

            paragraphs = self._split_paragraphs(section_text)
            section_chunks = self._merge_paragraphs_to_chunks(paragraphs)

            for chunk_text in section_chunks:
                # Prepend title context to chunk for better retrieval relevance
                if title_path and not chunk_text.startswith(f"# {title_path}"):
                    enriched = f"[{title_path}]\n{chunk_text}"
                else:
                    enriched = chunk_text

                token_count = _count_tokens(enriched)

                # Skip empty or near-empty chunks (< 5 tokens of real content)
                if _count_tokens(chunk_text) < 5:
                    continue

                chunks.append(Chunk(
                    content=enriched,
                    chunk_no=chunk_no,
                    title_path=title_path,
                    token_count=token_count,
                    metadata={"title_path": title_path},
                ))
                chunk_no += 1

        # Build parent-child relationships
        self._assign_parent_children(chunks)

        logger.info("chunked text: input_len=%d, chunks=%d", len(text), len(chunks))
        return chunks

    def _split_by_headings(self, text: str) -> list[dict]:
        """Split text into sections by Markdown headings, tracking heading hierarchy."""
        sections = []
        heading_stack: list[tuple[int, str]] = []  # (level, title)

        lines = text.split("\n")
        current_lines: list[str] = []

        def flush():
            content = "\n".join(current_lines).strip()
            if content:
                path = " > ".join(t for _, t in heading_stack) if heading_stack else ""
                sections.append({"title_path": path, "content": content})

        for line in lines:
            match = _HEADING_RE.match(line.strip())
            if match:
                # Flush previous section
                flush()
                current_lines = []

                level = len(match.group(1))
                title = match.group(2).strip()

                # Pop headings at same or deeper level
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, title))

                # Include heading in the section content
                current_lines.append(line)
            else:
                current_lines.append(line)

        flush()

        # If no headings found, treat entire text as single section
        if not sections:
            sections = [{"title_path": "", "content": text}]

        return sections

    def _split_paragraphs(self, text: str) -> list[str]:
        """Split text into paragraphs."""
        paragraphs = re.split(r"\n\s*\n", text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _merge_paragraphs_to_chunks(self, paragraphs: list[str]) -> list[str]:
        """Merge paragraphs into token-budget chunks with overlap."""
        chunks = []
        current_parts: list[str] = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = _count_tokens(para)

            # Single paragraph exceeds chunk size → force split
            if para_tokens > self.chunk_size:
                if current_parts:
                    chunks.append("\n\n".join(current_parts))
                    current_parts = []
                    current_tokens = 0

                for sub in self._split_long_text(para):
                    chunks.append(sub)
                continue

            # Would exceed budget → flush current
            if current_tokens + para_tokens > self.chunk_size:
                if current_parts:
                    chunks.append("\n\n".join(current_parts))

                # Overlap: carry last paragraphs that fit in overlap budget
                overlap_parts: list[str] = []
                overlap_tokens = 0
                for prev in reversed(current_parts):
                    prev_tokens = _count_tokens(prev)
                    if overlap_tokens + prev_tokens <= self.chunk_overlap:
                        overlap_parts.insert(0, prev)
                        overlap_tokens += prev_tokens
                    else:
                        break

                current_parts = overlap_parts + [para]
                current_tokens = overlap_tokens + para_tokens
            else:
                current_parts.append(para)
                current_tokens += para_tokens

        if current_parts:
            chunks.append("\n\n".join(current_parts))

        return chunks

    def _split_long_text(self, text: str) -> Iterator[str]:
        """Force-split text that exceeds chunk_size tokens."""
        sentences = re.split(r"([。！？.!?]+)", text)
        current: list[str] = []
        current_tokens = 0

        for i in range(0, len(sentences), 2):
            sentence = sentences[i]
            punct = sentences[i + 1] if i + 1 < len(sentences) else ""
            full = sentence + punct

            full_tokens = _count_tokens(full)

            if current_tokens + full_tokens > self.chunk_size:
                if current:
                    yield "".join(current)
                    current = [full]
                    current_tokens = full_tokens
                else:
                    # Single sentence exceeds limit → character split
                    yield from self._split_by_token_limit(full)
                    current = []
                    current_tokens = 0
            else:
                current.append(full)
                current_tokens += full_tokens

        if current:
            yield "".join(current)

    def _split_by_token_limit(self, text: str) -> Iterator[str]:
        """Last resort: split by approximate token boundaries."""
        enc = _get_encoding()
        if enc:
            tokens = enc.encode(text)
            step = self.chunk_size - self.chunk_overlap
            for i in range(0, len(tokens), step):
                chunk_tokens = tokens[i:i + self.chunk_size]
                yield enc.decode(chunk_tokens)
        else:
            # Fallback: character-based approximation
            chars_per_token = 3.5
            char_size = int(self.chunk_size * chars_per_token)
            char_overlap = int(self.chunk_overlap * chars_per_token)
            step = char_size - char_overlap
            for i in range(0, len(text), step):
                yield text[i:i + char_size]

    def _assign_parent_children(self, chunks: list[Chunk]) -> None:
        """Group consecutive chunks into parent chunks.

        Every `parent_chunk_size // chunk_size` consecutive child chunks
        share the same virtual parent. The first chunk in each group serves
        as the parent reference.
        """
        if not chunks:
            return

        children_per_parent = max(1, self.parent_chunk_size // self.chunk_size)

        for i, chunk in enumerate(chunks):
            group_start = (i // children_per_parent) * children_per_parent
            if group_start != i:
                # Point to the first chunk in the group as the "parent"
                chunk.parent_chunk_id = f"__parent_group_{group_start}"
            chunk.metadata["parent_group"] = group_start
            chunk.metadata["children_per_parent"] = children_per_parent


def create_chunker(
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    parent_chunk_size: int = 1024,
) -> TextChunker:
    """Create a text chunker instance."""
    return TextChunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        parent_chunk_size=parent_chunk_size,
    )
