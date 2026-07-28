"""
study.notebook — 复习笔记本生成器

把本地课件索引变成一本可以直接用 Jupyter 打开的复习笔记本。
.ipynb 本身就是一段 JSON，所以这里手写 nbformat 4 结构即可，
不需要 nbformat / jupyter 之类的额外依赖。

笔记本包含五个单元格：标题与课程概览、载入索引的代码、每日复习计划表、
纯标准库的文字版进度图表、逐份材料的自测清单。

生成结果是确定性的：时间戳取自 ``index.generated_at``，
同一份索引重复生成得到完全相同的文件，方便做 diff 与缓存。

本模块不产生任何用户可见输出（不 print、不 input），
只返回字典 / 写入路径，由调用方负责展示。

⚠️ 免责声明: 本工具仅供学生处理本人已注册课程的课件。
Disclaimer: For students to process their own course materials only.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .index import CourseIndex, Material


# nbformat 版本（4.5 起每个 cell 必须带 id）
NBFORMAT: int = 4
NBFORMAT_MINOR: int = 5

# 默认复习周期（天）
DEFAULT_DAYS: int = 7

# 复习周期上限，避免生成几百个空白天
_MAX_DAYS: int = 60

# 自测区最多列出多少份材料，超出部分只给出提示
_MAX_QUIZ_ITEMS: int = 200

# 计划表里每天最多显示几条，超出折叠成"共 N 份"
_MAX_ROW_ITEMS: int = 8

# 间隔重复的回顾间隔（天）：第 d 天回顾第 d-1 / d-3 / d-7 天学过的材料
_REVIEW_INTERVALS: tuple[int, ...] = (1, 3, 7)

# 材料类型的中文标签
_KIND_LABELS: dict[str, str] = {
    "lecture": "讲义",
    "tutorial": "习题课",
    "lab": "实验",
    "workshop": "研讨",
    "notes": "笔记",
    "assignment": "作业",
    "exam": "考试",
    "other": "其他",
}

# 排序时的类型优先级（先讲义后作业考试，符合复习顺序）
# ⚠️ 必须与 mcp_server.py 的 _KIND_ORDER 和 skills/moodle-revision/SKILL.md 保持一致
_KIND_ORDER: tuple[str, ...] = (
    "lecture", "tutorial", "lab", "workshop",
    "notes", "assignment", "exam", "other",
)

# 按类型给出的空白回忆提示
_RECALL_PROMPTS: dict[str, str] = {
    "lecture": "不看讲义，说出这一讲的 3 个关键词以及它们之间的关系",
    "tutorial": "挑一道题，从头到尾口述完整解法",
    "lab": "复述实验步骤，并指出最容易出错的一步",
    "workshop": "用自己的话概括这次研讨得到的结论",
    "notes": "把这份笔记压缩成 3 句话",
    "assignment": "题目要求是什么？评分点落在哪里？",
    "exam": "限时重做一遍，记下卡住的位置",
    "other": "这份材料想解决的是什么问题？",
}

_FALLBACK_PROMPT: str = "先合上材料，说出你还记得的全部要点"


@dataclass
class DayPlan:
    """一天的复习安排"""
    day: int                                        # 第几天，从 1 开始
    materials: list[Material] = field(default_factory=list)   # 当天新学
    reviews: list[Material] = field(default_factory=list)     # 当天回顾（间隔重复）


def notebook_dict(
    index: CourseIndex,
    *,
    course: str | None = None,
    days: int = DEFAULT_DAYS,
) -> dict:
    """
    构造 nbformat 4 结构的笔记本字典

    :param index: 课件索引
    :param course: 只针对某一门课程（不区分大小写的精确匹配），None 表示全部
    :param days: 复习周期天数，会被夹到 1..60
    :returns: 可直接 json.dumps 的字典
    """
    day_count = _clamp_days(days)
    materials = _select_materials(index, course)
    plans = build_plan(index, course=course, days=day_count)

    cells = [
        _markdown_cell(_header_lines(index, materials, course, day_count), "cell-header"),
        _code_cell(_load_lines(index, course), "cell-load"),
        _markdown_cell(_plan_lines(plans, day_count), "cell-plan"),
        _code_cell(_progress_lines(), "cell-progress"),
        _markdown_cell(_quiz_lines(materials), "cell-quiz"),
    ]

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "codemirror_mode": {"name": "ipython", "version": 3},
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "nbconvert_exporter": "python",
                "pygments_lexer": "ipython3",
            },
            "moodle_scraper": {
                "course": course or "",
                "days": day_count,
                "generated_at": index.generated_at,
                "material_count": len(materials),
            },
        },
        "nbformat": NBFORMAT,
        "nbformat_minor": NBFORMAT_MINOR,
    }


def build_revision_notebook(
    index: CourseIndex,
    out_path: str | Path,
    *,
    course: str | None = None,
    days: int = DEFAULT_DAYS,
) -> str:
    """
    生成复习笔记本并写入磁盘（先写 .part 再原子替换）

    :param index: 课件索引
    :param out_path: 目标 .ipynb 路径，父目录不存在会自动创建
    :param course: 只针对某一门课程，None 表示全部
    :param days: 复习周期天数
    :returns: 实际写入的路径
    """
    target = Path(out_path).expanduser()
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(
        notebook_dict(index, course=course, days=days),
        ensure_ascii=False,
        indent=1,
    )
    part = target.with_name(target.name + ".part")
    part.write_text(payload, encoding="utf-8")
    os.replace(str(part), str(target))
    return str(target)


def build_plan(
    index: CourseIndex,
    *,
    course: str | None = None,
    days: int = DEFAULT_DAYS,
) -> list[DayPlan]:
    """
    把材料摊到若干天里，并按 1/3/7 天间隔安排回顾

    材料先按周次排序（未标注周次的排在最后），再尽量均匀地分配到每一天，
    材料少于天数时后面的日子只有回顾任务。

    :param index: 课件索引
    :param course: 只针对某一门课程，None 表示全部
    :param days: 复习周期天数，会被夹到 1..60
    :returns: 长度等于天数的 DayPlan 列表
    """
    day_count = _clamp_days(days)
    materials = _select_materials(index, course)

    plans = [DayPlan(day=i + 1) for i in range(day_count)]

    # 均匀切块：前 extra 天各多拿一份
    base, extra = divmod(len(materials), day_count)
    cursor = 0
    for i, plan in enumerate(plans):
        take = base + (1 if i < extra else 0)
        plan.materials = materials[cursor:cursor + take]
        cursor += take

    # 间隔重复：第 d 天回顾第 d-1 / d-3 / d-7 天学过的东西
    for plan in plans:
        seen: set[str] = set()
        for interval in _REVIEW_INTERVALS:
            source = plan.day - interval
            if source < 1:
                continue
            for material in plans[source - 1].materials:
                key = material.path or material.rel_path
                if key in seen:
                    continue
                seen.add(key)
                plan.reviews.append(material)

    return plans


# ─── 内部函数：数据整理 ──────────────────────────────────────

def _clamp_days(days: int) -> int:
    """把天数夹到 1.._MAX_DAYS，非法输入回落到默认值"""
    try:
        value = int(days)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    if value < 1:
        return 1
    return min(value, _MAX_DAYS)


def _select_materials(index: CourseIndex, course: str | None) -> list[Material]:
    """挑出目标课程的材料并按复习顺序排序"""
    items = index.all_materials()

    target = course.strip().lower() if course and course.strip() else None
    if target is not None:
        items = [m for m in items if m.course.lower() == target]

    return sorted(items, key=_sort_key)


def _sort_key(material: Material) -> tuple:
    """复习顺序：有周次的按周次在前，同周内按类型优先级，再按路径"""
    week = material.week
    return (
        week is None,
        week if week is not None else 0,
        _kind_rank(material.kind),
        material.course.lower(),
        material.rel_path.lower(),
    )


def _kind_rank(kind: str) -> int:
    """类型在 _KIND_ORDER 里的位置，未知类型排最后"""
    try:
        return _KIND_ORDER.index(kind)
    except ValueError:
        return len(_KIND_ORDER)


def _kind_label(kind: str) -> str:
    """类型的中文标签，未知类型原样返回"""
    return _KIND_LABELS.get(kind, kind or "其他")


def _week_label(week: int | None) -> str:
    """周次标签"""
    return f"Week {week}" if week is not None else "未标注周次"


def _format_time(raw: str) -> str:
    """把 ISO 8601 时间串格式化成 YYYY-MM-DD HH:MM，解析不了就原样返回"""
    if not raw:
        return "未知"
    try:
        return datetime.fromisoformat(raw).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return raw


def _escape_cell(text: str) -> str:
    """转义 markdown 表格单元格里的竖线与换行"""
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def _py_literal(value: str | None) -> str:
    """把字符串转成合法的 Python 字面量（JSON 字符串语法在这里与 Python 兼容）"""
    if value is None:
        return "None"
    return json.dumps(value, ensure_ascii=False)


# ─── 内部函数：单元格构造 ────────────────────────────────────

def _ensure_newlines(lines: list[str]) -> list[str]:
    """按 nbformat 惯例，让每一行都以 \\n 结尾"""
    return [line if line.endswith("\n") else line + "\n" for line in lines]


def _markdown_cell(lines: list[str], cell_id: str) -> dict:
    """构造一个 markdown 单元格"""
    return {
        "cell_type": "markdown",
        "id": cell_id,
        "metadata": {},
        "source": _ensure_newlines(lines),
    }


def _code_cell(lines: list[str], cell_id: str) -> dict:
    """构造一个代码单元格（未执行状态）"""
    return {
        "cell_type": "code",
        "execution_count": None,
        "id": cell_id,
        "metadata": {},
        "outputs": [],
        "source": _ensure_newlines(lines),
    }


# ─── 内部函数：各单元格内容 ──────────────────────────────────

def _header_lines(
    index: CourseIndex,
    materials: list[Material],
    course: str | None,
    days: int,
) -> list[str]:
    """标题 + 生成时间 + 课程概览表"""
    scope = course.strip() if course and course.strip() else "全部课程"
    course_names = sorted(
        {m.course for m in materials},
        key=lambda n: n.lower(),
    )

    lines = [
        "# 📚 复习笔记本",
        "",
        f"- 复习范围：**{scope}**",
        f"- 索引生成时间：{_format_time(index.generated_at)}",
        f"- 课件根目录：`{index.root}`",
        f"- 复习周期：{days} 天",
        f"- 材料总数：{len(materials)} 份，覆盖 {len(course_names)} 门课程",
        "",
        "## 课程概览",
        "",
    ]

    if not materials:
        lines.append("> 索引里没有匹配的材料。先运行下载器把课件抓下来，再重建索引。")
        lines.append("")
        return lines

    lines.append("| 课程 | 材料数 | 周次跨度 | 主要类型 |")
    lines.append("| --- | ---: | --- | --- |")
    for name in course_names:
        items = [m for m in materials if m.course == name]
        lines.append(
            "| {course} | {count} | {weeks} | {kinds} |".format(
                course=_escape_cell(name),
                count=len(items),
                weeks=_week_span(items),
                kinds=_kind_summary(items),
            )
        )
    lines.append("")
    return lines


def _week_span(materials: list[Material]) -> str:
    """材料覆盖的周次范围，例如 Week 1-5"""
    weeks = sorted({m.week for m in materials if m.week is not None})
    if not weeks:
        return "—"
    if len(weeks) == 1:
        return f"Week {weeks[0]}"
    return f"Week {weeks[0]}-{weeks[-1]}"


def _kind_summary(materials: list[Material]) -> str:
    """出现最多的两种类型，例如 讲义 ×6 / 实验 ×4"""
    counter = Counter(m.kind for m in materials)
    parts = [f"{_kind_label(kind)} ×{count}" for kind, count in counter.most_common(2)]
    return _escape_cell(" / ".join(parts)) if parts else "—"


def _load_lines(index: CourseIndex, course: str | None) -> list[str]:
    """载入索引的代码单元格"""
    return [
        "# 载入本地课件索引：优先读缓存，读不到就现场扫描一次",
        "from pathlib import Path",
        "",
        "from moodle_scraper.study.index import INDEX_FILENAME, build_index, load_index",
        "",
        f"ROOT = {_py_literal(index.root)}",
        f"COURSE = {_py_literal(course)}   # 改成课程名可只看一门课",
        "",
        "index = load_index(Path(ROOT) / INDEX_FILENAME)",
        "if index is None:",
        "    index = build_index(ROOT)",
        "",
        "materials = [",
        "    m for m in index.all_materials()",
        "    if COURSE is None or m.course.lower() == COURSE.lower()",
        "]",
        "",
        'print(f"课程 {len(index.course_names())} 门 / 本次复习材料 {len(materials)} 份")',
    ]


def _plan_lines(plans: list[DayPlan], days: int) -> list[str]:
    """每日复习计划表"""
    lines = [
        f"## 🗓️ 每日复习计划（{days} 天）",
        "",
        "材料先按周次排序，再尽量均匀地摊到每一天；"
        "「回顾」列按 1 / 3 / 7 天的间隔重复，"
        "只需扫一眼标题能不能立刻想起内容即可。",
        "",
        "| 天 | 新学 | 回顾 |",
        "| --- | --- | --- |",
    ]

    for plan in plans:
        lines.append(
            "| 第 {day} 天 | {new} | {review} |".format(
                day=plan.day,
                new=_row_items(plan.materials, with_kind=True),
                review=_row_items(plan.reviews, with_kind=False),
            )
        )

    lines.append("")
    lines.append("> 勾不完也没关系——先保证「回顾」列过一遍，那是防遗忘的部分。")
    lines.append("")
    return lines


def _row_items(materials: list[Material], *, with_kind: bool) -> str:
    """把一天的材料压成一个表格单元格，超长时折叠"""
    if not materials:
        return "—"

    shown = materials[:_MAX_ROW_ITEMS]
    parts: list[str] = []
    for material in shown:
        label = _escape_cell(material.name) or _escape_cell(material.rel_path)
        if with_kind:
            parts.append(f"{label}（{_kind_label(material.kind)} · {_week_label(material.week)}）")
        else:
            parts.append(label)

    text = "<br>".join(parts)
    rest = len(materials) - len(shown)
    if rest > 0:
        text += f"<br>…… 另有 {rest} 份"
    return text


def _progress_lines() -> list[str]:
    """文字版进度图表的代码单元格（纯标准库）"""
    return [
        "# 文字版进度图表：只用标准库，不需要 matplotlib",
        "from collections import Counter",
        "",
        "# 复习完一份就把它的文件名加进来，然后重跑本单元格",
        "DONE: set[str] = set()",
        "",
        "",
        "def bar(value: int, total: int, width: int = 28) -> str:",
        '    """把比例画成 ██████░░░ 形式的文字条"""',
        "    if total <= 0:",
        '        return "░" * width',
        "    filled = round(width * value / total)",
        '    return "█" * filled + "░" * (width - filled)',
        "",
        "",
        "total = len(materials)",
        "",
        'print("按类型分布")',
        "for kind, count in Counter(m.kind for m in materials).most_common():",
        '    print(f"  {kind:<11}{bar(count, total)} {count:>3}")',
        "",
        "weeks = Counter(m.week for m in materials if m.week is not None)",
        "if weeks:",
        '    print("\\n按周次分布")',
        "    for week in sorted(weeks):",
        '        print(f"  Week {week:<6}{bar(weeks[week], total)} {weeks[week]:>3}")',
        "",
        "done = sum(1 for m in materials if m.name in DONE)",
        'print(f"\\n完成度      {bar(done, total)} {done}/{total}")',
    ]


def _group_by_course(materials: list[Material]) -> list[tuple[str, list[Material]]]:
    """
    按课程归组，课程之间按首次出现顺序，组内保持原有的复习顺序

    :param materials: 已按复习顺序排好的材料
    :returns: [(课程名, 该课程的材料), ...]
    """
    groups: dict[str, list[Material]] = {}
    for material in materials:
        groups.setdefault(material.course, []).append(material)
    return list(groups.items())


def _quiz_lines(materials: list[Material]) -> list[str]:
    """自测区：每份材料一个 checkbox + 空白回忆提示"""
    lines = [
        "## 🧠 自测区",
        "",
        "用法：**先合上材料**，照着提示回忆，说得出来再勾选。"
        "勾不掉的那几条就是下一轮复习的重点。",
        "",
    ]

    if not materials:
        lines.append("> 还没有可自测的材料。")
        lines.append("")
        return lines

    # 先截断（保住复习优先级），再按课程归组——materials 是按周次排序的，
    # 直接顺序输出会让同一个课程标题反复出现好几次
    shown = materials[:_MAX_QUIZ_ITEMS]
    for course_name, group in _group_by_course(shown):
        lines.append(f"### {course_name}")
        lines.append("")

        for material in group:
            title = material.name or material.rel_path
            prompt = _RECALL_PROMPTS.get(material.kind, _FALLBACK_PROMPT)
            lines.append(
                f"- [ ] **{title}** · {_kind_label(material.kind)} · {_week_label(material.week)}"
            )
            lines.append(f"  - 空白回忆：{prompt}")
            lines.append("  - 一句话总结：")
            lines.append("")

    rest = len(materials) - len(shown)
    if rest > 0:
        lines.append(f"> 还有 {rest} 份材料未列出（每次最多列 {_MAX_QUIZ_ITEMS} 份），"
                     "缩小课程范围或调大周期后重新生成即可。")
        lines.append("")

    return lines
