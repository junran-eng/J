# ============================================================
# tests/test_knowledge_base.py — Knowledge base unit tests
# ============================================================
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_split_chunks_basic():
    from infra.knowledge_base import _split_chunks
    text = 'Paragraph one.' + chr(10) + chr(10) + 'Paragraph two.' + chr(10) + chr(10) + 'Paragraph three.'
    chunks = _split_chunks(text, 'test.md')
    assert len(chunks) >= 1
    assert all('source' in c and 'text' in c for c in chunks)
    assert chunks[0]['source'] == 'test.md'


def test_split_chunks_large_text():
    from infra.knowledge_base import _split_chunks
    long_para = 'X' * 600
    text = long_para + chr(10) + chr(10) + long_para
    chunks = _split_chunks(text, 'test.md')
    assert len(chunks) >= 2


def test_split_chunks_respects_size():
    from infra.knowledge_base import _split_chunks
    short_text = (chr(10) + chr(10)).join(['Short para.'] * 50)
    chunks = _split_chunks(short_text, 'test.md')
    assert len(chunks) > 0
    for c in chunks:
        assert len(c['text']) < 1200


def test_score_chunk_keyword_match():
    from infra.knowledge_base import _score_chunk
    chunk = 'Low temperature drying equipment for sludge treatment'
    score1 = _score_chunk(chunk, 'drying sludge')
    score2 = _score_chunk(chunk, 'unrelated topic')
    assert score1 > score2


def test_score_chunk_heading_bonus():
    from infra.knowledge_base import _score_chunk
    chunk_heading = '# Drying Technology' + chr(10) + 'Some content here.'
    chunk_no_heading = 'Drying Technology' + chr(10) + 'Some content here.'
    score_h = _score_chunk(chunk_heading, 'drying')
    score_nh = _score_chunk(chunk_no_heading, 'drying')
    assert score_h > score_nh


def test_retrieve_empty_kb():
    from infra.knowledge_base import retrieve
    import infra.knowledge_base as kb
    original = kb._kb_chunks.copy() if kb._kb_chunks else []
    try:
        kb._kb_chunks = []
        result = retrieve('test', ['test'])
        assert result == ''
    finally:
        kb._kb_chunks = original


def test_load_knowledge_base_nonexistent_dir():
    import infra.knowledge_base as kb
    original = kb._kb_chunks.copy() if kb._kb_chunks else []
    try:
        kb.load_knowledge_base(kb_dir='/nonexistent/path/xyz123')
        assert kb._kb_loaded is True
        assert len(kb._kb_chunks) == 0
    finally:
        kb._kb_chunks = original


if __name__ == '__main__':
    test_split_chunks_basic()
    test_split_chunks_large_text()
    test_split_chunks_respects_size()
    test_score_chunk_keyword_match()
    test_score_chunk_heading_bonus()
    test_retrieve_empty_kb()
    test_load_knowledge_base_nonexistent_dir()
    print('ALL KNOWLEDGE BASE TESTS PASSED')
