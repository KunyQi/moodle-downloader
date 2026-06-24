"""
downloader — 认证模块

⚠️ 免责声明: 本工具仅供学生下载本人已注册课程的课件。
Disclaimer: For students to download their own course materials only.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .config import AppConfig
from .http import HttpClient, RequestsHttpClient


class AuthError(Exception):
    """认证相关异常"""


# ─── 浏览器驱动工厂 ─────────────────────────────────────────

def _try_chrome():
    """尝试启动 Chrome（需 chromedriver）"""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(options=opts)


def _try_edge():
    """尝试启动 Edge（需 msedgedriver）"""
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options
    opts = Options()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)
    return webdriver.Edge(options=opts)


def _try_firefox():
    """尝试启动 Firefox（需 geckodriver）"""
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    opts = Options()
    opts.set_preference("dom.webdriver.enabled", False)
    opts.set_preference("useAutomationExtension", False)
    return webdriver.Firefox(options=opts)


# 浏览器启动器注册表（按检测优先级排序）
_BROWSER_REGISTRY: dict[str, tuple[str, str, callable]] = {
    "chrome":  ("Chrome",  "chromedriver",  _try_chrome),
    "edge":    ("Edge",    "msedgedriver",  _try_edge),
    "firefox": ("Firefox", "geckodriver",   _try_firefox),
}


def _detect_browser(ui_browser: str = "") -> tuple[str, object]:
    """
    检测可用浏览器，返回 (浏览器名, driver 实例)

    策略：
    1. ui_browser 指定了 → 只用那个
    2. 未指定 → 按 Chrome → Edge → Firefox 顺序自动检测
    """
    if ui_browser:
        if ui_browser not in _BROWSER_REGISTRY:
            raise AuthError(f"不支持的浏览器: {ui_browser}，可选: {', '.join(_BROWSER_REGISTRY)}")
        name, driver_name, factory = _BROWSER_REGISTRY[ui_browser]
        return name, factory()

    for key, (name, driver_name, factory) in _BROWSER_REGISTRY.items():
        try:
            driver = factory()
            return name, driver
        except Exception:
            continue

    raise AuthError(
        "未检测到可用浏览器。请安装以下任一 WebDriver：\n"
        "  - Chrome:  https://chromedriver.chromium.org/\n"
        "  - Edge:    https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/\n"
        "  - Firefox: https://github.com/mozilla/geckodriver/releases"
    )


# ─── AuthManager ────────────────────────────────────────────

class AuthManager:
    """管理 Moodle 登录，返回已认证的 HttpClient"""

    def __init__(self, config: AppConfig, on_status: Optional[callable] = None):
        self._config = config
        self._on_status = on_status or (lambda e, m: None)

    def has_cached_cookies(self) -> bool:
        """检查是否有本地缓存的 Cookie（不验证有效性）"""
        return Path(self._config.cookie_file).exists()

    def get_authenticated_client(
        self, *, use_cached_first: bool = True
    ) -> Optional[HttpClient]:
        """
        返回一个已注入有效 Cookie 的 HttpClient

        use_cached_first=True → 先试本地缓存，失效再弹浏览器
        """
        cookie_file = Path(self._config.cookie_file)

        if use_cached_first:
            cached = self._load_cookies(cookie_file)
            if cached:
                client = self._make_client(cached)
                if self._check_client(client):
                    return client
                self._on_status("⚠️", "Cookie 已过期，需要重新登录")

        # Selenium 重新登录
        browser = self._config.browser
        fresh_raw = self._selenium_login(browser)
        if fresh_raw:
            self._save_cookies(cookie_file, fresh_raw)
            flat = {c["name"]: c["value"] for c in fresh_raw}
            return self._make_client(flat)

        self._on_status("❌", "无法获取有效的登录凭据")
        return None

    def clear_cookies(self) -> None:
        """清除本地 Cookie 文件"""
        path = Path(self._config.cookie_file)
        if path.exists():
            path.unlink()
            self._on_status("🗑️", "已清除本地 Cookie")

    # ─── 内部方法 ─────────────────────────────────────────────

    def _make_client(self, cookies: dict[str, str]) -> RequestsHttpClient:
        client = RequestsHttpClient(user_agent=self._config.user_agent)
        client.set_cookies(cookies)
        return client

    def _check_client(self, client: HttpClient) -> bool:
        """快速校验 cookie 是否仍有效"""
        try:
            url = f"https://moodle.telt.unsw.edu.au/course/view.php?id={self._config.course_id}"
            resp = client.get(url, timeout=self._config.request_timeout)
            return "login" not in resp.url.lower() and "Log in" not in resp.text
        except Exception:
            return False

    def _load_cookies(self, path: Path) -> Optional[dict[str, str]]:
        if not path.exists():
            return None
        try:
            with open(path) as f:
                raw = json.load(f)
            return {c["name"]: c["value"] for c in raw}
        except (json.JSONDecodeError, KeyError):
            return None

    def _save_cookies(self, path: Path, cookies: list[dict]) -> None:
        with open(path, "w") as f:
            json.dump(cookies, f)

    def _selenium_login(self, browser: str = "") -> Optional[list[dict]]:
        """启动浏览器让用户完成 Okta 登录"""
        # 检测并启动浏览器
        try:
            browser_name, driver = _detect_browser(browser)
        except AuthError as e:
            self._on_status("❌", str(e))
            return None

        self._on_status("🔑", f"正在唤起 {browser_name} 浏览器进行身份验证...")

        driver_obj = driver
        try:
            driver_obj.get("https://moodle.telt.unsw.edu.au/login/index.php")
            self._on_status("👉", "请在弹出的浏览器中完成登录和 Okta 验证")
            self._on_status("⏳", "登录成功后无需操作，脚本将自动接管...")

            cfg = self._config
            start = time.time()
            while time.time() - start < cfg.login_timeout:
                current = driver_obj.current_url
                if "moodle.telt.unsw.edu.au/my/" in current or "course/view.php" in current:
                    cookies = driver_obj.get_cookies()
                    self._on_status("✅", f"登录成功！Cookie 已安全保存")
                    return cookies
                time.sleep(cfg.login_check_interval)

            self._on_status("❌", "登录等待超时，请重新运行")
            return None

        except Exception as e:
            self._on_status("❌", f"浏览器调用失败: {e}")
            return None
        finally:
            if driver_obj:
                driver_obj.quit()
