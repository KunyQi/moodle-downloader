"""
downloader — 扫描模块

⚠️ 免责声明: 本工具仅供学生下载本人已注册课程的课件。
Disclaimer: For students to download their own course materials only.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

from .http import HttpClient, HttpResponse
from .i18n import t
from .utils import is_login_page


class ScanError(Exception):
    """扫描过程相关异常"""


COURSE_NAME_PATTERNS = [
    "h1.page-header-heading",           # Moodle 4.x
    "h1",                               # 通用 fallback
    "title",                            # 极简 fallback
]


@dataclass
class Resource:
    """一个可下载的课件资源"""
    name: str
    url: str


@dataclass
class CourseInfo:
    """仪表盘上的一门课程"""
    id: str
    name: str
    url: str


class Scanner:
    """Moodle 课程页面扫描器"""

    def __init__(self, client: HttpClient):
        self._client = client

    def fetch_course_name(self, course_id: str) -> str:
        """
        从课程主页抓取课程名称

        :returns: 课程名称字符串，解析失败时返回默认值
        """
        url = f"https://moodle.telt.unsw.edu.au/course/view.php?id={course_id}"
        try:
            resp = self._client.get(url, timeout=30)

            if is_login_page(resp.url, resp.text):
                raise ScanError(t("scanner.session_expired"))

            soup = BeautifulSoup(resp.text, "html.parser")

            # 1. Moodle 4.x 专用：h1.page-header-heading
            h1 = soup.select_one("h1.page-header-heading")
            if h1:
                return h1.get_text(strip=True)

            # 2. 通用 h1（通常第一个 h1 是课程名）
            h1s = soup.find_all("h1")
            if h1s:
                text = h1s[0].get_text(strip=True)
                if text and "course" not in text.lower():
                    return text

            # 3. 页面标题（去掉站点名后缀）
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)
                # 去掉常见的 Moodle 后缀
                for sep in ["—", "–", "-", "|"]:
                    if sep in title:
                        title = title.split(sep)[0].strip()
                return title

        except Exception:
            pass

        return f"Course_{course_id}"

    def list_courses(self) -> list[CourseInfo]:
        """
        从仪表盘（/my/）抓取当前用户已注册的所有课程

        :returns: 课程列表，按名称排序；登录失效时返回空列表
        """
        try:
            resp = self._client.get(
                "https://moodle.telt.unsw.edu.au/my/", timeout=30
            )

            if is_login_page(resp.url, resp.text):
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            seen: set[str] = set()
            courses: list[CourseInfo] = []

            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "course/view.php?id=" not in href:
                    continue

                # 提取 course_id
                raw_id = href.split("course/view.php?id=")[-1].split("&")[0].split("?")[0]
                if not raw_id.isdigit():
                    continue

                name = a.get_text(strip=True)
                if not name:
                    continue

                if raw_id not in seen:
                    seen.add(raw_id)
                    courses.append(CourseInfo(id=raw_id, name=name, url=href))

            courses.sort(key=lambda c: c.name.lower())
            return courses

        except Exception:
            return []

    def discover_courses(
        self,
        start_id: int,
        end_id: int,
        *,
        max_workers: int = 24,
        on_progress: Optional[callable] = None,
    ) -> list[CourseInfo]:
        """
        尝试一段 course_id 范围，返回可访问的课程列表

        :param start_id: 起始 ID（含）
        :param end_id: 结束 ID（含）
        :param max_workers: 并行线程数（默认 24）
        :param on_progress: 进度回调 (current, total, current_course_id)
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        total = end_id - start_id + 1
        ids = list(range(start_id, end_id + 1))
        results: list[CourseInfo] = []
        done = 0

        on_progress = on_progress or (lambda c, t, i: None)
        on_progress(0, total, start_id)

        def _check_one(cid: int) -> Optional[CourseInfo]:
            """检查单个 ID 是否可访问"""
            try:
                url = f"https://moodle.telt.unsw.edu.au/course/view.php?id={cid}"
                resp = self._client.get(url, timeout=5)

                # 登录页或被拒绝 → 跳过
                if is_login_page(resp.url, resp.text):
                    return None
                if "Access denied" in resp.text or "not enrolled" in resp.text.lower():
                    return None
                if "error" in resp.url.lower() and "course" in resp.url.lower():
                    return None

                # 尝试提取课程名
                soup = BeautifulSoup(resp.text, "html.parser")
                name = ""

                h1 = soup.select_one("h1.page-header-heading")
                if h1:
                    name = h1.get_text(strip=True)

                if not name:
                    h1s = soup.find_all("h1")
                    if h1s:
                        name = h1s[0].get_text(strip=True)

                if not name:
                    title_tag = soup.find("title")
                    if title_tag:
                        name = title_tag.get_text(strip=True)
                        for sep in ["—", "–", "-", "|"]:
                            if sep in name:
                                name = name.split(sep)[0].strip()

                if name and "course" not in name.lower() and "error" not in name.lower():
                    return CourseInfo(id=str(cid), name=name, url=url)

                return None
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            fut_map = {pool.submit(_check_one, cid): cid for cid in ids}
            for future in as_completed(fut_map):
                cid = fut_map[future]
                done += 1
                try:
                    info = future.result()
                    if info:
                        results.append(info)
                except Exception:
                    pass
                on_progress(done, total, cid)

        results.sort(key=lambda c: c.name.lower())
        return results

    def scan_course(
        self,
        course_id: str,
        *,
        keywords: Optional[list[str]] = None,
        extensions: Optional[list[str]] = None,
    ) -> list[Resource]:
        """
        扫描课程主页，返回符合条件的课件列表

        :param course_id: Moodle 课程 ID
        :param keywords: 文件名关键词过滤（默认不过滤）
        :param extensions: 后缀过滤（默认不过滤）
        """
        keywords = keywords or []
        extensions = extensions or []

        url = f"https://moodle.telt.unsw.edu.au/course/view.php?id={course_id}"
        resp = self._fetch(url)

        if is_login_page(resp.url, resp.text):
            raise ScanError(t("scanner.session_expired"))

        soup = BeautifulSoup(resp.text, "html.parser")

        resources: list[Resource] = []
        seen: set[str] = set()
        page_links: list[str] = []

        # Stage 1: 直接资源链接
        for a in soup.find_all("a"):
            href = a.get("href", "")
            text = a.get_text(strip=True)

            if "mod/resource" in href and href not in seen:
                if text and text != "File":
                    resources.append(Resource(name=text, url=href))
                    seen.add(href)
            elif "mod/page" in href and href not in page_links:
                page_links.append(href)

        # Stage 2: 钻入子页面提取嵌套 pluginfile 链接
        for page_url in page_links:
            try:
                page_resp = self._fetch(page_url)
                page_soup = BeautifulSoup(page_resp.text, "html.parser")
                for tag in page_soup.find_all("a"):
                    href = tag.get("href", "")
                    if "pluginfile.php" in href and href not in seen:
                        raw_name = href.split("?")[0].split("/")[-1]
                        real_name = urllib.parse.unquote(raw_name)

                        if self._matches(real_name, keywords, extensions):
                            clean_name = re.sub(
                                r"\.(pdf|pptx?|docx?)$", "", real_name, flags=re.IGNORECASE
                            )
                            resources.append(Resource(name=clean_name, url=href))
                            seen.add(href)
            except Exception:
                pass  # 单个页面失败不影响整体

        return resources

    # ─── 内部方法 ───────────────────────────────────────────

    def _fetch(self, url: str) -> HttpResponse:
        """带超时的 HTTP GET"""
        return self._client.get(url, timeout=30)

    @staticmethod
    def _matches(name: str, keywords: list[str], extensions: list[str]) -> bool:
        """检查文件名是否符合关键词或后缀条件"""
        name_lower = name.lower()
        if keywords:
            if any(k.lower() in name_lower for k in keywords):
                return True
        if extensions:
            if any(name_lower.endswith(e) for e in extensions):
                return True
        # 如果两者都为空，默认全部通过
        return not keywords and not extensions
