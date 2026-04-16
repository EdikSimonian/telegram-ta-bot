from unittest.mock import patch, MagicMock


def make_tavily_response(results):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": results}
    return mock_resp


def test_web_search_returns_formatted_results():
    results = [
        {"title": "Python Docs", "content": "Official docs", "url": "https://python.org"},
        {"title": "Real Python", "content": "Tutorials", "url": "https://realpython.com"},
    ]
    with patch("bot.search.requests.post", return_value=make_tavily_response(results)), \
         patch("bot.search.redis") as mock_redis:
        mock_redis.get.return_value = None
        from bot.search import web_search
        text, sources = web_search("python tutorials")
        assert "Python Docs" in text
        assert "https://python.org" in text
        assert "Real Python" in text


def test_web_search_returns_sources():
    results = [
        {"title": "Python Docs", "content": "Official docs", "url": "https://python.org"},
    ]
    with patch("bot.search.requests.post", return_value=make_tavily_response(results)), \
         patch("bot.search.redis") as mock_redis:
        mock_redis.get.return_value = None
        from bot.search import web_search
        text, sources = web_search("python tutorials")
        assert len(sources) == 1
        assert sources[0]["title"] == "Python Docs"
        assert sources[0]["url"] == "https://python.org"


def test_web_search_no_results():
    with patch("bot.search.requests.post", return_value=make_tavily_response([])), \
         patch("bot.search.redis") as mock_redis:
        mock_redis.get.return_value = None
        from bot.search import web_search
        text, sources = web_search("xkqzwmf")
        assert text == "No results found."
        assert sources == []


def test_web_search_sends_correct_payload():
    with patch("bot.search.requests.post", return_value=make_tavily_response([])) as mock_post, \
         patch("bot.search.redis") as mock_redis:
        mock_redis.get.return_value = None
        from bot.search import web_search
        web_search("test query")
        payload = mock_post.call_args[1]["json"]
        assert payload["query"] == "test query"
        assert payload["max_results"] == 5
        assert payload["search_depth"] == "basic"
        assert payload["include_answer"] is False
        assert payload["safe_search"] == "strict"


def test_web_search_returns_cached_result():
    import json
    cached = json.dumps({
        "text": "cached result",
        "sources": [{"title": "Cached", "url": "https://example.com"}],
    })
    with patch("bot.search.requests.post") as mock_post, \
         patch("bot.search.redis") as mock_redis:
        mock_redis.get.return_value = cached
        from bot.search import web_search
        text, sources = web_search("cached query")
        assert text == "cached result"
        assert sources[0]["url"] == "https://example.com"
        mock_post.assert_not_called()


def test_web_search_works_when_redis_cache_fails():
    results = [
        {"title": "Result", "content": "Content", "url": "https://example.com"},
    ]
    with patch("bot.search.requests.post", return_value=make_tavily_response(results)), \
         patch("bot.search.redis") as mock_redis:
        mock_redis.get.side_effect = Exception("connection refused")
        mock_redis.set.side_effect = Exception("connection refused")
        from bot.search import web_search
        text, sources = web_search("test")
        assert "Result" in text
        assert sources[0]["url"] == "https://example.com"
