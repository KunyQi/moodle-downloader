"""
downloader — 下载模块

⚠️ 免责声明: 本工具仅供学生下载本人已注册课程的课件。
Disclaimer: For students to download their own course materials only.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional

from .http import HttpClient
from .i18n import t
from .scanner import Resource
from .utils import extract_extension, sanitize_filename


@dataclass
class DownloadResult:
    """下载结果汇总"""
    new_count: int = 0
    total: int = 0
    skipped: int = 0
    failed: list[str] = field(default_factory=list)


class Downloader:
    """资源文件下载器（支持跳过已存在 + 并行下载）"""

    def __init__(
        self,
        client: HttpClient,
        *,
        save_dir: str = "downloads",
        max_workers: int = 4,
        chunk_size: int = 8192,
        on_progress: Optional[Callable] = None,
    ):
        self._client = client
        self._save_dir = save_dir
        self._max_workers = max_workers
        self._chunk_size = chunk_size
        self._on_progress = on_progress or (lambda c, t, m: None)

    def download_all(self, resources: list[Resource]) -> DownloadResult:
        """
        并行下载资源列表

        :param resources: 待下载的资源列表
        :returns: DownloadResult 汇总
        """
        os.makedirs(self._save_dir, exist_ok=True)

        # 过滤已存在的文件
        to_download: list[tuple[Resource, str]] = []
        skip_count = 0

        for res in resources:
            safe_name = sanitize_filename(res.name)
            ext = extract_extension(res.url)
            path = os.path.join(self._save_dir, f"{safe_name}{ext}")
            if os.path.exists(path):
                skip_count += 1
            else:
                to_download.append((res, path))

        total = len(to_download)
        if total == 0:
            return DownloadResult(total=len(resources), skipped=skip_count)

        self._on_progress(
            0, total,
            "📦 " + t(
                "downloader.queue_summary",
                total=len(resources), existing=skip_count, pending=total,
            ),
        )

        new_count = 0
        failed_names: list[str] = []

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            fut_map = {
                executor.submit(self._download_one, res, path): res
                for res, path in to_download
            }

            done = 0
            for future in as_completed(fut_map):
                res = fut_map[future]
                done += 1
                try:
                    ok = future.result()
                    if ok:
                        new_count += 1
                    else:
                        failed_names.append(res.name)
                except Exception:
                    failed_names.append(res.name)
                self._on_progress(
                    done, total,
                    "⏳ " + t("downloader.progress", done=done, total=total, ok=new_count),
                )

        return DownloadResult(
            new_count=new_count,
            total=len(resources),
            skipped=skip_count,
            failed=failed_names,
        )

    def _download_one(self, resource: Resource, path: str) -> bool:
        """下载单个资源到指定路径（先写 .part 临时文件，成功再重命名）"""
        part_path = path + ".part"
        try:
            with open(part_path, "wb") as f:
                for chunk in self._client.get_stream(
                    resource.url,
                    timeout=30,
                    chunk_size=self._chunk_size,
                ):
                    f.write(chunk)
            os.replace(part_path, path)  # 原子操作，不会留下残片
            return True
        except Exception:
            if os.path.exists(part_path):
                os.remove(part_path)  # 清理残片
            return False
