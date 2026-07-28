"""
study — 本地学习工具包

在已经下载到磁盘的课件之上，提供索引 / 检索能力，
供 Obsidian 导出器、MCP 服务、复习笔记本等消费。

⚠️ 免责声明: 本工具仅供学生处理本人已注册课程的课件。
Disclaimer: For students to process their own course materials only.
"""
from __future__ import annotations

from .index import (
    INDEX_FILENAME,
    CourseIndex,
    Material,
    build_index,
    detect_kind,
    detect_week,
    extract_pdf_text,
    load_index,
    save_index,
)
from .notebook import build_revision_notebook, notebook_dict
from .obsidian import ExportResult, export_vault
from .planner import KIND_ORDER, DayPlan, build_plan, revision_sort_key

__all__ = [
    "INDEX_FILENAME",
    "CourseIndex",
    "Material",
    "build_index",
    "detect_kind",
    "detect_week",
    "extract_pdf_text",
    "load_index",
    "save_index",
    # Obsidian 导出
    "ExportResult",
    "export_vault",
    # 复习排期（MCP 与笔记本共用的唯一事实源）
    "KIND_ORDER",
    "DayPlan",
    "build_plan",
    "revision_sort_key",
    # 复习笔记本
    "build_revision_notebook",
    "notebook_dict",
]
