"""
测试 Scanner — 用 FakeHttpClient 模拟 Moodle 课程页面
"""
from __future__ import annotations

from moodle_scraper.http import FakeHttpClient, HttpResponse
from moodle_scraper.scanner import Scanner, ScanError

COURSE_URL = "https://moodle.telt.unsw.edu.au/course/view.php?id=95383"
PAGE_REL = "/mod/page/view.php?id=99"  # 相对路径（Moodle HTML 中的实际格式）
PAGE_HTML = """<html><body>
    <a href="https://moodle.au/pluginfile.php/123/lecture_1.pdf">lecture_1</a>
    <a href="https://moodle.au/pluginfile.php/124/hidden_slides.pptx">hidden_slides</a>
    <a href="https://moodle.au/pluginfile.php/125/readme.txt">readme</a>
</body></html>"""


def _make_fake() -> FakeHttpClient:
    """预制一个包含 2 个直接资源 + 1 个子页面的课程页面"""
    fake = FakeHttpClient()

    course_html = """<html>
    <body>
        <a href="/mod/resource/view.php?id=1">Lecture 1</a>
        <a href="/mod/resource/view.php?id=2">Lab Manual</a>
        <a href="/mod/page/view.php?id=99">Slides page</a>
    </body></html>"""
    fake.add_response(COURSE_URL, HttpResponse(200, course_html, COURSE_URL))
    fake.add_response(PAGE_REL, HttpResponse(200, PAGE_HTML, PAGE_REL))

    return fake


class TestScanner:
    """Scanner 扫描课程并返回 Resource 列表"""

    def test_scan_direct_resources(self):
        fake = _make_fake()
        scanner = Scanner(fake)
        resources = scanner.scan_course("95383")
        # 2 direct (Lecture 1, Lab Manual) + 3 from sub-page (lecture_1.pdf, hidden_slides.pptx, readme.txt)
        assert len(resources) == 5
        names = [r.name for r in resources]
        assert "Lecture 1" in names
        assert "Lab Manual" in names
        assert "lecture_1" in names
        assert "hidden_slides" in names
        assert "readme.txt" in names

    def test_scan_returns_resource_objects(self):
        fake = _make_fake()
        scanner = Scanner(fake)
        resources = scanner.scan_course("95383")
        for r in resources:
            assert hasattr(r, "name")
            assert hasattr(r, "url")

    def test_scan_filters_by_keyword(self):
        fake = _make_fake()
        scanner = Scanner(fake)
        resources = scanner.scan_course("95383", keywords=["lecture"])
        names = [r.name for r in resources]
        assert "Lecture 1" in names  # 直接资源，不过滤
        assert "lecture_1" in names  # 子页面 pluginfile 匹配关键词
        # 直接资源不走关键词过滤（原始行为），所以 Lab Manual 仍会出现
        assert "Lab Manual" in names

    def test_scan_filters_by_extension(self):
        fake = _make_fake()
        scanner = Scanner(fake)
        resources = scanner.scan_course("95383", extensions=[".pdf"])
        names = [r.name for r in resources]
        assert "lecture_1" in names
        assert "hidden_slides" not in names  # .pptx not in .pdf filter

    def test_scan_raises_on_login_page(self):
        fake = FakeHttpClient()
        fake.add_response(COURSE_URL, HttpResponse(200, "Log in to Moodle",
                          "https://moodle.au/login/index.php"))
        scanner = Scanner(fake)
        import pytest
        with pytest.raises(ScanError):
            scanner.scan_course("95383")

    def test_scan_empty_when_no_links(self):
        fake = FakeHttpClient()
        fake.add_response(COURSE_URL, HttpResponse(200, "<html></html>", COURSE_URL))
        scanner = Scanner(fake)
        assert scanner.scan_course("95383") == []


