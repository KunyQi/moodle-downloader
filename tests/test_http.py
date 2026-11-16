"""
测试 HttpClient seam — FakeHttpClient 的预制响应与调试能力
"""
from __future__ import annotations

from moodle_scraper.http import FakeHttpClient, HttpResponse


class TestHttpResponse:
    """HttpResponse 是简单的数据容器，确保构造正确"""

    def test_basic(self):
        resp = HttpResponse(200, "hello", "https://example.com")
        assert resp.status_code == 200
        assert resp.text == "hello"
        assert resp.url == "https://example.com"

    def test_with_headers(self):
        resp = HttpResponse(301, "", "https://old.com", headers={"Location": "/new"})
        assert resp.headers["Location"] == "/new"


class TestFakeHttpClient:
    """FakeHttpClient 是测试 seam 的核心适配器"""

    def test_get_matches_exact_url(self):
        fake = FakeHttpClient()
        fake.add_response("https://example.com/a", HttpResponse(200, "A", ""))
        fake.add_response("https://example.com/b", HttpResponse(404, "B", ""))

        assert fake.get("https://example.com/a").text == "A"
        assert fake.get("https://example.com/b").status_code == 404

    def test_get_matches_by_prefix(self):
        fake = FakeHttpClient()
        fake.add_response("https://moodle.au/course/", HttpResponse(200, "course page", ""))
        resp = fake.get("https://moodle.au/course/view.php?id=123")
        assert resp.text == "course page"

    def test_get_returns_404_for_unregistered(self):
        fake = FakeHttpClient()
        resp = fake.get("https://unknown.com")
        assert resp.status_code == 404

    def test_get_stream(self):
        fake = FakeHttpClient()
        fake.add_stream("https://example.com/file.pdf", [b"chunk1", b"chunk2"])
        data = b"".join(fake.get_stream("https://example.com/file.pdf"))
        assert data == b"chunk1chunk2"

    def test_get_stream_empty_when_unregistered(self):
        fake = FakeHttpClient()
        import pytest
        with pytest.raises(RuntimeError, match="no stream registered"):
            list(fake.get_stream("https://unknown.com"))

    def test_request_log(self):
        fake = FakeHttpClient()
        fake.add_stream("https://c.com/file", [b"data"])
        fake.get("https://a.com")
        fake.get("https://b.com")
        list(fake.get_stream("https://c.com/file"))
        assert len(fake.request_log) == 3
        assert fake.request_log[0] == ("GET", "https://a.com")
        assert fake.request_log[2] == ("STREAM", "https://c.com/file")


class TestRequestsHttpClientStream:
    """RequestsHttpClient.get_stream 对错误页与登录页的识别（本地服务器，不访问网络）"""

    @staticmethod
    def _serve():
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/login"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<html>Log in</html>")
                elif self.path.startswith("/forbidden"):
                    self.send_response(403)
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.end_headers()
                    self.wfile.write(b"%PDF-1.4 ok")

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, f"http://127.0.0.1:{server.server_port}"

    def test_streams_pdf(self):
        from moodle_scraper.http import RequestsHttpClient
        server, base = self._serve()
        try:
            data = b"".join(RequestsHttpClient().get_stream(f"{base}/ok.pdf"))
            assert data == b"%PDF-1.4 ok"
        finally:
            server.shutdown()

    def test_raises_on_http_error(self):
        import pytest
        import requests
        from moodle_scraper.http import RequestsHttpClient
        server, base = self._serve()
        try:
            with pytest.raises(requests.HTTPError):
                list(RequestsHttpClient().get_stream(f"{base}/forbidden.pdf"))
        finally:
            server.shutdown()

    def test_raises_on_html_login_page(self):
        import pytest
        import requests
        from moodle_scraper.http import RequestsHttpClient
        server, base = self._serve()
        try:
            with pytest.raises(requests.HTTPError, match="session expired"):
                list(RequestsHttpClient().get_stream(f"{base}/login.pdf"))
        finally:
            server.shutdown()
