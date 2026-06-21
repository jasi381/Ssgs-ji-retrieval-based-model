from __future__ import annotations

import importlib
import json
import sys
import types


class _FakeFastMCP:
    def __init__(self, *args, **kwargs):
        self.tools = []

    def tool(self):
        def decorator(func):
            self.tools.append(func.__name__)
            return func

        return decorator

    def run(self, *args, **kwargs):
        return None


def _install_fake_mcp(monkeypatch):
    mcp_module = types.ModuleType("mcp")
    server_module = types.ModuleType("mcp.server")
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fastmcp_module.FastMCP = _FakeFastMCP

    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_module)


def _load_server(monkeypatch):
    _install_fake_mcp(monkeypatch)
    sys.modules.pop("sggs_mcp.server", None)
    return importlib.import_module("sggs_mcp.server")


def _json_result(raw: str) -> dict:
    return json.loads(raw)


def test_all_expected_tools_registered(monkeypatch):
    server = _load_server(monkeypatch)
    assert set(server.mcp.tools) == {
        "smart_search",
        "find_line",
        "semantic_search",
        "search_translation",
        "search_gurmukhi",
        "get_ang",
        "get_shabad",
        "search_by_author",
        "search_by_raaga",
        "get_concept",
        "get_line",
    }


def test_smoke_all_tool_functions(monkeypatch):
    server = _load_server(monkeypatch)

    find_line = _json_result(server.find_line("das vastu le paache paave", limit=2))
    assert find_line["count"] > 0

    smart = _json_result(server.smart_search("for the sake of one thing withheld", limit=2))
    assert "routed_to" in smart

    # English topical query must return results — either via semantic or keyword fallback.
    smart_ego = _json_result(server.smart_search("teachings about ego", limit=2))
    assert smart_ego.get("count", 0) > 0, (
        f"smart_search returned 0 for English topical query — "
        f"semantic + keyword fallback both failed: {smart_ego}"
    )

    # semantic_search directly: may be unavailable (no deps) or have results —
    # but must NEVER return empty results without an error or count > 0.
    semantic = _json_result(server.semantic_search("teachings about ego", limit=1))
    assert "error" in semantic or semantic.get("count", 0) > 0, (
        f"semantic_search returned empty results with no error — "
        f"index may be built but empty: {semantic}"
    )

    translation = _json_result(server.search_translation("truth", limit=2))
    assert "lines" in translation

    gurmukhi = _json_result(server.search_gurmukhi("sat nam", limit=2))
    assert "lines" in gurmukhi

    ang = _json_result(server.get_ang(1))
    assert ang["ang"] == 1

    shabad_id = ang["shabad_ids"][0]
    shabad = _json_result(server.get_shabad(shabad_id))
    assert shabad["shabad_id"] == shabad_id

    author = _json_result(server.search_by_author("Guru Nanak", limit=1))
    assert author["count"] >= 1

    raaga = _json_result(server.search_by_raaga("Jap", limit=1))
    assert "lines" in raaga or "error" in raaga

    concept = _json_result(server.get_concept("Naam"))
    assert concept["concept"].lower() == "naam"

    line_id = find_line["results"][0]["line_id"]
    line = _json_result(server.get_line(line_id))
    assert line["line_id"] == line_id
