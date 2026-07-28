"""
mcp_server — 把本地课件索引暴露成 MCP 服务（stdio + JSON-RPC 2.0）

任何 MCP 客户端（Claude Code / Claude Desktop / 支持 MCP 连接器的 ChatGPT）
都可以用 `python -m moodle_scraper.mcp_server` 拉起本服务，再通过 5 个工具
查询已经下载到本地的课件：列课程、搜材料、取正文、看总览、排复习计划。

协议只用标准库实现（stdin 一行一个 JSON 对象，stdout 同样一行一个），
不引入任何新依赖。本模块不 print、不 input：
  · handle_request() 是纯函数，只做协议 → 结果的映射，便于直接单测；
  · 所有 I/O 都集中在 serve() 里，且 stdin/stdout 可注入。

工具返回的文本是给 MCP 客户端里的模型读的（机器消费面），
不是终端 UI，因此不走 i18n 目录，统一用英文字段名。

⚠️ 免责声明: 本工具仅供学生处理本人已注册课程的课件。
Disclaimer: For students to process their own course materials only.
"""
from __future__ import annotations

import copy
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from . import __version__
from .study.index import (
    INDEX_FILENAME,
    CourseIndex,
    Material,
    build_index,
    extract_pdf_text,
    load_index,
)


# ─── 协议常量 ───────────────────────────────────────────────

JSONRPC_VERSION: str = "2.0"

# MCP 协议版本（与 Claude Desktop / Claude Code 当前使用的一致）
PROTOCOL_VERSION: str = "2024-11-05"

# 在 MCP 客户端里显示的服务名
SERVER_NAME: str = "moodle-downloader"

# JSON-RPC 2.0 标准错误码
PARSE_ERROR: int = -32700
INVALID_REQUEST: int = -32600
METHOD_NOT_FOUND: int = -32601
INVALID_PARAMS: int = -32602
INTERNAL_ERROR: int = -32603

# 复习计划允许的天数区间
MIN_PLAN_DAYS: int = 1
MAX_PLAN_DAYS: int = 60

# search_materials 的默认 / 最大返回条数
DEFAULT_SEARCH_LIMIT: int = 20
MAX_SEARCH_LIMIT: int = 200

# get_material_text 回落到磁盘抽取时最多读多少字符
MATERIAL_TEXT_CHARS: int = 6000

# 复习顺序：先讲义再练习，笔记随后，测评类排在最后
# ⚠️ 必须与 study/notebook.py 的 _KIND_ORDER 和 skills/moodle-revision/SKILL.md
#    保持一致，否则同一门课经 MCP 工具和经笔记本得到的复习顺序会对不上
_KIND_ORDER: tuple[str, ...] = (
    "lecture", "tutorial", "lab", "workshop", "notes", "assignment", "exam", "other",
)


__all__ = [
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "PROTOCOL_VERSION",
    "SERVER_NAME",
    "TOOLS",
    "McpError",
    "empty_index",
    "handle_request",
    "load_server_index",
    "serve",
]


class McpError(Exception):
    """MCP 处理过程中的可预期错误，携带 JSON-RPC 错误码"""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ─── 工具定义 ───────────────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_courses",
        "description": (
            "List every course found in the local Moodle material index, "
            "with material counts and a breakdown by material kind."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "search_materials",
        "description": (
            "Search downloaded course materials by keyword. Matches file names, "
            "course names and extracted document text."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search for, e.g. 'quantum' or 'week 3'.",
                },
                "course": {
                    "type": "string",
                    "description": "Optional course name to restrict the search to.",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Maximum results to return (default {DEFAULT_SEARCH_LIMIT}).",
                    "minimum": 1,
                    "maximum": MAX_SEARCH_LIMIT,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_material_text",
        "description": (
            "Return the extracted text of one material. Accepts the absolute path, "
            "the course-relative path or the file name as shown by the other tools."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path, relative path or file name of the material.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "course_overview",
        "description": (
            "Summarise one course: material count, kind breakdown and every "
            "material grouped by teaching week."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "course": {
                    "type": "string",
                    "description": "Course name as reported by list_courses.",
                },
            },
            "required": ["course"],
        },
    },
    {
        "name": "revision_plan",
        "description": (
            "Spread a course's materials over N days of revision, ordered by "
            "teaching week and material kind."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "course": {
                    "type": "string",
                    "description": "Course name as reported by list_courses.",
                },
                "days": {
                    "type": "integer",
                    "description": "Number of revision days (default 7).",
                    "minimum": MIN_PLAN_DAYS,
                    "maximum": MAX_PLAN_DAYS,
                },
            },
            "required": ["course"],
        },
    },
]


