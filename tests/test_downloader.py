"""
测试 Downloader — 用 FakeHttpClient 模拟文件流下载
"""
from __future__ import annotations

import os
import tempfile

from moodle_scraper.http import FakeHttpClient, HttpResponse
from moodle_scraper.scanner import Resource
from moodle_scraper.downloader import Downloader, DownloadResult


class TestDownloader:
    """Downloader 负责并行下载与跳过已存在"""

    def test_download_single_file(self, tmp_path):
        fake = FakeHttpClient()
        fake.add_stream("https://example.com/file.pdf", [b"pdf content"])
        dl = Downloader(fake, save_dir=str(tmp_path))
        result = dl.download_all([Resource("test_file", "https://example.com/file.pdf")])
        assert result.new_count == 1
        assert result.total == 1
        assert result.skipped == 0
        assert len(result.failed) == 0
        # verify file written
        files = os.listdir(tmp_path)
        assert any("test_file" in f for f in files)

    def test_download_skips_existing(self, tmp_path):
        fake = FakeHttpClient()
        fake.add_stream("https://example.com/file.pdf", [b"content"])
        # Create the file first
        file_path = os.path.join(tmp_path, "existing.pdf")
        with open(file_path, "w") as f:
            f.write("old")

        dl = Downloader(fake, save_dir=str(tmp_path))
        result = dl.download_all([Resource("existing", "https://example.com/file.pdf")])
        assert result.new_count == 0
        assert result.skipped == 1

    def test_download_multiple_files(self, tmp_path):
        fake = FakeHttpClient()
        fake.add_stream("https://a.com/1", [b"one"])
        fake.add_stream("https://b.com/2", [b"two"])
        dl = Downloader(fake, save_dir=str(tmp_path), max_workers=2)
        resources = [
            Resource("file_a", "https://a.com/1"),
            Resource("file_b", "https://b.com/2"),
        ]
        result = dl.download_all(resources)
        assert result.new_count == 2
        assert result.skipped == 0

    def test_download_partial_failure(self, tmp_path):
        fake = FakeHttpClient()
        fake.add_stream("https://ok.com/f", [b"ok"])
        # Don't register the second URL → stream returns empty → treated as failure
        ok = Resource("ok_file", "https://ok.com/f")
        fail = Resource("fail_file", "https://fail.com/f")
        dl = Downloader(fake, save_dir=str(tmp_path))
        result = dl.download_all([ok, fail])
        assert result.new_count == 1
        assert len(result.failed) == 1

    def test_download_result_dataclass(self):
        r = DownloadResult(new_count=3, total=10, skipped=5, failed=["a", "b"])
        assert r.new_count + r.skipped + len(r.failed) == 10
