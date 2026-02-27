from tkp_worker.main import _chunk_text


def test_chunk_text_splits_long_text():
    text = "a" * 2200
    chunks = _chunk_text(text, chunk_size=500, overlap=50)

    assert len(chunks) >= 4
    assert all(chunk for chunk in chunks)
