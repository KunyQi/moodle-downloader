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
    table.add_column("课程名称", style="white")
    table.add_column("课程 ID", style="yellow")
    for i, c in enumerate(courses, 1):
        table.add_row(str(i), c.name, c.id)
    console.print(table)
    console.print()
    try:
        choice = input("  输入序号选课，或直接输入课程 ID（回车退出）: ").strip()
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
        console.print("  [red]❌ 请输入数字序号或有效的课程 ID[/]")
        return None
    return CourseInfo(id=choice, name=f"Course_{choice}", url="")


def _download_course_by_id(ui: RichUI, client, course_id: str, config: AppConfig) -> int:
    """按课程 ID 下载（自动检测名称、扫描、下载）"""
    config.course_id = course_id
    scanner = Scanner(client)

    ui.status("📋", f"正在识别课程 {course_id}...")
    detected_name = scanner.fetch_course_name(course_id)
    config.course_name = detected_name
    safe_dir_name = detected_name.replace(" ", "_").replace("/", "_")
    config.save_dir = safe_dir_name
    config.ensure_dirs()

    ui.status("🔍", "正在扫描课件文件...")
    try:
        items = scanner.scan_course(
            course_id,
            keywords=config.file_keywords,
            extensions=config.file_extensions,
        )
    except Exception as e:
        ui.show_error("扫描失败", str(e))
        return 1

    if not items:
        ui.status("❓", "未找到任何课件资源")
        return 0

    ui.show_scan_results(items)
    if not _confirm(f"共 {len(items)} 个文件，确认下载？"):
        ui.status("⏩", "已取消")
        return 0

    progress = ui.create_progress()
    task_id = progress.add_task("📥 下载中...", total=len(items))
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
        ui.show_error("无课程", "未找到任何课程")
        return 1
    picked = _show_course_table(courses, f"📚 你注册了 {len(courses)} 门课程")
    if not picked:
        return 0
    return _download_course_by_id(ui, client, picked.id, config)


def _discover_courses(
    ui: RichUI, client, config: AppConfig,
    start_id: int, end_id: int,
) -> int:
    """扫描 ID 范围 → 列出结果 → 选一门下载"""
    if start_id <= 0 or end_id <= 0 or end_id < start_id:
        ui.show_error("参数无效", "扫描范围无效，请使用: --discover 起始ID-结束ID")
        return 1
    total = end_id - start_id + 1
    scanner = Scanner(client)
    progress = ui.create_progress()
    task_id = progress.add_task("🔍 扫描中...", total=total)

    def on_progress(done: int, _total: int, _cid: int):
        progress.update(task_id, completed=done, description=f"🔍 正在试 ID {_cid}...")

    with progress:
        courses = scanner.discover_courses(
            start_id, end_id,
            max_workers=config.max_workers,
            on_progress=on_progress,
        )

    if not courses:
        ui.show_error("无发现", f"范围 {start_id}～{end_id} 内未找到可访问的课程")
        return 1
    picked = _show_course_table(courses, f"🔍 发现 {len(courses)} 门可访问的课程")
    if not picked:
        return 0
    return _download_course_by_id(ui, client, picked.id, config)


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
) -> int:
    """主流程 — 返回退出码 (0=成功)"""
    if course_id is not None:
        config.course_id = course_id
    if workers is not None:
        config.max_workers = workers
    if browser:
        config.browser = browser

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
    auth = AuthManager(config, on_status=ui.status)

    # ── 认证 ──────────────────────────────────────────
    cookies_exist = auth.has_cached_cookies()
    if not cookies_exist:
        if not _confirm("打开 Edge 浏览器登录 UNWS Moodle？"):
            ui.status("👋", "已取消")
            return 0

    client = auth.get_authenticated_client(use_cached_first=cookies_exist)
    if not client:
        ui.show_error("认证失败", "无法获取有效的登录凭据")
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
        )
    except KeyboardInterrupt:
        print("\n  ⛔ 用户中断")
    except Exception:
        print("\n  💥 发生未预料的错误：")
        traceback.print_exc()
    finally:
        input("\n  按 Enter 键退出...")
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
