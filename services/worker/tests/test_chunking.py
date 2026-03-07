from tkp_worker.chunker import create_chunker
from tkp_worker.main import _extract_filename_from_key, _normalize_metadata


def test_chunker_splits_long_text():
    text = ("段落A " * 120) + "\n\n" + ("段落B " * 120)
    chunker = create_chunker(chunk_size=220, chunk_overlap=40)
    chunks = chunker.chunk_text(text)

    assert len(chunks) >= 2
    assert all(chunk for chunk in chunks)
    assert chunks[0] != chunks[-1]


def test_normalize_metadata_supports_dict_json_and_invalid_text():
    assert _normalize_metadata({"lang": "zh"}) == {"lang": "zh"}
    assert _normalize_metadata('{"topic":"refund"}') == {"topic": "refund"}
    assert _normalize_metadata("invalid-json") == {}
    assert _normalize_metadata(None) == {}


def test_extract_filename_from_key():
    assert _extract_filename_from_key("tenant/a/doc.md") == "doc.md"
    assert _extract_filename_from_key("plain.txt") == "plain.txt"
