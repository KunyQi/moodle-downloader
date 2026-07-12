"""
生成 README 用的终端演示图（assets/demo-zh.svg / demo-en.svg）

用真实的 RichUI 组件渲染示例数据，导出 SVG——非截图、非手绘，
界面文案改动后重新运行即可同步演示图：

    python scripts/gen_demo_svg.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console

import moodle_scraper.ui as ui_mod
from moodle_scraper.config import AppConfig
from moodle_scraper.i18n import set_language, t
from moodle_scraper.scanner import Resource
from moodle_scraper.ui import RichUI

# 示例数据（与真实课程页面的典型内容一致）
DEMO_FILES = [
    "Course Introduction.pdf",
    "Topic 1 - Lecture Notes.pdf",
    "Topic 1 Solved Examples.pdf",
    "Workshop 1.pdf",
    "Workshop 1 Solutions.pdf",
    "Lab Manual (Week 2).pdf",
    "Formula Sheet.pdf",
]


def make_demo(lang: str, out_path: Path) -> None:
    set_language(lang)
    console = Console(record=True, width=88, force_terminal=True, file=io.StringIO())
    ui_mod.console = console

    cfg = AppConfig(
        course_id="95383",
        course_name="PHYS1231 Higher Physics 1B",
        max_workers=24,
        save_dir="PHYS1231_Higher_Physics_1B",
    )
    ui = RichUI(cfg)

    ui.welcome()
    ui.status("📋", t("flow.detecting_course", course_id="95383"))
    ui.status("🔍", t("flow.scanning"))
    ui.show_scan_results([Resource(name=n, url="") for n in DEMO_FILES])
    console.print()

    progress = ui.create_progress()
    tid = progress.add_task(f"📥 {t('flow.downloading')}", total=len(DEMO_FILES))
    progress.update(tid, completed=len(DEMO_FILES))
    console.print(progress.get_renderable())

    ui.download_summary(new_count=6, total=len(DEMO_FILES), failed=[])
    ui.result_banner(6)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(console.export_svg(title="moodle-downloader"), encoding="utf-8")
    print(f"✅ {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    make_demo("zh", ROOT / "assets" / "demo-zh.svg")
    make_demo("en", ROOT / "assets" / "demo-en.svg")