# ─── 协议入口 ───────────────────────────────────────────────

def handle_request(request: dict, index: CourseIndex) -> dict | None:
    """
    处理单条 JSON-RPC 请求（纯函数，不做任何 I/O）

    :param request: 已解析的 JSON-RPC 请求对象
    :param index: 供工具查询的课件索引
    :returns: 响应字典；通知（无 id / notifications/* 方法）返回 None
    """
    if not isinstance(request, dict):
        return _error(None, INVALID_REQUEST, "Request must be a JSON object")

    method = request.get("method")
    req_id = request.get("id")
    is_notification = "id" not in request or req_id is None

    if not isinstance(method, str) or not method:
        if is_notification:
            return None
        return _error(req_id, INVALID_REQUEST, "Missing or invalid 'method'")

    # 通知不需要（也不允许）回包
    if is_notification or method.startswith("notifications/"):
        return None

    params = request.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _error(req_id, INVALID_PARAMS, "'params' must be an object")

    try:
        if method == "initialize":
            result: dict[str, Any] = _initialize_result()
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": copy.deepcopy(TOOLS)}
        elif method == "tools/call":
            result = _call_tool(params, index)
        else:
            return _error(req_id, METHOD_NOT_FOUND, f"Unknown method: {method}")
    except McpError as exc:
        return _error(req_id, exc.code, exc.message)
    except Exception as exc:  # 兜底：任何意外都变成 JSON-RPC 错误，不炸服务
        return _error(req_id, INTERNAL_ERROR, f"Internal error: {exc}")

    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result}


def serve(
    index_path: str | Path | None = None,
    root: str | Path | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> None:
    """
    以 stdio 方式跑 MCP 服务：逐行读请求，逐行写响应

    单行畸形输入会被跳过而不是终止循环；任何异常都不会逃出本函数。

    :param index_path: 已有索引 JSON 的路径（优先使用）
    :param root: 课件根目录；index_path 缺失或损坏时现场扫描
    :param stdin: 输入流，默认 sys.stdin（测试可注入 StringIO）
    :param stdout: 输出流，默认 sys.stdout（测试可注入 StringIO）
    """
    in_stream = stdin if stdin is not None else sys.stdin
    out_stream = stdout if stdout is not None else sys.stdout

    try:
        index = load_server_index(index_path, root)
    except Exception:
        index = empty_index(root)

    try:
        for line in in_stream:
            text = (line or "").strip()
            if not text:
                continue

            try:
                request = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                continue  # 畸形行直接跳过
            if not isinstance(request, dict):
                continue  # 批量请求 / 非对象一律忽略

            try:
                response = handle_request(request, index)
            except Exception as exc:  # handle_request 已兜底，这里再兜一层
                response = _error(request.get("id"), INTERNAL_ERROR, f"Internal error: {exc}")

            if response is not None:
                _write_message(out_stream, response)
    except (KeyboardInterrupt, EOFError):
        return
    except Exception:
        return  # 读流本身坏了就安静退出，绝不向 stdout 吐非协议内容


def load_server_index(
    index_path: str | Path | None = None,
    root: str | Path | None = None,
) -> CourseIndex:
    """
    解析出一个可用索引：index_path → root → 当前目录

    :param index_path: 索引 JSON 路径，读不出来时静默回落
    :param root: 课件根目录，给定时现场 build_index()
    :returns: CourseIndex（什么都找不到时是空索引）
    """
    if index_path:
        loaded = load_index(index_path)
        if loaded is not None:
            return loaded

    if root:
        return build_index(root)

    # 都没给：先看当前目录有没有现成索引，再退化成扫当前目录
    cwd = Path.cwd()
    loaded = load_index(cwd / INDEX_FILENAME)
    if loaded is not None:
        return loaded
    return build_index(cwd)


def empty_index(root: str | Path | None = None) -> CourseIndex:
    """
    构造一个空索引（索引不可用时的兜底）

    :param root: 记录在索引里的根目录
    :returns: courses 为空的 CourseIndex
    """
    return CourseIndex(
        root=str(root) if root else str(Path.cwd()),
        generated_at=datetime.now(timezone.utc).isoformat(),
        courses={},
    )


# ─── 方法实现 ───────────────────────────────────────────────

def _initialize_result() -> dict[str, Any]:
    """initialize 的握手响应"""
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": __version__},
    }


