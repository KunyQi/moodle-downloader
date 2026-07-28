"""
downloader

⚠️ 免责声明 / Disclaimer:
   本工具仅供学生下载本人已注册课程的课件。
   This tool is for students to download course materials
   they are enrolled in, for offline study purposes only.
   请遵守所在机构 IT 使用政策。
   Please comply with your institution's IT Acceptable Use Policy.
"""
from __future__ import annotations

import sys
import traceback
from typing import Optional

# Windows GBK 终端编码修复
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from .auth import AuthManager
from .config import AppConfig, config as global_config
from .downloader import Downloader
from .i18n import DEFAULT_LANGUAGE, resolve_language, set_language, t
from .scanner import CourseInfo, Scanner
from .ui import RichUI


def _confirm(prompt: str, default: bool = True) -> bool:
    """Y/n 确认提示"""
    yn = "Y/n" if default else "y/N"
    try:
        ans = input(f"  {prompt} [{yn}] ").strip().lower()
        if not ans:
            return default
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return default


# ═══════════════════════════════════════════════════════════════
# 子流程
# ═══════════════════════════════════════════════════════════════

def _show_course_table(courses: list, title: str) -> Optional[dict]:
    """显示课程表格 → 让用户选课（序号或直接输入 ID）→ 返回选中课程或 None"""
    from rich.table import Table
    from moodle_scraper.ui import console
    console.print()
    table = Table(
        title=title, title_style="bold cyan",
        border_style="dim", header_style="bold blue",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column(t("table.course_name"), style="white")
    table.add_column(t("table.course_id"), style="yellow")
    for i, c in enumerate(courses, 1):
        table.add_row(str(i), c.name, c.id)
    console.print(table)
    console.print()
    try:
        choice = input(f"  {t('table.pick_prompt')}").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not choice:
        return None
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(courses):
            return courses[idx]
    except ValueError:
        pass
    # 不是有效序号 → 检查输入是否为有效的课程 ID（至少是数字）
    if not choice.isdigit():
        console.print(f"  [red]❌ {t('table.pick_invalid')}[/]")
        return None
    return CourseInfo(id=choice, name=f"Course_{choice}", url="")


def _download_course_by_id(ui: RichUI, client, course_id: str, config: AppConfig) -> int:
    """按课程 ID 下载（自动检测名称、扫描、下载）"""
    config.course_id = course_id
    scanner = Scanner(client)

    ui.status("📋", t("flow.detecting_course", course_id=course_id))
    detected_name = scanner.fetch_course_name(course_id)
    config.course_name = detected_name
    safe_dir_name = detected_name.replace(" ", "_").replace("/", "_")
    config.save_dir = safe_dir_name
    config.ensure_dirs()

    ui.status("🔍", t("flow.scanning"))
    try:
        items = scanner.scan_course(
            course_id,
            keywords=config.file_keywords,
            extensions=config.file_extensions,
        )
    except Exception as e:
        ui.show_error(t("flow.scan_failed_title"), str(e))
        return 1

    if not items:
        ui.status("❓", t("flow.no_resources"))
        return 0

    ui.show_scan_results(items)
    if not _confirm(t("flow.confirm_download", count=len(items))):
        ui.status("⏩", t("flow.cancelled"))
        return 0

    progress = ui.create_progress()
    task_id = progress.add_task(f"📥 {t('flow.downloading')}", total=len(items))
    downloader = Downloader(
        client,
        save_dir=config.save_dir,
        max_workers=config.max_workers,
        chunk_size=config.download_chunk_size,
        on_progress=lambda c, t, m: progress.update(
            task_id, completed=c, description=f"📥 {m}" if m else None
        ),
    )
    with progress:
        result = downloader.download_all(items)

    ui.download_summary(result.new_count, result.total, result.failed)
    ui.result_banner(result.new_count)
    return 0 if not result.failed else 2


def _list_courses(ui: RichUI, client, config: AppConfig) -> int:
    """列出已注册课程 → 选一门下载（序号或直接输入 ID）"""
    scanner = Scanner(client)
    courses = scanner.list_courses()
    if not courses:
        ui.show_error(t("flow.no_courses_title"), t("flow.no_courses_detail"))
        return 1
    picked = _show_course_table(courses, f"📚 {t('flow.enrolled_title', count=len(courses))}")
    if not picked:
        return 0
    return _download_course_by_id(ui, client, picked.id, config)


def _discover_courses(
    ui: RichUI, client, config: AppConfig,
    start_id: int, end_id: int,
) -> int:
    """扫描 ID 范围 → 列出结果 → 选一门下载"""
    if start_id <= 0 or end_id <= 0 or end_id < start_id:
        ui.show_error(t("flow.invalid_range_title"), t("flow.invalid_range_detail"))
        return 1
    total = end_id - start_id + 1
    scanner = Scanner(client)
    progress = ui.create_progress()
    task_id = progress.add_task(f"🔍 {t('flow.discover_scanning')}", total=total)

    def on_progress(done: int, _total: int, _cid: int):
        progress.update(
            task_id, completed=done,
            description=f"🔍 {t('flow.discover_trying', course_id=_cid)}",
        )

    with progress:
        courses = scanner.discover_courses(
            start_id, end_id,
            max_workers=config.max_workers,
            on_progress=on_progress,
        )

    if not courses:
        ui.show_error(
            t("flow.discover_none_title"),
            t("flow.discover_none_detail", start=start_id, end=end_id),
        )
        return 1
    picked = _show_course_table(courses, f"🔍 {t('flow.discover_found_title', count=len(courses))}")
    if not picked:
        return 0
    return _download_course_by_id(ui, client, picked.id, config)


# ═══════════════════════════════════════════════════════════════
# 学习 / Agent 集成（操作已下载的本地文件，无需登录）
# ═══════════════════════════════════════════════════════════════

def _study_flow(
    ui: RichUI,
    *,
    root: str,
    export_vault_dir: Optional[str] = None,
    notebook_path: Optional[str] = None,
    course: Optional[str] = None,
    days: int = 7,
    overwrite: bool = False,
    copy_files: bool = False,
) -> int:
    """索引本地课件 → 可选导出 Obsidian / 生成复习 notebook"""
    from pathlib import Path

    from .study import (
        INDEX_FILENAME,
        build_index,
        build_revision_notebook,
        export_vault,
        save_index,
    )

    root_path = Path(root).resolve()

    ui.status("🔍", t("study.indexing", root=root_path))
    try:
        index = build_index(root_path)
    except Exception as e:
        ui.show_error(t("study.failed_title"), str(e))
        return 1

    materials = index.all_materials()
    if not materials:
        ui.status("❓", t("study.no_materials"))
        return 0

    ui.status("📚", t("study.index_done", courses=len(index.courses), files=len(materials)))

    index_path = root_path / INDEX_FILENAME
    try:
        save_index(index, index_path)
        ui.status("📌", t("study.index_saved", path=index_path))
    except Exception as e:
        ui.show_error(t("study.failed_title"), str(e))
        return 1

    # ── 导出 Obsidian 知识库 ──────────────────────────
    if export_vault_dir:
        ui.status("📝", t("study.exporting", vault=export_vault_dir))
        try:
            result = export_vault(
                index, export_vault_dir,
                overwrite=overwrite, copy_files=copy_files,
            )
        except Exception as e:
            ui.show_error(t("study.failed_title"), str(e))
            return 1
        ui.status("✅", t(
            "study.export_done",
            notes=result.notes_written, courses=result.courses, skipped=result.skipped,
        ))
        if result.files_copied:
            ui.status("📦", t("study.export_copied", count=result.files_copied))
        ui.status("👉", t("study.export_hint"))

    # ── 生成复习 notebook ─────────────────────────────
    if notebook_path:
        ui.status("📓", t("study.notebook_building"))
        try:
            written = build_revision_notebook(index, notebook_path, course=course, days=days)
        except Exception as e:
            ui.show_error(t("study.failed_title"), str(e))
            return 1
        ui.status("✅", t("study.notebook_done", path=written))

    ui.status("🌐", t("study.mcp_hint"))
    return 0


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def main_impl(
    config: AppConfig,
    *,
    course_id: Optional[str] = None,
    workers: Optional[int] = None,
    discover_range: Optional[str] = None,
    browser: str = "",
    lang: str = "",
    study_root: Optional[str] = None,
    export_vault_dir: Optional[str] = None,
    notebook_path: Optional[str] = None,
    days: int = 7,
    overwrite: bool = False,
    copy_files: bool = False,
) -> int:
    """主流程 — 返回退出码 (0=成功)"""
    if course_id is not None:
        config.course_id = course_id
    if workers is not None:
        config.max_workers = workers
    if browser:
        config.browser = browser
    if lang:
        config.language = lang

    # 解析界面语言（--lang 优先于 config.toml；无法识别时回退默认并提示）
    requested_lang = (config.language or "").strip()
    resolved_lang = resolve_language(requested_lang) if requested_lang else DEFAULT_LANGUAGE
    unsupported_lang = requested_lang if resolved_lang is None else ""
    set_language(resolved_lang or DEFAULT_LANGUAGE)

    # 解析 discover 范围（必须由 --discover start-end 指定）
    discover_start, discover_end = 0, 0
    if discover_range:
        try:
            parts = discover_range.split("-")
            discover_start = int(parts[0])
            discover_end = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            discover_start, discover_end = 0, 0

    ui = RichUI(config)
    if unsupported_lang:
        ui.status("⚠️", t("lang.unsupported", lang=unsupported_lang))

    # ── 学习 / Agent 集成：只读本地文件，在认证之前短路返回 ──
    if study_root is not None or export_vault_dir or notebook_path:
        return _study_flow(
            ui,
            root=study_root or ".",
            export_vault_dir=export_vault_dir,
            notebook_path=notebook_path,
            course=config.course_id or None,
            days=days,
            overwrite=overwrite,
            copy_files=copy_files,
        )

    auth = AuthManager(config, on_status=ui.status)

    # ── 认证 ──────────────────────────────────────────
    cookies_exist = auth.has_cached_cookies()
    if not cookies_exist:
        if not _confirm(t("flow.confirm_login")):
            ui.status("👋", t("flow.cancelled"))
            return 0

    client = auth.get_authenticated_client(use_cached_first=cookies_exist)
    if not client:
        ui.show_error(t("flow.auth_failed_title"), t("flow.auth_failed_detail"))
        return 1

    # ── 分发 ──────────────────────────────────────────
    if discover_range is not None:
        return _discover_courses(ui, client, config, discover_start, discover_end)

    # 命令行传了 course_id → 直接下载
    if config.course_id:
        return _download_course_by_id(ui, client, config.course_id, config)

    # 默认流程：列出已注册课程 → 用户选择 → 下载
    return _list_courses(ui, client, config)


def main(
    course_id: Optional[str] = None,
    workers: Optional[int] = None,
    discover_range: Optional[str] = None,
    browser: str = "",
    lang: str = "",
    study_root: Optional[str] = None,
    export_vault_dir: Optional[str] = None,
    notebook_path: Optional[str] = None,
    days: int = 7,
    overwrite: bool = False,
    copy_files: bool = False,
) -> None:
    """CLI 入口"""
    exit_code = 1
    try:
        exit_code = main_impl(
            global_config,
            course_id=course_id,
            workers=workers,
            discover_range=discover_range,
            browser=browser,
            lang=lang,
            study_root=study_root,
            export_vault_dir=export_vault_dir,
            notebook_path=notebook_path,
            days=days,
            overwrite=overwrite,
            copy_files=copy_files,
        )
    except KeyboardInterrupt:
        print(f"\n  ⛔ {t('app.user_interrupt')}")
    except Exception:
        print(f"\n  💥 {t('app.unexpected_error')}")
        traceback.print_exc()
    finally:
        input(f"\n  {t('app.press_enter_exit')}")
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
