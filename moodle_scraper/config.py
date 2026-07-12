"""
downloader — 配置管理

⚠️ 免责声明: 本工具仅供学生下载本人已注册课程的课件。
Disclaimer: For students to download their own course materials only.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# 默认配置文件路径（项目根目录）
CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.toml"


@dataclass
class AppConfig:
    """应用配置"""
    # 课程
    course_id: str = ""
    course_name: str = ""

    # 路径
    save_dir: str = "downloads"
    cookie_file: str = "moodle_cookies.json"

    # 网络
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edge/120.0.0.0"
    request_timeout: int = 30
    download_chunk_size: int = 8192

    # 并行下载
    max_workers: int = 24

    # Selenium 登录
    login_timeout: int = 300
    login_check_interval: float = 1.0

    # 文件过滤
    file_keywords: list[str] = field(default_factory=lambda: ["lecture"])
    file_extensions: list[str] = field(default_factory=lambda: [".pdf", ".ppt", ".pptx"])

    # 界面
    theme: str = "default"
    language: str = "zh"  # 界面语言 / UI language: "zh" 或 "en"

    # 浏览器（留空 = 自动检测）
    browser: str = ""

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        """从 TOML 文件加载配置，缺失字段使用默认值"""
        cfg_path = path or CONFIG_FILE
        cfg = cls()

        if not cfg_path.exists():
            return cfg

        try:
            with open(cfg_path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            return cfg

        # 映射 TOML 字段到 dataclass 字段
        section_map = {
            "course": ["course_id", "course_name"],
            "paths": ["save_dir", "cookie_file"],
            "network": ["user_agent", "request_timeout", "download_chunk_size"],
            "download": ["max_workers"],
            "auth": ["login_timeout", "login_check_interval"],
            "filters": ["file_keywords", "file_extensions"],
            "ui": ["theme", "language"],
            "browser": ["browser"],
        }

        for section, fields in section_map.items():
            if section in data:
                for key in fields:
                    if key in data[section]:
                        setattr(cfg, key, data[section][key])

        return cfg

    def ensure_dirs(self) -> None:
        """确保保存目录存在"""
        os.makedirs(self.save_dir, exist_ok=True)


# 全局单例
config = AppConfig.load()
