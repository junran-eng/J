# ============================================================
# tests/test_scraper.py — Scraper unit tests
# ============================================================
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_extract_text_from_html():
    """_extract_text parses HTML and extracts meaningful text"""
    from infra.scraper import _extract_text
    html = b"<html><body><h1>Important Heading Here</h1><p>Hello world test paragraph with enough length</p></body></html>"
    text = _extract_text(html)
    assert "Hello world" in text


def test_extract_text_strips_scripts():
    """_extract_text removes script and style tags"""
    from infra.scraper import _extract_text
    html = b"<html><head><script>alert('xss')</script></head><body><p>Real content here</p></body></html>"
    text = _extract_text(html)
    assert "alert" not in text
    assert "Real content" in text


def test_extract_text_short_lines_filtered():
    """_extract_text filters out lines shorter than 10 chars"""
    from infra.scraper import _extract_text
    html = b"<html><body><p>Hi</p><p>This is a proper paragraph with enough length</p></body></html>"
    text = _extract_text(html)
    assert "Hi" not in text.split("\n")
    assert "proper paragraph" in text


def test_load_sources_from_config_defaults():
    """_load_sources_from_config returns defaults when config.yaml missing"""
    from infra.scraper import _load_sources_from_config
    sources = _load_sources_from_config()
    assert isinstance(sources, list)
    assert len(sources) >= 5  # At least built-in defaults
    for src in sources:
        assert "name" in src
        assert "urls" in src


def test_scrape_web_invalid_source():
    """scrape_web handles completely invalid source gracefully"""
    from infra.scraper import scrape_web
    result = scrape_web("test_topic_nonexistent_xyz", ["test"])
    assert isinstance(result, dict)
    # All sources should report status
    for name, (status, _detail) in result.items():
        assert status in ("成功", "失败")


def test_default_sources_have_required_fields():
    """Built-in default sources have name and urls"""
    from infra.scraper import _DEFAULT_SOURCES
    assert len(_DEFAULT_SOURCES) == 7
    for src in _DEFAULT_SOURCES:
        assert "name" in src
        assert isinstance(src["urls"], list)
        for url_entry in src["urls"]:
            assert "type" in url_entry
            assert "url" in url_entry


if __name__ == "__main__":
    test_extract_text_from_html()
    test_extract_text_strips_scripts()
    test_extract_text_short_lines_filtered()
    test_load_sources_from_config_defaults()
    test_scrape_web_invalid_source()
    test_default_sources_have_required_fields()
    print("ALL SCRAPER TESTS PASSED")
