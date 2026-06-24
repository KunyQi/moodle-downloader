"""
downloader — UI 界面

⚠️ 免责声明: 本工具仅供学生下载本人已注册课程的课件。
Disclaimer: For students to download their own course materials only.
"""
from __future__ import annotations

import sys

# Windows GBK 终端下确保 Rich 能输出 UTF-8 emoji
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text

from .config import AppConfig

console = Console()

# ─── 颜色常量 ──────────────────────────────────────────────
C_PRIMARY   = "deep_sky_blue1"
C_SUCCESS   = "green1"
C_DANGER    = "red1"
C_WARN      = "gold1"
C_MUTED     = "grey66"
C_ACCENT    = "medium_purple1"
C_BORDER    = "steel_blue"


class RichUI:
    """提供 Rich 驱动的终端界面组件"""

    def __init__(self, config: AppConfig):
        self.config = config

    # ═════════════════════════════════════════════════════════
    # 欢迎画面
    # ═════════════════════════════════════════════════════════

    def welcome(self) -> None:
        """显示启动欢迎面板"""
        header = Text("downloader", style=f"bold {C_PRIMARY}")
        sub = Text(
            f"课程  {self.config.course_name}   ·   ID  {self.config.course_id}   ·   "
            f"并行  {self.config.max_workers} 线程   ·   保存至  {self.config.save_dir}/",
            style=C_MUTED,
        )
        panel = Panel(
            Align.center(Group(header, sub)),
            border_style=C_BORDER,
            box=box.HEAVY,
            padding=(1, 3),
        )
        console.print()
        console.print(panel)
        console.print()

    # ═════════════════════════════════════════════════════════
    # 状态消息
    # ═════════════════════════════════════════════════════════

    _ICON_STYLE = {
        "✅": C_SUCCESS, "❌": f"bold {C_DANGER}",
        "⚠️": C_WARN,    "🔑": f"bold {C_WARN}",
        "👉": C_PRIMARY, "⏳": C_MUTED,
        "🌐": C_PRIMARY, "🕳️": C_ACCENT,
        "📦": C_PRIMARY, "⏩": C_MUTED,
        "😎": C_SUCCESS, "✨": f"bold {C_SUCCESS}",
        "💥": f"bold {C_DANGER}", "🗑️": C_WARN,
        "🚀": C_PRIMARY, "🔄": C_PRIMARY,
        "📋": f"bold {C_PRIMARY}", "🔍": C_PRIMARY,
        "📌": f"bold {C_WARN}",   "👋": C_MUTED,
        "📥": C_SUCCESS,
    }

    def status(self, emoji: str, message: str) -> None:
        """彩色状态消息"""
        style = self._ICON_STYLE.get(emoji, "white")
        console.print(f"  {emoji}  [{style}]{message}[/]")

    # ═════════════════════════════════════════════════════════
    # 进度条（download 和 discover 共享）
    # ═════════════════════════════════════════════════════════

    def create_progress(self) -> Progress:
        """带 spinner + 进度条 + 百分比 + 时间的完整组件"""
        return Progress(
            SpinnerColumn("dots2", style=f"bold {C_PRIMARY}"),
            TextColumn("[progress.description]{task.description}", style="white"),
            BarColumn(
                bar_width=36,
                style=f"{C_MUTED}",
                complete_style=f"bold {C_SUCCESS}",
                finished_style=C_SUCCESS,
                pulse_style=C_PRIMARY,
            ),
            TaskProgressColumn(style=C_PRIMARY),
            " · ",
            TimeElapsedColumn(),
            " ─ ",
            TimeRemainingColumn(),
            console=console,
            expand=False,
        )

    # ═════════════════════════════════════════════════════════
    # 扫描结果表格
    # ═════════════════════════════════════════════════════════

    def show_scan_results(self, items: list) -> None:
        """文件列表表格：序号 + 文件名 + 类型图标"""
        if not items:
            return
        console.print()
        table = Table(
            title=f"📂  发现  {len(items)}  个文件",
            title_style=f"bold {C_PRIMARY}",
            border_style=C_BORDER,
            box=box.ROUNDED,
            row_styles=["", "dim"],
            header_style=f"bold {C_PRIMARY}",
        )
        table.add_column("#", style=C_MUTED, width=4, justify="right")
        table.add_column("文件名", style="white", min_width=30)
        table.add_column("状态", style=C_MUTED, width=10)

        for i, item in enumerate(items, 1):
            name = item.name if hasattr(item, "name") else item["name"]
            icon = self._file_icon(name)
            if i > 20:
                break
            table.add_row(str(i), f"{icon}  {name}", "待下载")

        remaining = len(items) - 20
        if remaining > 0:
            table.add_row("", f"[dim]… 还有 {remaining} 个文件[/]", "")

        console.print(table)

    @staticmethod
    def _file_icon(name: str) -> str:
        n = name.lower()
        # 精确匹配优先（避免 "syllabus" 匹配到 "lab"）
        if "syllabus" in n or "outline" in n:
            return "📋"
        if "lab" in n or "manual" in n:
            return "🔬"
        if "lecture" in n or "lec " in n or " week" in n or "slide" in n:
            return "📖"
        if "homework" in n or "problem" in n or " set " in n or "solution" in n:
            return "📝"
        if "note" in n or "course note" in n:
            return "📒"
        if "formula" in n or "sheet" in n:
            return "🧮"
        if "ppt" in n or "presentation" in n:
            return "📊"
        return "📄"

    # ═════════════════════════════════════════════════════════
    # 下载汇总仪表盘
    # ═════════════════════════════════════════════════════════

    def download_summary(self, new_count: int, total: int, failed: list[str]) -> None:
        """下载摘要仪表盘 — 卡片式统计"""
        console.print()
        skipped = max(0, total - new_count - len(failed))

        cards = [
            self._stat_card("📦 总目标", str(total), C_MUTED),
            self._stat_card("✅ 新增", str(new_count), C_SUCCESS),
            self._stat_card("⏩ 已有", str(skipped), C_WARN),
        ]
        if failed:
            cards.append(self._stat_card("❌ 失败", str(len(failed)), C_DANGER))

        panel = Panel(
            Columns(cards, equal=True, expand=True),
            title="下载报告",
            title_align="center",
            border_style=C_BORDER,
            box=box.ROUNDED,
            padding=(1, 2),
        )
        console.print(panel)

        if failed:
            console.print()
            fail_table = Table(box=box.SIMPLE, show_header=False, border_style=C_DANGER)
            fail_table.add_column(style=f"bold {C_DANGER}")
            for f in failed:
                fail_table.add_row(f"  ✗  {f}")
            console.print(Panel(fail_table, title="失败列表", border_style=C_DANGER, box=box.ROUNDED))

    def _stat_card(self, label: str, value: str, color: str) -> RenderableType:
        """单个统计卡片"""
        return Align.center(
            Group(
                Text(label, style=C_MUTED),
                Text(value, style=f"bold {color}"),
            ),
            vertical="middle",
        )

    # ═════════════════════════════════════════════════════════
    # 结果横幅
    # ═════════════════════════════════════════════════════════

    def result_banner(self, new_count: int) -> None:
        """下载完成横幅"""
        console.print()
        console.print(Rule(style=C_BORDER))
        console.print()
        if new_count == 0:
            msg = Text("🎉  资料已是最新，无需更新！", style=f"bold {C_SUCCESS}", justify="center")
        else:
            msg = Text(
                f"🎉  成功新增  {new_count}  个文件",
                style=f"bold {C_SUCCESS}",
                justify="center",
            )
        console.print(Align.center(msg))
        console.print()
        console.print(Rule(style=C_BORDER))

    # ═════════════════════════════════════════════════════════
    # 专业仪表盘
    # ═════════════════════════════════════════════════════════

    def dashboard(
        self,
        *,
        status: str = "初始化",
        status_color: str = C_MUTED,
        course_count: Optional[int] = None,
    ) -> None:
        """启动仪表盘 — 版本号 + 状态 + 统计 + 操作提示"""
        from datetime import datetime

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # ── 顶部标题 ──
        header = Panel(
            Align.center(
                Group(
                    Text("downloader", style=f"bold {C_PRIMARY}"),
                    Text(f"v2.0.0", style=C_MUTED),
                ),
            ),
            border_style=C_BORDER,
            box=box.HEAVY,
            padding=(1, 3),
        )

        # ── 中间状态栏 ──
        status_text = Text.assemble(
            (f"  ●  {status}", f"bold {status_color}"),
            ("  │  ", C_MUTED),
            (now, C_MUTED),
            ("  │  ", C_MUTED),
            (f"{self.config.max_workers} 线程", C_PRIMARY),
        )

        middle = Panel(
            Align.left(status_text),
            border_style=C_MUTED,
            box=box.ROUNDED,
            padding=(1, 2),
        )

        # ── 底部操作指引 ──
        help_text = Text("  \u23ce  按 Enter 键继续  ", style=C_MUTED)
        bottom = Panel(
            Align.center(help_text),
            border_style=C_BORDER,
            box=box.SIMPLE,
            padding=(1, 2),
        )

        console.clear()
        console.print()
        console.print(header)
        console.print(middle)

        if course_count is not None:
            stats = Panel(
                Align.center(
                    Group(
                        Text(f"📚 可访问 {course_count} 门课程", style=f"bold {C_SUCCESS}"),
                        Text(f"保存至 {self.config.save_dir}/", style=C_MUTED),
                    ),
                ),
                border_style=C_BORDER,
                box=box.SIMPLE,
                padding=(1, 2),
            )
            console.print(stats)

        console.print(bottom)

    def show_error(self, title: str, detail: str) -> None:
        """红色错误面板"""
        console.print()
        console.print(
            Panel(
                Group(Text(title, style=f"bold {C_DANGER}"), Text(detail, style=C_MUTED)),
                border_style=C_DANGER,
                box=box.HEAVY,
                padding=(1, 2),
            )
        )
