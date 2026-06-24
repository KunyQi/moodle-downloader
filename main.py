#!/usr/bin/env python3
"""
downloader

用法:
      python main.py                    自动登录 → 列出课程 → 选择下载
      python main.py 98120              直接下载课程 98120
      python main.py --browser chrome   指定浏览器 (chrome / edge / firefox)
"""
import sys
import traceback

# ── 最早执行：Windows GBK 终端编码修复 ─────────────────
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _show_crash(info: str) -> None:
    """统一的崩溃画面 — 红框报错 + 等用户按回车再关"""
    border = "=" * 60
    print()
    print(border)
    print("  💥 程序异常终止")
    print(border)
    print()
    print(info)
    print()
    print(border)
    print("  如需帮助，请检查:")
    print("    1. pip install -r requirements.txt")
    print("    2. Edge WebDriver 是否安装")
    print("    3. 网络是否正常")
    print(border)
    print()
    try:
        input("  按 Enter 键退出...")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
# 最后一堵墙：任何错误都停在这，绝不闪退
# ═══════════════════════════════════════════════════════════════
try:
    try:
        from moodle_scraper.__main__ import main
    except ModuleNotFoundError as e:
        missing = str(e).split("'")[1] if "'" in str(e) else str(e)
        _show_crash(
            f"缺少依赖模块: {missing}\n\n"
            f"请运行: pip install -r requirements.txt"
        )
        sys.exit(1)

    if __name__ == "__main__":
        course_id = None
        workers = None
        discover_range = None
        browser = ""
        args = sys.argv[1:]

        i = 0
        while i < len(args):
            if args[i] == "--discover" and i + 1 < len(args):
                # --discover 需跟范围参数，不公开在 help 中
                discover_range = args[i + 1]
                i += 2
            elif args[i] == "--browser" and i + 1 < len(args):
                browser = args[i + 1]
                i += 2
            elif args[i] == "--workers" and i + 1 < len(args):
                workers = int(args[i + 1])
                i += 2
            elif args[i] == "--help":
                print(__doc__)
                try:
                    input("\n  按 Enter 键退出...")
                except (EOFError, KeyboardInterrupt):
                    pass
                sys.exit(0)
            elif not args[i].startswith("--"):
                course_id = args[i]
                i += 1
            else:
                print(f"未知参数: {args[i]}")
                input("\n  按 Enter 键退出...")
                sys.exit(1)

        main(
            course_id=course_id,
            workers=workers,
            discover_range=discover_range,
            browser=browser,
        )

except SystemExit:
    pass
except KeyboardInterrupt:
    _show_crash("用户中断 (Ctrl+C)")
except Exception:
    _show_crash(traceback.format_exc())
except BaseException as e:
    _show_crash(f"{type(e).__name__}: {e}")
