"""
downloader — 工具函数

⚠️ 免责声明: 本工具仅供学生下载本人已注册课程的课件。
Disclaimer: For students to download their own course materials only.
"""
from __future__ import annotations

import re


def sanitize_filename(filename: str) -> str:
    """清理文件名中的非法字符，确保可安全写入磁盘"""
    name = filename.replace("File", "").strip()
    if not name:
        name = "Unnamed_Resource"
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def extract_extension(url: str, default: str = ".pdf") -> str:
    """从下载 URL 中提取文件扩展名（如 .pdf、.pptx）"""
    path = url.split("?")[0]          # 去掉 query 参数
    filename = path.rstrip("/").split("/")[-1]
    if "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
        # 跳过 PHP/HTML 等非文件类扩展名
        if ext not in {"php", "html", "htm", "asp", "aspx", "jsp"}:
            return f".{ext}"
    return default


def is_login_page(url: str, html_text: str) -> bool:
    """判断响应是否重定向到了登录页"""
    return "login" in url.lower() or "Log in" in html_text
