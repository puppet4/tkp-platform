from tkp_worker.main import _chunk_text, _embed_text, _normalize_metadata, _vector_to_pg_literal


def test_chunk_text_splits_long_text():
    text = "a" * 2200
    chunks = _chunk_text(text, chunk_size=500, overlap=50)

    assert len(chunks) >= 4
    assert all(chunk for chunk in chunks)


def test_embed_text_is_deterministic_and_normalized():
    vector1 = _embed_text("知识库检索测试", dim=16)
    vector2 = _embed_text("知识库检索测试", dim=16)
    vector3 = _embed_text("完全不同的问题", dim=16)

    assert len(vector1) == 16
    assert vector1 == vector2
    assert vector1 != vector3
    assert abs(sum(v * v for v in vector1) - 1.0) < 1e-6


def test_vector_to_pg_literal_format():
    literal = _vector_to_pg_literal([0.12, -0.5, 0.0])
    assert literal == "[0.120000,-0.500000,0.000000]"


def test_normalize_metadata_supports_dict_and_json_text():
    assert _normalize_metadata({"lang": "zh"}) == {"lang": "zh"}
    assert _normalize_metadata('{"topic":"refund"}') == {"topic": "refund"}
    assert _normalize_metadata("invalid-json") == {}
    assert _normalize_metadata(None) == {}
