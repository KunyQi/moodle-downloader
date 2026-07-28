"""
study — 复习计划核心

复习顺序与排期的**唯一事实源**：MCP 服务（mcp_server.revision_plan）和
复习笔记本（study.notebook）都从这里取，避免同一门课经两条路径得到不同结果。

⚠️ 免责声明: 本工具仅供学生处理本人已注册课程的课件。
Disclaimer: For students to process their own course materials only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .index import CourseIndex, Material

# 默认复习周期天数
DEFAULT_DAYS: int = 7

# 天数上下界（防止 1 天 5000 份或负数这类离谱输入）
MIN_DAYS: int = 1
MAX_DAYS: int = 60

# 间隔重复：第 d 天回顾第 d-1 / d-3 / d-7 天学过的材料
REVIEW_INTERVALS: tuple[int, ...] = (1, 3, 7)

# 复习顺序：先讲义再练习，笔记随后，测评类排在最后
# 改这里就够了——MCP 与笔记本都读它，不需要再同步别处
KIND_ORDER: tuple[str, ...] = (
    "lecture", "tutorial", "lab", "workshop", "notes", "assignment", "exam", "other",
)


@dataclass
class DayPlan:
    """一天的复习安排"""
    day: int                                                  # 第几天，从 1 开始
    materials: list[Material] = field(default_factory=list)   # 当天新学
    reviews: list[Material] = field(default_factory=list)     # 当天回顾（间隔重复）


def clamp_days(days: int) -> int:
    """把天数夹到 MIN_DAYS..MAX_DAYS，非法输入回落到默认值"""
    try:
        value = int(days)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    if value < MIN_DAYS:
        return MIN_DAYS
    return min(value, MAX_DAYS)


def kind_rank(kind: str) -> int:
    """类型在 KIND_ORDER 里的位置，未知类型排最后"""
    try:
        return KIND_ORDER.index(kind)
    except ValueError:
        return len(KIND_ORDER)


def revision_sort_key(material: Material) -> tuple:
    """复习顺序：有周次的按周次在前，同周内按类型优先级，再按课程与路径"""
    week = material.week
    return (
        week is None,
        week if week is not None else 0,
        kind_rank(material.kind),
        material.course.lower(),
        material.rel_path.lower(),
    )


def select_materials(index: CourseIndex, course: str | None = None) -> list[Material]:
    """挑出目标课程的材料并按复习顺序排序（course=None 表示全部课程）"""
    items = index.all_materials()

    target = course.strip().lower() if course and course.strip() else None
    if target is not None:
        items = [m for m in items if m.course.lower() == target]

    return sorted(items, key=revision_sort_key)


def split_evenly(items: list[Material], buckets: int) -> list[list[Material]]:
    """把材料尽量均匀地切成 buckets 份，前面的份额多拿一个"""
    count = max(1, buckets)
    base, extra = divmod(len(items), count)
    result: list[list[Material]] = []
    cursor = 0
    for i in range(count):
        take = base + (1 if i < extra else 0)
        result.append(items[cursor:cursor + take])
        cursor += take
    return result


def build_plan(
    index: CourseIndex,
    *,
    course: str | None = None,
    days: int = DEFAULT_DAYS,
) -> list[DayPlan]:
    """
    把材料摊到若干天里，并按 1/3/7 天间隔安排回顾

    材料先按周次排序（未标注周次的排在最后），再尽量均匀地分配到每一天；
    材料少于天数时，靠后的日子只剩回顾任务。

    :param index: 课件索引
    :param course: 只针对某一门课程（不区分大小写的精确匹配），None 表示全部
    :param days: 复习周期天数，会被夹到 MIN_DAYS..MAX_DAYS
    :returns: 长度等于天数的 DayPlan 列表
    """
    day_count = clamp_days(days)
    materials = select_materials(index, course)

    plans = [DayPlan(day=i + 1) for i in range(day_count)]
    for plan, bucket in zip(plans, split_evenly(materials, day_count)):
        plan.materials = bucket

    # 间隔重复：第 d 天回顾第 d-1 / d-3 / d-7 天学过的东西
    for plan in plans:
        seen: set[str] = set()
        for interval in REVIEW_INTERVALS:
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