def _call_tool(params: dict, index: CourseIndex) -> dict[str, Any]:
    """分发 tools/call；未知工具按 MCP 约定报 -32602"""
    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise McpError(INVALID_PARAMS, "Missing tool name")

    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise McpError(INVALID_PARAMS, "'arguments' must be an object")

    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        raise McpError(INVALID_PARAMS, f"Unknown tool: {name}")
    return handler(arguments, index)


# ─── 工具实现 ───────────────────────────────────────────────

def _tool_list_courses(arguments: dict, index: CourseIndex) -> dict[str, Any]:
    """列出所有课程 + 材料数 + 类型分布"""
    names = index.course_names()
    if not names:
        return _text_result(
            "No courses indexed yet. Download materials first, or start the "
            "server with a materials folder (--root)."
        )

    total = len(index.all_materials())
    lines = [f"{len(names)} course(s), {total} material(s) — root: {index.root}", ""]

    for name in names:
        materials = index.courses.get(name, [])
        parts = [f"- {name} — {len(materials)} material(s)"]
        kinds = _kind_breakdown(materials)
        if kinds:
            parts.append(f"kinds: {kinds}")
        weeks = _week_span(materials)
        if weeks:
            parts.append(f"weeks: {weeks}")
        lines.append(" | ".join(parts))

    return _text_result("\n".join(lines))


def _tool_search_materials(arguments: dict, index: CourseIndex) -> dict[str, Any]:
    """按关键词搜索材料"""
    query = _str_arg(arguments, "query", required=True)
    raw_course = _str_arg(arguments, "course")
    limit = _int_arg(arguments, "limit", default=DEFAULT_SEARCH_LIMIT)
    limit = max(1, min(limit, MAX_SEARCH_LIMIT))

    course: str | None = None
    if raw_course:
        course = _resolve_course(index, raw_course)
        if course is None:
            return _unknown_course_result(index, raw_course)

    results = index.search(query, course=course, limit=limit)
    scope = f"course '{course}'" if course else "all courses"
    if not results:
        return _text_result(f"No material matched '{query}' in {scope}.")

    lines = [f"{len(results)} result(s) for '{query}' in {scope}:", ""]
    lines.extend(_material_lines(results, numbered=True, with_path=True))
    return _text_result("\n".join(lines))


def _tool_get_material_text(arguments: dict, index: CourseIndex) -> dict[str, Any]:
    """返回某份材料的提取文本"""
    path = _str_arg(arguments, "path", required=True)
    material = _find_material(index, path)
    if material is None:
        return _text_result(
            f"No indexed material matches '{path}'. "
            "Use search_materials or course_overview to get a valid path.",
            is_error=True,
        )

    header = (
        f"{material.course} / {material.rel_path}\n"
        f"kind: {material.kind} | week: {_week_label(material.week)} | "
        f"size: {_format_size(material.size)}\n"
        f"path: {material.path}"
    )

    text = material.text or extract_pdf_text(material.path, MATERIAL_TEXT_CHARS)
    if not text.strip():
        return _text_result(
            f"{header}\n\n"
            "No text available for this material. Text extraction only works for "
            ".txt/.md/.csv files and for PDFs when 'pypdf' or 'pdfminer.six' is "
            "installed; scanned or image-only PDFs yield nothing either."
        )

    return _text_result(f"{header}\n\n--- text ---\n{text}")


def _tool_course_overview(arguments: dict, index: CourseIndex) -> dict[str, Any]:
    """按周次 / 类型组织的课程总览"""
    raw_course = _str_arg(arguments, "course", required=True)
    course = _resolve_course(index, raw_course)
    if course is None:
        return _unknown_course_result(index, raw_course)

    materials = index.courses.get(course, [])
    if not materials:
        return _text_result(f"Course '{course}' has no indexed materials.")

    total_size = sum(m.size for m in materials)
    lines = [
        f"{course} — {len(materials)} material(s), {_format_size(total_size)}",
        f"kinds: {_kind_breakdown(materials) or 'n/a'}",
    ]
    weeks = _week_span(materials)
    if weeks:
        lines.append(f"weeks: {weeks}")

    for week, group in _group_by_week(materials):
        lines.append("")
        lines.append(f"## {_week_heading(week)} ({len(group)})")
        lines.extend(_material_lines(group))

    return _text_result("\n".join(lines))


