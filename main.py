#!/usr/bin/env python3
"""
downloader

用法 / Usage:
      python main.py                    自动登录 → 列出课程 → 选择下载
                                        login → list courses → pick & download
      python main.py 98120              直接下载课程 98120
                                        download course 98120 directly
      python main.py --browser chrome   指定浏览器 / browser (chrome / edge / firefox)
      python main.py --lang en          界面语言 / UI language (zh / en)

学习 / Agent 集成（操作已下载的本地课件，无需登录）:
Study / agent integration (works on already-downloaded files, no login):
      python main.py --index [目录]      建立本地课件索引 / build a local index
      python main.py --obsidian <目录>   导出 Obsidian 知识库 / export an Obsidian vault
      python main.py --notebook <文件>   生成复习 notebook / build a revision notebook
      python -m moodle_scraper.mcp_server  给 AI agent 用的 MCP 服务 / MCP server for AI agents
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
    """统一的崩溃画面 — 红框报错 + 等用户按回车再关（双语，包不可用时也能显示）"""
    border = "=" * 60
    print()
    print(border)
    print("  💥 程序异常终止 / Program terminated unexpectedly")
    print(border)
    print()
    print(info)
    print()
    print(border)
    print("  如需帮助，请检查 / Troubleshooting:")
    print("    1. pip install -r requirements.txt")
    print("    2. WebDriver 是否安装 / Is a WebDriver installed?")
    print("    3. 网络是否正常 / Is the network OK?")
    print(border)
    print()
    try:
        input("  按 Enter 键退出... / Press Enter to exit...")
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
        lang = ""
        study_root = None
        export_vault_dir = None
        notebook_path = None
        days = 7
        overwrite = False
        copy_files = False
        args = sys.argv[1:]

        def _opt_value(idx):
            """取下一个参数值；若缺失或是另一个选项则返回 None"""
            if idx + 1 < len(args) and not args[idx + 1].startswith("--"):
                return args[idx + 1]
            return None

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
            elif args[i] == "--lang" and i + 1 < len(args):
                lang = args[i + 1]
                i += 2
            elif args[i] == "--index":
                # 目录可选，缺省为当前目录
                value = _opt_value(i)
                study_root = value if value else "."
                i += 2 if value else 1
            elif args[i] == "--obsidian" and i + 1 < len(args):
                export_vault_dir = args[i + 1]
                i += 2
            elif args[i] == "--notebook" and i + 1 < len(args):
                notebook_path = args[i + 1]
                i += 2
            elif args[i] == "--days" and i + 1 < len(args):
                days = int(args[i + 1])
                i += 2
            elif args[i] == "--overwrite":
                overwrite = True
                i += 1
            elif args[i] == "--copy-files":
                copy_files = True
                i += 1
            elif args[i] == "--help":
                print(__doc__)
                try:
                    input("\n  按 Enter 键退出... / Press Enter to exit...")
                except (EOFError, KeyboardInterrupt):
                    pass
                sys.exit(0)
            elif not args[i].startswith("--"):
                course_id = args[i]
                i += 1
            else:
                print(f"未知参数 / Unknown argument: {args[i]}")
                input("\n  按 Enter 键退出... / Press Enter to exit...")
                sys.exit(1)

        main(
            course_id=course_id,
            workers=workers,
            discover_range=discover_range,
            browser=browser,
            lang=lang,
            study_root=study_root,
            export_vault_dir=export_vault_dir,
            notebook_path=notebook_path,
            days=days,
            overwrite=overwrite,
            copy_files=copy_files,
        )

except SystemExit:
    pass
except KeyboardInterrupt:
    _show_crash("用户中断 (Ctrl+C)")
except Exception:
    _show_crash(traceback.format_exc())
except BaseException as e:
    _show_crash(f"{type(e).__name__}: {e}")
