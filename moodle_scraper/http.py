"""
downloader — HTTP 适配器层

⚠️ 免责声明: 本工具仅供学生下载本人已注册课程的课件。
Disclaimer: For students to download their own course materials only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Optional, Protocol

import requests


@dataclass
class HttpResponse:
    """统一的 HTTP 响应（不暴露 requests 内部）"""
    status_code: int
    text: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)


class HttpClient(Protocol):
    """HTTP 客户端协议 — 扫描和下载都依赖此 seam"""

    def get(self, url: str, *, timeout: int = 30) -> HttpResponse:
        """普通 GET 请求，返回完整响应"""
        ...

    def get_stream(
        self, url: str, *, timeout: int = 30, chunk_size: int = 8192
    ) -> Iterator[bytes]:
        """流式 GET，用于文件下载"""
        ...


class RequestsHttpClient:
    """生产适配器 — 基于 requests.Session"""

    def __init__(self, user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edge/120.0.0.0"):
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})

    def set_cookies(self, cookies: dict[str, str]) -> None:
        """注入认证 cookie"""
        self._session.cookies.update(cookies)

    def get(self, url: str, *, timeout: int = 30) -> HttpResponse:
        resp = self._session.get(url, timeout=timeout)
        return HttpResponse(
            status_code=resp.status_code,
            text=resp.text,
            url=resp.url,
            headers=dict(resp.headers),
        )

    def get_stream(
        self, url: str, *, timeout: int = 30, chunk_size: int = 8192
    ) -> Iterator[bytes]:
        with self._session.get(
            url, stream=True, allow_redirects=True, timeout=timeout
        ) as resp:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if chunk:
                    yield chunk


class FakeHttpClient:
    """测试适配器 — 返回预制响应"""

    def __init__(self):
        self._responses: dict[str, HttpResponse] = {}
        self._streams: dict[str, list[bytes]] = {}
        self.request_log: list[tuple[str, str]] = []  # (method, url)

    def add_response(self, url: str, response: HttpResponse) -> None:
        """预制一个 GET 响应"""
        self._responses[url] = response

    def add_stream(self, url: str, chunks: list[bytes]) -> None:
        """预制一个流式响应"""
        self._streams[url] = chunks

    def get(self, url: str, *, timeout: int = 30) -> HttpResponse:
        self.request_log.append(("GET", url))
        # 支持 URL 前缀匹配（含 query 参数的情况）
        for key in sorted(self._responses, key=len, reverse=True):
            if url.startswith(key):
                return self._responses[key]
        # 兜底：匹配 path 部分
        for key, resp in self._responses.items():
            if key in url:
                return resp
        return HttpResponse(404, "", url)

    def get_stream(
        self, url: str, *, timeout: int = 30, chunk_size: int = 8192
    ) -> Iterator[bytes]:
        self.request_log.append(("STREAM", url))
        for key in sorted(self._streams, key=len, reverse=True):
            if url.startswith(key):
                yield from self._streams[key]
                return
        raise RuntimeError(f"FakeHttpClient: no stream registered for {url}")
