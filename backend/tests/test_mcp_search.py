"""MCP-клиент веб-поиска (spec web-search, design D1–D4, D8, D9)."""
import asyncio
import io
import json
import logging
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.rag import mcp_search as ms

FIXTURE = Path(__file__).parent / "fixtures" / "tavily_search_response.json"
SEARCH_SCHEMA = {"properties": {"query": {"type": "string"}, "max_results": {"anyOf": [{"type": "integer"}]}},
                 "required": ["query"]}


def _tool(name, schema=None, description=""):
    return SimpleNamespace(name=name, input_schema=schema or {}, description=description)


TOOLS = [_tool("tavily_extract"), _tool("tavily_crawl"), _tool("tavily_search", SEARCH_SCHEMA), _tool("tavily_map")]


# ---------- выбор инструмента ----------

def test_pick_tool_by_server_list():
    assert ms.pick_tool(TOOLS).name == "tavily_search"
    assert ms.pick_tool([_tool("web_search_exa"), _tool("tavily_search")]).name == "web_search_exa"
    assert ms.pick_tool([_tool("tavily_extract"), _tool("deep_research")]) is None


def test_pick_tool_override():
    assert ms.pick_tool(TOOLS, "tavily_map").name == "tavily_map"
    assert ms.pick_tool(TOOLS, "brave_search") is None


def test_build_args_from_schema():
    assert ms.build_args(TOOLS[2], "q", 3) == {"query": "q", "max_results": 3}
    no_limit = _tool("s", {"properties": {"query": {"type": "string"}}, "required": ["query"]})
    assert ms.build_args(no_limit, "q", 3) == {"query": "q"}
    other = _tool("s", {"properties": {"text": {"type": "string"}, "n": {"type": "integer"}}, "required": ["text"]})
    assert ms.build_args(other, "q", 3) == {"text": "q"}


# ---------- разбор и нормализация ----------

def _fixture_parts():
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return d["structuredContent"], [c["text"] for c in d["content"] if c["type"] == "text"]


def test_parse_real_tavily_response():
    structured, texts = _fixture_parts()
    from_structured = ms.normalize(ms.parse_result(structured, texts), 3, 800)
    from_text = ms.normalize(ms.parse_result(None, texts), 3, 800)
    assert from_structured == from_text and len(from_structured) == 3
    for r in from_structured:
        assert r["url"].startswith("https://") and r["title"] and r["domain"] and len(r["content"]) <= 800
        assert "\\_" not in r["content"]  # markdown-экранирование снято
    assert from_structured[1]["domain"] == "github.com"


def test_parse_text_format():
    text = ("Title: Первая\nURL: https://a.example/1\nContent: текст один\n\n"
            "Title: Вторая\nURL: https://b.example/2\nContent: текст два")
    items = ms.normalize(ms.parse_result(None, [text]), 3, 800)
    assert [i["url"] for i in items] == ["https://a.example/1", "https://b.example/2"]


def test_normalize_limits_and_filters():
    items = [
        {"title": "long", "url": "https://www.x.org/a", "content": "слово " * 1000},
        {"title": "no url", "content": "c"},
        {"title": "js", "url": "javascript:alert(1)", "content": "c"},
        {"title": "ftp", "url": "ftp://x.org/f", "content": "c"},
        {"title": "dup", "url": "https://www.x.org/a", "content": "c"},
        {"title": "b", "url": "http://b.org", "content": "<script>alert(1)</script>"},
        {"title": "c", "url": "https://c.org", "content": "c"},
        {"title": "d", "url": "https://d.org", "content": "d"},
    ]
    out = ms.normalize(items, 3, 800)
    assert [o["url"] for o in out] == ["https://www.x.org/a", "http://b.org", "https://c.org"]
    assert len(out[0]["content"]) <= 800 and out[0]["content"].endswith("…")
    assert out[0]["domain"] == "x.org"
    assert out[1]["content"] == "<script>alert(1)</script>"  # текст как есть, экранирует интерфейс


def test_is_error_result_raises():
    with pytest.raises(RuntimeError):
        ms.parse_result(None, ["rate limit"], is_error=True)


# ---------- search() на подменённой сессии ----------

class FakeSession:
    def __init__(self, tools=TOOLS, result=None, exc=None):
        self.tools, self.result, self.exc = tools, result, exc
        self.calls = []
        self.list_calls = 0

    async def list_tools(self):
        self.list_calls += 1
        return SimpleNamespace(tools=self.tools)

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        if self.exc:
            raise self.exc
        return self.result


