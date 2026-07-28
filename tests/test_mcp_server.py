"""
测试 mcp_server — 全部离线：协议层用手写的请求字典直打 handle_request，
传输层用 io.StringIO 注入 stdin/stdout，不起进程、不碰网络。
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from moodle_scraper import __version__, mcp_server
from moodle_scraper.mcp_server import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    SERVER_NAME,
    TOOLS,
    _parse_argv,
    empty_index,
    handle_request,
    load_server_index,
    serve,
)
from moodle_scraper.study import notebook, planner
from moodle_scraper.study.index import CourseIndex, Material, save_index


# ─── 测试夹具 ───────────────────────────────────────────────

def _material(
    course: str,
    rel_path: str,
    *,
    kind: str = "lecture",
    week: int | None = None,
    text: str = "",
    size: int = 1024,
    root: str = "/data",
) -> Material:
    """造一份内存里的 Material（路径不需要真实存在）"""
    name = Path(rel_path).stem
    return Material(
        path=f"{root}/{course}/{rel_path}",
        rel_path=rel_path,
        name=name,
        ext=Path(rel_path).suffix.lower(),
        course=course,
        size=size,
        modified=1700000000.0,
        kind=kind,
        week=week,
        text=text,
    )


@pytest.fixture()
def index() -> CourseIndex:
    """两门课、六份材料的内存索引"""
    comp = [
        _material("COMP1511", "Week1_Lecture.pdf", kind="lecture", week=1,
                  text="pointers and memory"),
        _material("COMP1511", "Week2_Lecture.pdf", kind="lecture", week=2),
        _material("COMP1511", "Lab_03.txt", kind="lab", week=3,
                  text="this lab covers quantum tunnelling"),
        _material("COMP1511", "notes/cheatsheet.md", kind="notes", text="revision notes"),
    ]
    phys = [
        _material("PHYS1231", "Assignment_1.pdf", kind="assignment", week=4),
        _material("PHYS1231", "quantum.txt", kind="other", text="", size=10),
    ]
    return CourseIndex(
        root="/data",
        generated_at="2026-07-28T00:00:00+00:00",
        courses={"COMP1511": comp, "PHYS1231": phys},
    )


def _call(index: CourseIndex, tool: str, arguments: dict | None = None, req_id: int = 1) -> dict:
    """发一条 tools/call 请求"""
    params: dict = {"name": tool}
    if arguments is not None:
        params["arguments"] = arguments
    response = handle_request(
        {"jsonrpc": "2.0", "id": req_id, "method": "tools/call", "params": params},
        index,
    )
    assert response is not None
    return response


def _text(response: dict) -> str:
    """从工具响应里取出正文文本"""
    content = response["result"]["content"]
    assert isinstance(content, list) and content
    assert content[0]["type"] == "text"
    return content[0]["text"]


# ─── initialize / ping / 通知 ───────────────────────────────

def test_initialize_returns_handshake(index: CourseIndex) -> None:
    response = handle_request(
        {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}, index
    )

    assert response is not None
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 0
    result = response["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION == "2024-11-05"
    assert result["serverInfo"] == {"name": SERVER_NAME, "version": __version__}
    assert result["capabilities"]["tools"] == {}


def test_initialize_without_params(index: CourseIndex) -> None:
    response = handle_request({"jsonrpc": "2.0", "id": 7, "method": "initialize"}, index)

    assert response is not None
    assert response["result"]["serverInfo"]["name"] == "moodle-downloader"


def test_ping_returns_empty_result(index: CourseIndex) -> None:
    response = handle_request({"jsonrpc": "2.0", "id": 2, "method": "ping"}, index)

    assert response == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_initialized_notification_returns_none(index: CourseIndex) -> None:
    assert handle_request(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}, index
    ) is None


def test_request_without_id_is_a_notification(index: CourseIndex) -> None:
    assert handle_request({"jsonrpc": "2.0", "method": "tools/list"}, index) is None


# ─── tools/list ─────────────────────────────────────────────

def test_tools_list_shape(index: CourseIndex) -> None:
    response = handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}, index)

    assert response is not None
    tools = response["result"]["tools"]
    assert isinstance(tools, list)
    names = [tool["name"] for tool in tools]
    assert names == [
        "list_courses",
        "search_materials",
        "get_material_text",
        "course_overview",
        "revision_plan",
    ]

    for tool in tools:
        assert tool["description"].strip()
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)
        assert isinstance(schema["required"], list)
        for key in schema["required"]:
            assert key in schema["properties"]

    by_name = {tool["name"]: tool for tool in tools}
    assert by_name["search_materials"]["inputSchema"]["required"] == ["query"]
    assert by_name["get_material_text"]["inputSchema"]["required"] == ["path"]
    assert by_name["course_overview"]["inputSchema"]["required"] == ["course"]
    assert by_name["revision_plan"]["inputSchema"]["required"] == ["course"]


def test_tools_list_result_is_a_copy(index: CourseIndex) -> None:
    """返回的是深拷贝，客户端改不动模块级定义"""
    response = handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/list"}, index)

    assert response is not None
    response["result"]["tools"][0]["name"] = "hacked"
    assert TOOLS[0]["name"] == "list_courses"


def test_tools_list_is_json_serialisable(index: CourseIndex) -> None:
    response = handle_request({"jsonrpc": "2.0", "id": 5, "method": "tools/list"}, index)

    assert response is not None
    json.dumps(response)


# ─── list_courses ───────────────────────────────────────────

def test_list_courses_happy_path(index: CourseIndex) -> None:
    text = _text(_call(index, "list_courses", {}))

    assert "COMP1511" in text
    assert "PHYS1231" in text
    assert "4 material(s)" in text
    assert "lecture 2" in text
    assert "weeks: 1-3" in text


def test_list_courses_without_arguments_key(index: CourseIndex) -> None:
    text = _text(_call(index, "list_courses"))

    assert "COMP1511" in text


def test_list_courses_on_empty_index() -> None:
    text = _text(_call(empty_index("/nowhere"), "list_courses", {}))

    assert "No courses indexed" in text


# ─── search_materials ───────────────────────────────────────

def test_search_materials_finds_by_name(index: CourseIndex) -> None:
    text = _text(_call(index, "search_materials", {"query": "Lab_03"}))

    assert "Lab_03.txt" in text
    assert "1 result(s)" in text
    assert "path:" in text


def test_search_materials_finds_by_extracted_text(index: CourseIndex) -> None:
    text = _text(_call(index, "search_materials", {"query": "tunnelling"}))

    assert "Lab_03.txt" in text


def test_search_materials_course_filter(index: CourseIndex) -> None:
    text = _text(_call(index, "search_materials", {"query": "quantum", "course": "PHYS1231"}))

    assert "quantum.txt" in text
    assert "Lab_03.txt" not in text


def test_search_materials_limit_is_respected(index: CourseIndex) -> None:
    text = _text(_call(index, "search_materials", {"query": "week", "limit": 1}))

    assert "1 result(s)" in text


def test_search_materials_no_hits(index: CourseIndex) -> None:
    response = _call(index, "search_materials", {"query": "thermodynamics"})

    assert "No material matched" in _text(response)
    assert "isError" not in response["result"]


def test_search_materials_unknown_course_is_tool_error(index: CourseIndex) -> None:
    response = _call(index, "search_materials", {"query": "x", "course": "MATH1131"})

    assert response["result"]["isError"] is True
    assert "COMP1511" in _text(response)


def test_search_materials_missing_query(index: CourseIndex) -> None:
    response = _call(index, "search_materials", {})

    assert response["error"]["code"] == INVALID_PARAMS
    assert "query" in response["error"]["message"]


def test_search_materials_wrong_query_type(index: CourseIndex) -> None:
    response = _call(index, "search_materials", {"query": 42})

    assert response["error"]["code"] == INVALID_PARAMS


def test_search_materials_bad_limit_type(index: CourseIndex) -> None:
    response = _call(index, "search_materials", {"query": "week", "limit": "many"})

    assert response["error"]["code"] == INVALID_PARAMS


# ─── get_material_text ──────────────────────────────────────

def test_get_material_text_by_absolute_path(index: CourseIndex) -> None:
    text = _text(_call(index, "get_material_text", {"path": "/data/COMP1511/Lab_03.txt"}))

    assert "this lab covers quantum tunnelling" in text
    assert "--- text ---" in text


def test_get_material_text_by_relative_path(index: CourseIndex) -> None:
    text = _text(_call(index, "get_material_text", {"path": "notes/cheatsheet.md"}))

    assert "revision notes" in text


def test_get_material_text_by_file_name(index: CourseIndex) -> None:
    text = _text(_call(index, "get_material_text", {"path": "Lab_03.txt"}))

    assert "quantum tunnelling" in text


def test_get_material_text_when_unavailable(index: CourseIndex) -> None:
    """索引里没正文、磁盘上也没文件 → 明确说明而不是空结果"""
    response = _call(index, "get_material_text", {"path": "Week2_Lecture.pdf"})

    text = _text(response)
    assert "No text available" in text
    assert "pypdf" in text
    assert "isError" not in response["result"]


def test_get_material_text_falls_back_to_disk(tmp_path: Path) -> None:
    """索引里 text 为空，但文件还在磁盘上 → 现场读出来"""
    real = tmp_path / "COMP1511" / "reading.md"
    real.parent.mkdir(parents=True)
    real.write_text("chapter one: recursion", encoding="utf-8")

    material = Material(
        path=str(real), rel_path="reading.md", name="reading", ext=".md",
        course="COMP1511", size=real.stat().st_size, modified=0.0,
        kind="notes", week=None, text="",
    )
    idx = CourseIndex(root=str(tmp_path), generated_at="", courses={"COMP1511": [material]})

    text = _text(_call(idx, "get_material_text", {"path": "reading.md"}))

    assert "chapter one: recursion" in text


def test_get_material_text_unknown_path(index: CourseIndex) -> None:
    response = _call(index, "get_material_text", {"path": "nope.pdf"})

    assert response["result"]["isError"] is True
    assert "No indexed material matches" in _text(response)


def test_get_material_text_missing_path(index: CourseIndex) -> None:
    response = _call(index, "get_material_text", {})

    assert response["error"]["code"] == INVALID_PARAMS


def test_get_material_text_empty_path(index: CourseIndex) -> None:
    response = _call(index, "get_material_text", {"path": "   "})

    assert response["error"]["code"] == INVALID_PARAMS


# ─── course_overview ────────────────────────────────────────

def test_course_overview_groups_by_week(index: CourseIndex) -> None:
    text = _text(_call(index, "course_overview", {"course": "COMP1511"}))

    assert text.startswith("COMP1511 — 4 material(s)")
    assert "Week 1" in text
    assert "Week 3" in text
    assert "No week detected" in text
    assert "[lab] COMP1511 / Lab_03.txt" in text
    # 有周次的排在无周次的前面
    assert text.index("Week 1") < text.index("No week detected")


def test_course_overview_is_case_insensitive(index: CourseIndex) -> None:
    text = _text(_call(index, "course_overview", {"course": "comp1511"}))

    assert "COMP1511" in text


def test_course_overview_partial_match(index: CourseIndex) -> None:
    text = _text(_call(index, "course_overview", {"course": "PHYS"}))

    assert "PHYS1231" in text


def test_course_overview_unknown_course(index: CourseIndex) -> None:
    response = _call(index, "course_overview", {"course": "MATH1131"})

    assert response["result"]["isError"] is True
    assert "Unknown course" in _text(response)


def test_course_overview_missing_course(index: CourseIndex) -> None:
    response = _call(index, "course_overview", {})

    assert response["error"]["code"] == INVALID_PARAMS


# ─── revision_plan ──────────────────────────────────────────

def test_revision_plan_default_days(index: CourseIndex) -> None:
    text = _text(_call(index, "revision_plan", {"course": "COMP1511"}))

    assert "over 7 day(s)" in text
    assert "## Day 1" in text
    assert "## Day 7" in text
    # 材料比天数少 → 后面的天没有新材料，但仍有间隔重复的回顾任务
    assert "no new material — review only" in text
    assert "### Review" in text


def test_revision_plan_custom_days_covers_every_material(index: CourseIndex) -> None:
    text = _text(_call(index, "revision_plan", {"course": "COMP1511", "days": 2}))

    assert "over 2 day(s)" in text
    assert "## Day 3" not in text
    for rel in ("Week1_Lecture.pdf", "Week2_Lecture.pdf", "Lab_03.txt", "notes/cheatsheet.md"):
        assert rel in text


def test_revision_plan_orders_by_week(index: CourseIndex) -> None:
    text = _text(_call(index, "revision_plan", {"course": "COMP1511", "days": 1}))

    assert text.index("Week1_Lecture.pdf") < text.index("Lab_03.txt")
    # 无周次的材料排到最后
    assert text.index("Lab_03.txt") < text.index("cheatsheet.md")


def test_revision_plan_accepts_numeric_string_days(index: CourseIndex) -> None:
    text = _text(_call(index, "revision_plan", {"course": "COMP1511", "days": "3"}))

    assert "over 3 day(s)" in text


def test_revision_plan_rejects_zero_days(index: CourseIndex) -> None:
    response = _call(index, "revision_plan", {"course": "COMP1511", "days": 0})

    assert response["error"]["code"] == INVALID_PARAMS


def test_revision_plan_rejects_absurd_days(index: CourseIndex) -> None:
    response = _call(index, "revision_plan", {"course": "COMP1511", "days": 500})

    assert response["error"]["code"] == INVALID_PARAMS


def test_revision_plan_unknown_course(index: CourseIndex) -> None:
    response = _call(index, "revision_plan", {"course": "MATH1131"})

    assert response["result"]["isError"] is True


# ─── 协议错误 ───────────────────────────────────────────────

def test_unknown_method(index: CourseIndex) -> None:
    response = handle_request(
        {"jsonrpc": "2.0", "id": 9, "method": "resources/list"}, index
    )

    assert response is not None
    assert response["id"] == 9
    assert response["error"]["code"] == METHOD_NOT_FOUND
    assert "resources/list" in response["error"]["message"]


def test_unknown_tool(index: CourseIndex) -> None:
    response = _call(index, "delete_everything", {})

    assert response["error"]["code"] == INVALID_PARAMS
    assert "Unknown tool" in response["error"]["message"]


def test_tools_call_without_name(index: CourseIndex) -> None:
    response = handle_request(
        {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {}}, index
    )

    assert response is not None
    assert response["error"]["code"] == INVALID_PARAMS


def test_tools_call_with_non_object_arguments(index: CourseIndex) -> None:
    response = handle_request(
        {"jsonrpc": "2.0", "id": 11, "method": "tools/call",
         "params": {"name": "list_courses", "arguments": "oops"}},
        index,
    )

    assert response is not None
    assert response["error"]["code"] == INVALID_PARAMS


def test_non_object_params(index: CourseIndex) -> None:
    response = handle_request(
        {"jsonrpc": "2.0", "id": 12, "method": "tools/list", "params": [1, 2]}, index
    )

    assert response is not None
    assert response["error"]["code"] == INVALID_PARAMS


def test_missing_method_with_id(index: CourseIndex) -> None:
    response = handle_request({"jsonrpc": "2.0", "id": 13}, index)

    assert response is not None
    assert response["error"]["code"] < 0


def test_non_dict_request(index: CourseIndex) -> None:
    response = handle_request(["not", "a", "request"], index)  # type: ignore[arg-type]

    assert response is not None
    assert "error" in response


def test_internal_error_is_reported_not_raised(index: CourseIndex, monkeypatch) -> None:
    """工具内部炸了 → -32603，而不是异常逃出 handle_request"""
    def boom(arguments: dict, idx: CourseIndex) -> dict:
        raise RuntimeError("kaboom")

    monkeypatch.setitem(mcp_server._TOOL_HANDLERS, "list_courses", boom)
    response = _call(index, "list_courses", {})

    assert response["error"]["code"] == INTERNAL_ERROR
    assert "kaboom" in response["error"]["message"]


# ─── serve() 端到端 ─────────────────────────────────────────

def _run_serve(lines: list[str], **kwargs) -> list[dict]:
    """把若干行喂给 serve()，收集输出的 JSON 消息"""
    stdin = io.StringIO("\n".join(lines) + "\n")
    stdout = io.StringIO()
    serve(stdin=stdin, stdout=stdout, **kwargs)
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


def test_serve_end_to_end(tmp_path: Path, index: CourseIndex) -> None:
    index_file = tmp_path / "index.json"
    save_index(index, index_file)

    messages = _run_serve(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "list_courses", "arguments": {}}}),
        ],
        index_path=index_file,
    )

    # 通知不回包 → 只有 3 条响应
    assert [m["id"] for m in messages] == [1, 2, 3]
    assert messages[0]["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert len(messages[1]["result"]["tools"]) == 5
    assert "COMP1511" in messages[2]["result"]["content"][0]["text"]


def test_serve_skips_malformed_and_blank_lines(tmp_path: Path, index: CourseIndex) -> None:
    index_file = tmp_path / "index.json"
    save_index(index, index_file)

    messages = _run_serve(
        [
            "{not json at all",
            "",
            "   ",
            "[1, 2, 3]",
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            "}}}",
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
        ],
        index_path=index_file,
    )

    assert [m["id"] for m in messages] == [1, 2]
    assert all(m["result"] == {} for m in messages)


def test_serve_output_is_one_json_object_per_line(tmp_path: Path, index: CourseIndex) -> None:
    index_file = tmp_path / "index.json"
    save_index(index, index_file)

    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    )
    stdout = io.StringIO()
    serve(index_path=index_file, stdin=stdin, stdout=stdout)

    raw = stdout.getvalue()
    assert raw.endswith("\n")
    assert len(raw.strip().splitlines()) == 1
    assert raw.isascii()  # 全 ASCII 转义，任何终端编码都写得出去


def test_serve_builds_index_from_root(tmp_path: Path) -> None:
    course = tmp_path / "MATH1131"
    course.mkdir()
    (course / "Week1_Lecture.txt").write_text("limits", encoding="utf-8")

    messages = _run_serve(
        [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": "list_courses", "arguments": {}}})],
        root=tmp_path,
    )

    assert "MATH1131" in messages[0]["result"]["content"][0]["text"]


def test_serve_with_broken_index_file_falls_back_to_root(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{{{", encoding="utf-8")
    course = tmp_path / "MATH1131"
    course.mkdir()
    (course / "Week1_Lecture.txt").write_text("limits", encoding="utf-8")

    messages = _run_serve(
        [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": "list_courses", "arguments": {}}})],
        index_path=broken,
        root=tmp_path,
    )

    assert "MATH1131" in messages[0]["result"]["content"][0]["text"]


def test_serve_on_empty_input(tmp_path: Path) -> None:
    stdout = io.StringIO()
    serve(root=tmp_path, stdin=io.StringIO(""), stdout=stdout)

    assert stdout.getvalue() == ""


# ─── 索引加载 / 命令行解析 ──────────────────────────────────

def test_load_server_index_prefers_index_path(tmp_path: Path, index: CourseIndex) -> None:
    index_file = tmp_path / "index.json"
    save_index(index, index_file)

    loaded = load_server_index(index_path=index_file, root=tmp_path)

    assert loaded.course_names() == ["COMP1511", "PHYS1231"]


def test_load_server_index_builds_from_root(tmp_path: Path) -> None:
    (tmp_path / "ARTS1630").mkdir()
    (tmp_path / "ARTS1630" / "Week1.txt").write_text("kana", encoding="utf-8")

    loaded = load_server_index(root=tmp_path)

    assert loaded.course_names() == ["ARTS1630"]


def test_empty_index_has_no_courses() -> None:
    idx = empty_index("/some/root")

    assert idx.courses == {}
    assert idx.root == "/some/root"
    assert idx.generated_at


def test_parse_argv() -> None:
    assert _parse_argv([]) == (None, None)
    assert _parse_argv(["--root", "downloads"]) == (None, "downloads")
    assert _parse_argv(["--index", "a.json", "--root", "b"]) == ("a.json", "b")
    assert _parse_argv(["--root"]) == (None, None)
    assert _parse_argv(["--unknown", "x", "--root", "b"]) == (None, "b")


# ─── 跨模块一致性 ───────────────────────────────────────────

def test_no_local_plan_implementation() -> None:
    """
    MCP 不得自带一套排序 / 排期实现

    历史上这里有过 _KIND_ORDER / _revision_sort_key / _split_evenly 的副本，
    与笔记本各自演化后，同一门课经 revision_plan 和经 build_revision_notebook
    会得到两份对不上的计划。现在统一由 study/planner.py 提供，副本必须不存在。
    """
    for name in ("_KIND_ORDER", "_revision_sort_key", "_split_evenly"):
        assert not hasattr(mcp_server, name), f"{name} 又出现了副本，应改用 study.planner"

    # 用的必须就是 planner 里那一份（同一对象，不是等值的拷贝）
    assert mcp_server.revision_sort_key is planner.revision_sort_key
    assert mcp_server.build_plan is planner.build_plan


def test_notebook_and_mcp_share_one_planner() -> None:
    """笔记本与 MCP 必须引用同一个排期实现"""
    assert notebook.build_plan is planner.build_plan
    assert notebook.DayPlan is planner.DayPlan


def test_kind_order_covers_every_kind_index_can_emit() -> None:
    """index.detect_kind() 产出的每一种类型都要在排序表里有位置"""
    from moodle_scraper.study.index import _KIND_KEYWORDS

    kinds = {kind for kind, _ in _KIND_KEYWORDS} | {"other"}

    assert kinds <= set(planner.KIND_ORDER)


def test_mcp_and_notebook_plans_agree(index: CourseIndex) -> None:
    """
    同一门课、同样天数：MCP 文本里的材料顺序必须与笔记本的计划一致

    这是上面那些结构性断言的行为级兜底——就算有人绕过 planner，
    只要两边结果对不上，这条就会红。
    """
    text = _text(_call(index, "revision_plan", {"course": "COMP1511", "days": 3}))
    plans = planner.build_plan(index, course="COMP1511", days=3)

    expected = [m.rel_path for plan in plans for m in plan.materials]
    positions = [text.index(rel) for rel in expected]

    assert positions == sorted(positions), "MCP 输出顺序与 planner 计划不一致"


def test_tools_list_matches_handler_table() -> None:
    """TOOLS 里公布的工具和实际注册的处理函数必须一一对应"""
    assert {t["name"] for t in TOOLS} == set(mcp_server._TOOL_HANDLERS)
