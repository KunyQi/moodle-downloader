"""
测试工具函数 — 纯函数，零依赖
"""
from __future__ import annotations

from moodle_scraper.utils import extract_extension, sanitize_filename, is_login_page


class TestSanitizeFilename:
    """sanitize_filename 去除非法字符"""

    def test_removes_file_prefix(self):
        assert sanitize_filename("File Lecture 1") == "Lecture 1"

    def test_replaces_windows_illegal_chars(self):
        result = sanitize_filename('a:b|c<d>e?f*g/h\\"i"')
        assert ":" not in result
        assert "|" not in result
        assert "<" not in result
        assert ">" not in result
        assert "?" not in result
        assert "*" not in result
        assert "/" not in result
        assert "\\" not in result
        assert '"' not in result

    def test_fallback_when_empty(self):
        assert sanitize_filename("") == "Unnamed_Resource"
        assert sanitize_filename("File") == "Unnamed_Resource"

    def test_normal_name_preserved(self):
        assert sanitize_filename("Lecture 1 Electromagnetism") == "Lecture 1 Electromagnetism"


class TestIsLoginPage:
    """is_login_page 检测 Moodle 登录页"""

    def test_login_in_url(self):
        assert is_login_page("https://moodle.au/login/index.php", "some text")

    def test_login_in_text(self):
        assert is_login_page("https://moodle.au/course/view.php", "Log in to Moodle")

    def test_normal_page(self):
        assert not is_login_page("https://moodle.au/course/view.php", "Course content here")


class TestExtractExtension:
    """extract_extension 从 URL 提取文件后缀"""

    def test_pdf_url(self):
        assert extract_extension("https://moodle.au/pluginfile.php/123/lecture_1.pdf") == ".pdf"

    def test_pptx_url(self):
        assert extract_extension("https://moodle.au/pluginfile.php/124/slides.pptx") == ".pptx"

    def test_url_with_query(self):
        assert extract_extension("https://moodle.au/file.pdf?forcedownload=1") == ".pdf"

    def test_url_without_extension(self):
        assert extract_extension("https://moodle.au/mod/resource/view.php?id=1") == ".pdf"

    def test_uppercase_extension(self):
        assert extract_extension("https://moodle.au/file.PDF") == ".pdf"