def _searcher(session, **kw) -> ms.WebSearcher:
    ws = ms.WebSearcher("https://mcp.example/mcp/", "tvly-SECRET-123", **kw)

    @asynccontextmanager
    async def fake_session():
        yield session

    ws._session = fake_session
    return ws


def _result(structured, texts=(), is_error=False):
    return SimpleNamespace(structured_content=structured, is_error=is_error,
                           content=[SimpleNamespace(type="text", text=t) for t in texts])


def test_search_ok_and_tool_cache():
    structured, texts = _fixture_parts()
    sess = FakeSession(result=_result(structured, texts))
    ws = _searcher(sess)
    r = asyncio.run(ws.search("  llama.cpp Q4_K_M  "))
    assert r["status"] == "ok" and r["query"] == "llama.cpp Q4_K_M" and r["tool"] == "tavily_search"
    assert [x["label"] for x in r["results"]] == ["W1", "W2", "W3"]
    assert sess.calls == [("tavily_search", {"query": "llama.cpp Q4_K_M", "max_results": 3})]
    asyncio.run(ws.search("ещё"))
    assert sess.list_calls == 1  # описание инструмента закэшировано


def test_search_empty():
    r = asyncio.run(_searcher(FakeSession(result=_result({"results": []}))).search("q"))
    assert r["status"] == "empty" and r["results"] == [] and r["error"] is None


def test_search_error_masks_key_and_resets_cache():
    sess = FakeSession(exc=RuntimeError("401 Unauthorized for key tvly-SECRET-123"))
    ws = _searcher(sess)
    r = asyncio.run(ws.search("q"))
    assert r["status"] == "error" and "tvly-SECRET-123" not in r["error"] and "***" in r["error"]
    assert ws.tool_name is None


def test_search_tool_missing():
    r = asyncio.run(_searcher(FakeSession(tools=[_tool("tavily_extract")])).search("q"))
    assert r["status"] == "error" and "не найден" in r["error"]


def test_search_query_truncated():
    sess = FakeSession(result=_result({"results": []}))
    asyncio.run(_searcher(sess).search("я" * 1000))
    assert len(sess.calls[0][1]["query"]) == ms.QUERY_MAX_CHARS


def test_injection_flag():
    on = asyncio.run(_searcher(FakeSession(exc=RuntimeError("down")), inject_test=True).search("q"))
    assert on["status"] == "error" and len(on["results"]) == 1
    syn = on["results"][0]
    assert syn["synthetic"] is True and ms.INJECTION_TEXT in syn["content"] and syn["label"] == "W1"
    off = asyncio.run(_searcher(FakeSession(result=_result({"results": []}))).search("q"))
    assert off["results"] == []


# ---------- настоящий транспорт: тайм-аут и отказ соединения ----------

def test_timeout_on_hanging_server():
    async def run():
        async def hang(reader, writer):
            await asyncio.sleep(30)

        server = await asyncio.start_server(hang, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            ws = ms.WebSearcher(f"http://127.0.0.1:{port}/mcp/", None, timeout_s=0.5)
            t0 = time.perf_counter()
            r = await ws.search("q")
            return r, time.perf_counter() - t0

    r, dt = asyncio.run(run())
    assert r["status"] == "timeout" and r["results"] == []
    assert 0.4 < dt < 3 and 400 <= r["t_ms"] < 3000


def test_connection_refused():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    r = asyncio.run(ms.WebSearcher(f"http://127.0.0.1:{port}/mcp/", None, timeout_s=5).search("q"))
    assert r["status"] == "error" and r["error"]


# ---------- ключ ----------

def test_secret_mask_filter():
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.addFilter(ms.SecretMaskFilter("tvly-SECRET-123"))
    lg = logging.getLogger("test.mask")
    lg.addHandler(handler)
    lg.propagate = False
    lg.warning("header Authorization: Bearer %s", "tvly-SECRET-123")
    try:
        raise ValueError("bad key tvly-SECRET-123")
    except ValueError:
        lg.exception("boom")
    out = buf.getvalue()
    assert "tvly-SECRET-123" not in out and out.count("***") >= 2


def test_settings_key_is_secret(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-SECRET-123")
    s = Settings(jwt_secret="x")
    assert s.mcp_api_key == "tvly-SECRET-123" and "tvly-SECRET-123" not in repr(s)
    monkeypatch.setenv("TAVILY_API_KEY", "  ")
    assert Settings(jwt_secret="x").mcp_api_key is None
    ws = ms.WebSearcher.from_settings(Settings(jwt_secret="x"))
    assert ws.auth_mode.startswith("keyless") and ws.timeout_s == 10 and ws.max_results == 3