def _tool_revision_plan(arguments: dict, index: CourseIndex) -> dict[str, Any]:
    """把课程材料摊到 N 天的复习计划里"""
    raw_course = _str_arg(arguments, "course", required=True)
    course = _resolve_course(index, raw_course)
    if course is None:
        return _unknown_course_result(index, raw_course)

    days = _int_arg(arguments, "days", default=7)
    if days < MIN_PLAN_DAYS or days > MAX_PLAN_DAYS:
        raise McpError(
            INVALID_PARAMS,
            f"'days' must be between {MIN_PLAN_DAYS} and {MAX_PLAN_DAYS}",
        )

    materials = index.courses.get(course, [])
    if not materials:
        return _text_result(f"Course '{course}' has no indexed materials to plan.")

    ordered = sorted(materials, key=_revision_sort_key)
    buckets = _split_evenly(ordered, days)

    lines = [
        f"Revision plan — {course}: {len(ordered)} material(s) over {days} day(s)",
    ]
    for number, bucket in enumerate(buckets, start=1):
        lines.append("")
        if not bucket:
            lines.append(f"## Day {number} — buffer / catch-up (no material assigned)")
            continue
        weeks = _week_span(bucket)
        heading = f"## Day {number} ({len(bucket)})"
        if weeks:
            heading += f" — weeks {weeks}"
        lines.append(heading)
        lines.extend(_material_lines(bucket))

    return _text_result("\n".join(lines))


_TOOL_HANDLERS: dict[str, Callable[[dict, CourseIndex], dict[str, Any]]] = {
    "list_courses": _tool_list_courses,
    "search_materials": _tool_search_materials,
    "get_material_text": _tool_get_material_text,
    "course_overview": _tool_course_overview,
    "revision_plan": _tool_revision_plan,
}


# ─── 内部函数：响应构造 ─────────────────────────────────────

def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    """构造 JSON-RPC 错误响应"""
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    """构造 MCP 工具结果（content 数组形式）"""
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["isError"] = True
    return result


def _unknown_course_result(index: CourseIndex, requested: str) -> dict[str, Any]:
    """课程名对不上时，回一个带可选课程清单的工具错误"""
    names = index.course_names()
    available = ", ".join(names) if names else "(none indexed)"
    return _text_result(
        f"Unknown course '{requested}'. Available courses: {available}",
        is_error=True,
    )


def _write_message(stream: TextIO, message: dict[str, Any]) -> None:
    """把一条响应写成单行 JSON

    用 ensure_ascii=True：Windows 控制台编码未必是 UTF-8，
    全 ASCII 转义可以保证中文课程名在任何终端下都不会写崩。
    """
    stream.write(json.dumps(message, ensure_ascii=True) + "\n")
    flush = getattr(stream, "flush", None)
    if callable(flush):
        flush()


# ─── 内部函数：参数解析 ─────────────────────────────────────

def _str_arg(arguments: dict, key: str, *, required: bool = False) -> str:
    """取字符串参数；required 时缺失/空串报 -32602"""
    value = arguments.get(key)
    if value is None:
        if required:
            raise McpError(INVALID_PARAMS, f"Missing required argument '{key}'")
        return ""
    if not isinstance(value, str):
        raise McpError(INVALID_PARAMS, f"Argument '{key}' must be a string")
    value = value.strip()
    if required and not value:
        raise McpError(INVALID_PARAMS, f"Argument '{key}' must not be empty")
    return value