class TestFetchCourseName:
    """从课程页面 HTML 提取课程名称"""

    def test_from_h1_header(self):
        fake = FakeHttpClient()
        fake.add_response(COURSE_URL, HttpResponse(200, """
            <html><body>
                <h1 class="page-header-heading">PHYS1231 – Physics 1B</h1>
            </body></html>""", COURSE_URL))
        scanner = Scanner(fake)
        assert scanner.fetch_course_name("95383") == "PHYS1231 – Physics 1B"

    def test_from_title(self):
        fake = FakeHttpClient()
        fake.add_response(COURSE_URL, HttpResponse(200, """
            <html><head><title>PHYS1231 Physics 1B — UNSW Moodle</title></head></html>""",
            COURSE_URL))
        scanner = Scanner(fake)
        name = scanner.fetch_course_name("95383")
        assert "PHYS1231" in name
        assert "Physics" in name

    def test_fallback_on_failure(self):
        fake = FakeHttpClient()
        fake.add_response(COURSE_URL, HttpResponse(200, "<html></html>", COURSE_URL))
        scanner = Scanner(fake)
        name = scanner.fetch_course_name("95383")
        assert "Course_" in name


class TestListCourses:
    """从仪表盘解析课程列表"""

    DASHBOARD_HTML = """<html><body>
        <a href="https://moodle.telt.unsw.edu.au/course/view.php?id=95383">PHYS1231 – Physics 1B</a>
        <a href="https://moodle.telt.unsw.edu.au/course/view.php?id=98120">MATH1231 – Calculus</a>
        <a href="https://moodle.telt.unsw.edu.au/course/view.php?id=99666">COMP1511 – Programming</a>
        <a href="https://moodle.telt.unsw.edu.au/some/other/page">Ignore me</a>
    </body></html>"""

    def test_list_all_courses(self):
        fake = FakeHttpClient()
        fake.add_response("https://moodle.telt.unsw.edu.au/my/",
                          HttpResponse(200, self.DASHBOARD_HTML,
                                       "https://moodle.telt.unsw.edu.au/my/"))
        scanner = Scanner(fake)
        courses = scanner.list_courses()
        assert len(courses) == 3
        ids = [c.id for c in courses]
        assert "95383" in ids
        assert "98120" in ids
        assert "99666" in ids

    def test_list_sorted_by_name(self):
        fake = FakeHttpClient()
        fake.add_response("https://moodle.telt.unsw.edu.au/my/",
                          HttpResponse(200, self.DASHBOARD_HTML,
                                       "https://moodle.telt.unsw.edu.au/my/"))
        scanner = Scanner(fake)
        courses = scanner.list_courses()
        names = [c.name for c in courses]
        assert names == sorted(names)

    def test_list_login_page_returns_empty(self):
        fake = FakeHttpClient()
        fake.add_response("https://moodle.telt.unsw.edu.au/my/",
                          HttpResponse(200, "Log in to Moodle",
                                       "https://moodle.au/login/index.php"))
        scanner = Scanner(fake)
        assert scanner.list_courses() == []


class TestDiscoverCourses:
    """扫描 ID 范围发现可访问课程"""

    def test_finds_courses_in_range(self):
        fake = FakeHttpClient()
        # 模拟几个有效课程
        for cid in [95001, 95005, 95010]:
            fake.add_response(
                f"https://moodle.telt.unsw.edu.au/course/view.php?id={cid}",
                HttpResponse(200, f"""<html><head><title>Course {cid} — UNSW Moodle</title></head>
                    <body><h1 class="page-header-heading">Subject{cid} – Name</h1></body></html>""",
                    f"https://moodle.telt.unsw.edu.au/course/view.php?id={cid}"),
            )
        # 其他 ID 返回 404 或登录页
        for cid in [95002, 95003, 95004]:
            fake.add_response(
                f"https://moodle.telt.unsw.edu.au/course/view.php?id={cid}",
                HttpResponse(200, "Access denied", "https://moodle.au/login/index.php"),
            )

        scanner = Scanner(fake)
        courses = scanner.discover_courses(95001, 95010, max_workers=1)
        assert len(courses) == 3
        ids = [c.id for c in courses]
        assert "95001" in ids

    def test_discover_empty_range(self):
        fake = FakeHttpClient()
        for cid in range(99000, 99005):
            fake.add_response(
                f"https://moodle.telt.unsw.edu.au/course/view.php?id={cid}",
                HttpResponse(200, "Access denied", "https://moodle.au/login/index.php"),
            )
        scanner = Scanner(fake)
        courses = scanner.discover_courses(99000, 99004, max_workers=1)
        assert courses == []
