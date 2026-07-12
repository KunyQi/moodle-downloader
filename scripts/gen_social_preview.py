"""
生成 GitHub Social Preview 图（assets/social-preview.png，1280x640）

用 Selenium 无头浏览器渲染 scripts/social_preview.html 后对卡片元素截图：

    python scripts/gen_social_preview.py

生成后在 GitHub 网页上传：仓库 Settings → General → Social preview → Edit。
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "scripts" / "social_preview.html"
OUT = ROOT / "assets" / "social-preview.png"


def _make_driver():
    """无头浏览器，Edge → Chrome 依次尝试"""
    common = [
        "--headless=new",
        "--force-device-scale-factor=1",
        "--window-size=1400,800",
        "--hide-scrollbars",
    ]
    from selenium import webdriver

    try:
        from selenium.webdriver.edge.options import Options as EdgeOptions
        opts = EdgeOptions()
        for a in common:
            opts.add_argument(a)
        return webdriver.Edge(options=opts)
    except Exception:
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        opts = ChromeOptions()
        for a in common:
            opts.add_argument(a)
        return webdriver.Chrome(options=opts)


def main() -> None:
    driver = _make_driver()
    try:
        driver.get(HTML.resolve().as_uri())
        # 等字体与 SVG 加载
        import time
        time.sleep(2)
        card = driver.find_element("id", "card")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        card.screenshot(str(OUT))
        size = OUT.stat().st_size
        print(f"✅ {OUT.relative_to(ROOT)} ({size / 1024:.0f} KB)")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