def _int_arg(arguments: dict, key: str, *, default: int) -> int:
    """取整数参数；数字字符串也接受，其余报 -32602"""
    value = arguments.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        raise McpError(INVALID_PARAMS, f"Argument '{key}' must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            raise McpError(INVALID_PARAMS, f"Argument '{key}' must be an integer") from None
    raise McpError(INVALID_PARAMS, f"Argument '{key}' must be an integer")


# ─── 内部函数：索引查询 ─────────────────────────────────────

def _resolve_course(index: CourseIndex, requested: str) -> str | None:
    """
    宽松地把用户给的课程名对到索引里的真实课程名

    依次尝试：精确 → 忽略大小写 → 唯一子串匹配。
    """
    names = index.course_names()
    if not names or not requested:
        return None

    if requested in index.courses:
        return requested

    needle = requested.strip().lower()
    for name in names:
        if name.lower() == needle:
            return name

    partial = [name for name in names if needle in name.lower()]
    if len(partial) == 1:
        return partial[0]
    return None


def _find_material(index: CourseIndex, path: str) -> Material | None:
    """按绝对路径 → 相对路径 → 路径后缀 → 文件名 依次匹配一份材料"""
    needle = _normalize_path(path)
    if not needle:
        return None

    items = index.all_materials()

    for item in items:
        if _normalize_path(item.path) == needle:
            return item
    for item in items:
        if _normalize_path(item.rel_path) == needle:
            return item
    for item in items:
        if (_normalize_path(item.path).endswith("/" + needle)
                or _normalize_path(item.rel_path).endswith("/" + needle)):
            return item

    stem = Path(needle).stem
    for item in items:
        if item.name.lower() == stem:
            return item
    return None


def _normalize_path(path: str) -> str:
    """统一分隔符 + 小写，便于跨平台比较"""
    return str(path or "").strip().replace("\\", "/").rstrip("/").lower()


def _group_by_week(materials: list[Material]) -> list[tuple[int | None, list[Material]]]:
    """按周次分组；无周次的一组排在最后"""
    grouped: dict[int | None, list[Material]] = {}
    for item in materials:
        grouped.setdefault(item.week, []).append(item)

    known = sorted((w for w in grouped if w is not None))
    groups: list[tuple[int | None, list[Material]]] = [
        (week, sorted(grouped[week], key=_revision_sort_key)) for week in known
    ]
    if None in grouped:
        groups.append((None, sorted(grouped[None], key=_revision_sort_key)))
    return groups


def _split_evenly(items: list[Material], buckets: int) -> list[list[Material]]:
    """把有序材料尽量平均切成 buckets 份（前面的份额多 1）"""
    if buckets <= 0:
        return [list(items)]

    base, extra = divmod(len(items), buckets)
    result: list[list[Material]] = []
    cursor = 0
    for i in range(buckets):
        size = base + (1 if i < extra else 0)
        result.append(items[cursor:cursor + size])
        cursor += size
    return result


def _revision_sort_key(material: Material) -> tuple[int, int, int, str]:
    """复习顺序：有周次的按周次在前，其次按类型优先级，最后按路径"""
    week_missing = 1 if material.week is None else 0
    week = material.week if material.week is not None else 0
    try:
        kind_rank = _KIND_ORDER.index(material.kind)
    except ValueError:
        kind_rank = len(_KIND_ORDER)
    return (week_missing, week, kind_rank, material.rel_path.lower())


# ─── 内部函数：文本渲染 ─────────────────────────────────────

def _material_lines(
    materials: list[Material],
    *,
    numbered: bool = False,
    with_path: bool = False,
) -> list[str]:
    """把材料渲染成清单行"""
    lines: list[str] = []
    for number, item in enumerate(materials, start=1):
        bullet = f"{number}." if numbered else "-"
        lines.append(
            f"{bullet} [{item.kind}] {item.course} / {item.rel_path} "
            f"(week {_week_label(item.week)}, {_format_size(item.size)})"
        )
        if with_path:
            lines.append(f"   path: {item.path}")
    return lines


def _kind_breakdown(materials: list[Material]) -> str:
    """类型分布，如 'lecture 3, lab 1'"""
    counter = Counter(item.kind or "other" for item in materials)
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{kind} {count}" for kind, count in ordered)


def _week_span(materials: list[Material]) -> str:
    """周次跨度，如 '1-5'、'3'；全无周次时返回空串"""
    weeks = sorted({item.week for item in materials if item.week is not None})
    if not weeks:
        return ""
    if len(weeks) == 1:
        return str(weeks[0])
    return f"{weeks[0]}-{weeks[-1]}"


def _week_label(week: int | None) -> str:
    """周次的短标签"""
    return str(week) if week is not None else "n/a"


def _week_heading(week: int | None) -> str:
    """分组标题"""
    return f"Week {week}" if week is not None else "No week detected"


def _format_size(size: int) -> str:
    """人类可读的体积"""
    value = float(max(int(size or 0), 0))
    if value < 1024:
        return f"{int(value)} B"
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} GB"


# ─── 命令行入口 ─────────────────────────────────────────────

def _parse_argv(argv: list[str]) -> tuple[str | None, str | None]:
    """
    解析 `--index PATH` / `--root PATH`（沿用项目不用 argparse 的习惯）

    :param argv: 不含程序名的参数列表
    :returns: (index_path, root)，未给出为 None
    """
    index_path: str | None = None
    root: str | None = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if arg in ("--index", "--index-path") and nxt:
            index_path = nxt
            i += 2
        elif arg == "--root" and nxt:
            root = nxt
            i += 2
        else:
            i += 1

    return index_path, root


if __name__ == "__main__":  # pragma: no cover
    _cli_index, _cli_root = _parse_argv(sys.argv[1:])
    serve(index_path=_cli_index, root=_cli_root)
