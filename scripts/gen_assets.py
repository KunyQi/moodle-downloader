"""
生成 README / GitHub 主页用的图片资源：

    assets/demo-zh.png       中文终端演示
    assets/demo-en.png       英文终端演示
    assets/social-preview.png  社交预览卡片（1280x640，用于仓库 Settings → Social preview）

原理：用真实的 RichUI 组件渲染示例数据 → export_html → 无头浏览器截图。
相比 Rich 的 export_svg，HTML + 浏览器自然排版能正确显示中文（CJK），不会重叠。
界面文案 / 布局改动后重新运行即可同步：

    python scripts/gen_assets.py
"""
from __future__ import annotations

import io
import sys
import tempfile
import time
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console
from rich.terminal_theme import TerminalTheme

import moodle_scraper.ui as ui_mod
from moodle_scraper.config import AppConfig
from moodle_scraper.i18n import set_language, t
from moodle_scraper.scanner import Resource
from moodle_scraper.ui import RichUI

ASSETS = ROOT / "assets"
SCRIPTS = ROOT / "scripts"

# 示例课件（与真实课程页面的典型内容一致）
DEMO_FILES = [
    "Course Introduction.pdf",
    "Topic 1 - Lecture Notes.pdf",
    "Topic 1 Solved Examples.pdf",
    "Workshop 1.pdf",
    "Workshop 1 Solutions.pdf",
    "Lab Manual (Week 2).pdf",
    "Formula Sheet.pdf",
]

# 近似 GitHub 暗色的终端配色
THEME = TerminalTheme(
    (13, 17, 23),
    (230, 237, 243),
    [(13, 17, 23), (255, 106, 102), (86, 211, 100), (230, 192, 123),
     (121, 192, 255), (210, 168, 255), (57, 197, 187), (230, 237, 243)],
    [(72, 79, 88), (255, 123, 114), (86, 211, 100), (230, 192, 123),
     (121, 192, 255), (210, 168, 255), (57, 197, 187), (255, 255, 255)],
)

# 优先等宽 + 中文全角对齐的字体栈（浏览器按可用性回退）
FONT_STACK = (
    "'Sarasa Mono SC','Maple Mono NF CN','Cascadia Mono',"
    "'Microsoft YaHei Mono','NSimSun',Consolas,monospace"
)


def _terminal_html(lang: str) -> str:
    set_language(lang)
    console = Console(record=True, width=84, force_terminal=True, file=io.StringIO())
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

    body = console.export_html(inline_styles=True, theme=THEME)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
 body{{margin:0;background:#0d1117;}}
 #wrap{{display:inline-block;padding:26px 30px;background:#0d1117;border-radius:12px;}}
 pre,pre span{{font-family:{FONT_STACK} !important;font-size:15px;line-height:1.4;margin:0;}}
</style></head><body><div id="wrap">{body}</div></body></html>"""


def _make_driver():
    """无头浏览器，Edge → Chrome 依次尝试（2x 缩放，输出清晰）"""
    args = [
        "--headless=new",
        "--force-device-scale-factor=2",
        "--window-size=1600,1400",
        "--hide-scrollbars",
    ]
    from selenium import webdriver

    try:
        from selenium.webdriver.edge.options import Options as EdgeOptions
        opts = EdgeOptions()
        for a in args:
            opts.add_argument(a)
        return webdriver.Edge(options=opts)
    except Exception:
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        opts = ChromeOptions()
        for a in args:
            opts.add_argument(a)
        return webdriver.Chrome(options=opts)


def _shoot(driver, url: str, element_id: str, out: Path, wait: float = 1.6) -> None:
    driver.get(url)
    time.sleep(wait)  # 等字体 / 图片加载
    out.parent.mkdir(parents=True, exist_ok=True)
    driver.find_element("id", element_id).screenshot(str(out))
    print(f"✅ {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    driver = _make_driver()
    try:
        # 1) 两张终端演示图（社交卡片依赖 demo-zh.png，须先生成）
        for lang in ("zh", "en"):
            with tempfile.NamedTemporaryFile(
                "w", suffix=".html", delete=False, encoding="utf-8"
            ) as f:
                f.write(_terminal_html(lang))
                tmp = Path(f.name)
            try:
                _shoot(driver, tmp.resolve().as_uri(), "wrap", ASSETS / f"demo-{lang}.png")
            finally:
                tmp.unlink(missing_ok=True)

        # 2) 社交预览卡片（引用 ../assets/demo-zh.png）
        _shoot(driver, (SCRIPTS / "social_preview.html").resolve().as_uri(),
               "card", ASSETS / "social-preview.png")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
