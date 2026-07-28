"""
study.obsidian — 把课件索引导出成 Obsidian 库

按 "一门课一个文件夹、一份材料一篇笔记" 的结构生成纯 Markdown：

    <vault>/PHYS1231/PHYS1231.md            课程 MOC（Map of Content）
    <vault>/PHYS1231/Week 03/Lecture 3.md   每份材料一篇笔记
    <vault>/PHYS1231/Unsorted/Syllabus.md   解析不出周次的材料
    <vault>/PHYS1231/_attachments/...       仅 copy_files=True 时复制原文件

本模块不产生任何用户可见输出（不 print、不 input），只返回 ExportResult，
由调用方负责展示；单份材料导出失败会被吞掉，不影响其余材料。

⚠️ 免责声明: 本工具仅供学生处理本人已注册课程的课件。
Disclaimer: For students to process their own course materials only.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..utils import sanitize_filename
from .index import CourseIndex, Material


# 附件目录名（课程文件夹内）
ATTACHMENTS_DIRNAME: str = "_attachments"

# 没有周次的材料统一放这个桶
UNSORTED_DIRNAME: str = "Unsorted"

# 所有笔记都会带上的根标签
VAULT_TAG: str = "moodle"

# 单个路径段的最大长度，避免 Windows 上撞 MAX_PATH
_MAX_COMPONENT_LEN: int = 100

# 摘要 callout 里最多放多少字符
_MAX_SUMMARY_CHARS: int = 2000

# "复习要点" 里预留几个空条目
_REVIEW_BULLETS: int = 3

# 合理的周次上限（与 index._MAX_WEEK 对齐），超出视为无周次
_MAX_WEEK: int = 60

# Obsidian 链接语法里会出问题的字符（sanitize_filename 不管这些）
_OBSIDIAN_UNSAFE_RE = re.compile(r"[#^\[\]]+")

# 标签里只允许字母数字和 _ / -
_TAG_UNSAFE_RE = re.compile(r"[^0-9A-Za-z_/-]+")

# Windows 保留设备名，作为文件名会直接创建失败
_WINDOWS_RESERVED: frozenset[str] = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


@dataclass
class ExportResult:
    """一次导出的结果汇总

    - courses:       实际写出的课程数（材料为空的课程会被跳过）
    - notes_written: 真正写入磁盘的笔记数（含每门课的 MOC）
    - skipped:       因已存在且 overwrite=False 而跳过的笔记数（含 MOC）
    - files_copied:  复制到 _attachments 的原文件数
    """
    vault_dir: str
    courses: int
    notes_written: int
    skipped: int
    files_copied: int


@dataclass
class _NoteRef:
    """MOC 里引用一篇笔记所需的信息"""
    week: int | None
    bucket: str                 # "Week 03" / "Unsorted"
    title: str                  # 笔记标题（已清洗）
    target: str                 # vault 内相对路径，不含 .md，用 / 分隔
    kind: str


def export_vault(
    index: CourseIndex,
    vault_dir: str | Path,
    *,
    overwrite: bool = False,
    copy_files: bool = False,
) -> ExportResult:
    """
    把索引导出成一个 Obsidian 库

    目录不存在会自动创建；已存在的笔记默认不覆盖（计入 skipped）。
    单门课 / 单份材料出错都会被吞掉，保证其余内容照常导出。

    :param index: 已构建好的课件索引
    :param vault_dir: 目标 vault 目录
    :param overwrite: 是否覆盖已存在的笔记与附件
    :param copy_files: 是否把原文件复制进 <课程>/_attachments
    :returns: ExportResult（vault_dir 为解析后的绝对路径）
    """
    vault_path = Path(vault_dir).expanduser()
    try:
        vault_path = vault_path.resolve()
    except OSError:
        pass

    result = ExportResult(
        vault_dir=str(vault_path),
        courses=0,
        notes_written=0,
        skipped=0,
        files_copied=0,
    )

    try:
        vault_path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return result

    for course_name in index.course_names():
        materials = index.courses.get(course_name) or []
        if not materials:
            continue                      # 空课程不产生任何文件
        try:
            _export_course(
                vault_path, course_name, materials,
                overwrite=overwrite, copy_files=copy_files, result=result,
            )
        except Exception:
            continue                      # 单门课失败不影响其余课程

    return result


# ─── 内部函数 ───────────────────────────────────────────────

def _export_course(
    vault_path: Path,
    course_name: str,
    materials: list[Material],
    *,
    overwrite: bool,
    copy_files: bool,
    result: ExportResult,
) -> None:
    """导出一门课（就地累加 result 的计数）"""
    course_title = _safe_component(course_name, "Course")
    course_dir = vault_path / course_title
    course_dir.mkdir(parents=True, exist_ok=True)

    used: set[str] = set()
    refs: list[_NoteRef] = []

    for material in materials:
        try:
            ref = _export_material(
                material, course_dir, course_title,
                overwrite=overwrite, copy_files=copy_files,
                used=used, result=result,
            )
        except Exception:
            continue                      # 单份材料失败不影响其余材料
        if ref is not None:
            refs.append(ref)

    moc_path = course_dir / f"{course_title}.md"
    _write_note(moc_path, _render_moc(course_title, refs),
                overwrite=overwrite, result=result)

    result.courses += 1


def _export_material(
    material: Material,
    course_dir: Path,
    course_title: str,
    *,
    overwrite: bool,
    copy_files: bool,
    used: set[str],
    result: ExportResult,
) -> _NoteRef | None:
    """导出一份材料，返回它在 MOC 里的引用信息"""
    week = _normal_week(material.week)
    bucket = _week_dirname(week)
    bucket_dir = course_dir / bucket
    bucket_dir.mkdir(parents=True, exist_ok=True)

    fallback = Path(material.path).stem if material.path else ""
    title = _unique_title(
        _safe_component(material.name or fallback, "Untitled"), bucket, used
    )

    attachment: str | None = None
    if copy_files:
        attachment, copied = _copy_attachment(material, course_dir, overwrite=overwrite)
        if copied:
            result.files_copied += 1

    note_path = bucket_dir / f"{title}.md"
    _write_note(
        note_path,
        _render_note(material, course_title, title, week, attachment),
        overwrite=overwrite, result=result,
    )

    return _NoteRef(
        week=week,
        bucket=bucket,
        title=title,
        target=f"{course_title}/{bucket}/{title}",
        kind=_kind_of(material),
    )


def _write_note(
    path: Path,
    content: str,
    *,
    overwrite: bool,
    result: ExportResult,
) -> None:
    """写一篇笔记；已存在且不允许覆盖时只累加 skipped"""
    if path.exists() and not overwrite:
        result.skipped += 1
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    result.notes_written += 1


def _copy_attachment(
    material: Material,
    course_dir: Path,
    *,
    overwrite: bool,
) -> tuple[str | None, bool]:
    """
    把原文件复制进 <课程>/_attachments

    :returns: (笔记里用的相对路径, 是否真的复制了)；源文件不存在或复制失败返回 (None, False)
    """
    source = Path(material.path) if material.path else None
    try:
        if source is None or not source.is_file():
            return None, False
    except OSError:
        return None, False

    rel = _safe_relpath(material.rel_path or source.name)
    target = course_dir / ATTACHMENTS_DIRNAME / Path(rel)
    link = f"{ATTACHMENTS_DIRNAME}/{rel}"

    try:
        if target.exists() and not overwrite:
            return link, False            # 已经在库里了，直接引用
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(target))
    except (OSError, shutil.Error):
        return None, False

    return link, True


def _render_note(
    material: Material,
    course_title: str,
    title: str,
    week: int | None,
    attachment: str | None,
) -> str:
    """渲染一篇材料笔记的完整 Markdown"""
    lines: list[str] = [
        "---",
        f"title: {_yaml_str(title)}",
        f"course: {_yaml_str(course_title)}",
        f"week: {week if week is not None else 'null'}",
        f"kind: {_yaml_str(_kind_of(material))}",
        f"source: {_yaml_str(material.path)}",
        f"size: {_safe_int(material.size)}",
        f"modified: {_yaml_str(_iso(material.modified))}",
        f"tags: [{', '.join(_note_tags(material, course_title, week))}]",
        "---",
        "",
        f"# {title}",
        "",
        _source_link(material, attachment),
        "",
        "## 复习要点",
        "",
    ]
    lines.extend("- " for _ in range(_REVIEW_BULLETS))
    lines.append("")

    excerpt = (material.text or "").strip()
    if excerpt:
        lines.append("## 摘要")
        lines.append("")
        lines.extend(_callout(excerpt))
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"[[{course_title}]]")
    lines.append("")
    return "\n".join(lines)


def _render_moc(course_title: str, refs: list[_NoteRef]) -> str:
    """渲染课程 MOC：统计 + 按周次分组的 wikilink 清单"""
    lines: list[str] = [
        "---",
        f"title: {_yaml_str(course_title)}",
        f"course: {_yaml_str(course_title)}",
        "type: course-moc",
        f"materials: {len(refs)}",
        f"generated: {_yaml_str(_now_iso())}",
        f"tags: [{VAULT_TAG}, {_tag(course_title) or 'course'}, moc]",
        "---",
        "",
        f"# {course_title}",
        "",
        f"共 {len(refs)} 份材料。",
        "",
        "## 材料统计",
        "",
        "| 类型 | 数量 |",
        "| --- | --- |",
    ]

    counts: dict[str, int] = {}
    for ref in refs:
        counts[ref.kind] = counts.get(ref.kind, 0) + 1
    for kind, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {kind} | {count} |")

    lines.append("")
    lines.append("## 材料索引")
    lines.append("")

    for bucket, bucket_refs in _group_by_bucket(refs):
        lines.append(f"### {bucket}")
        lines.append("")
        for ref in sorted(bucket_refs, key=lambda r: r.title.lower()):
            lines.append(f"- [[{ref.target}|{ref.title}]]")
        lines.append("")

    return "\n".join(lines)


def _group_by_bucket(refs: list[_NoteRef]) -> list[tuple[str, list[_NoteRef]]]:
    """按周次桶分组，周次升序、Unsorted 垫底"""
    buckets: dict[str, list[_NoteRef]] = {}
    order: dict[str, tuple[int, int]] = {}

    for ref in refs:
        buckets.setdefault(ref.bucket, []).append(ref)
        order[ref.bucket] = (1, 0) if ref.week is None else (0, ref.week)

    return [(name, buckets[name]) for name in sorted(buckets, key=lambda n: order[n])]


def _source_link(material: Material, attachment: str | None) -> str:
    """指向原文件的嵌入（已复制）或 Markdown 链接（未复制）"""
    if attachment:
        return f"![[{attachment}]]"

    if not material.path:
        return "*(源文件路径缺失)*"

    display = Path(material.path).name or f"{material.name}{material.ext}"
    return f"[{display}](<{Path(material.path).as_posix()}>)"


def _callout(excerpt: str) -> list[str]:
    """把提取到的正文包成 Obsidian callout"""
    body = excerpt[:_MAX_SUMMARY_CHARS]
    lines = ["> [!summary] 自动提取的正文摘录"]
    lines.extend(f"> {line}".rstrip() for line in (body.splitlines() or [""]))
    return lines


def _note_tags(material: Material, course_title: str, week: int | None) -> list[str]:
    """笔记标签：moodle / 课程 / 类型 / 周次"""
    candidates = [VAULT_TAG, _tag(course_title), _tag(_kind_of(material))]
    if week is not None:
        candidates.append(f"week-{week:02d}")

    tags: list[str] = []
    for tag in candidates:
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _tag(value: str) -> str:
    """清洗成合法的 Obsidian 标签（纯数字前面补 _，否则 Obsidian 不认）"""
    tag = _TAG_UNSAFE_RE.sub("-", value or "").strip("-/")
    if not tag:
        return ""
    if tag.isdigit():
        tag = f"_{tag}"
    return tag


def _safe_component(name: str, fallback: str) -> str:
    """把任意字符串清洗成可用作 Windows 文件夹 / 笔记名的单个路径段"""
    if not (name or "").strip():
        return fallback

    cleaned = _OBSIDIAN_UNSAFE_RE.sub("_", sanitize_filename(name))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if len(cleaned) > _MAX_COMPONENT_LEN:
        cleaned = cleaned[:_MAX_COMPONENT_LEN].strip(" .")
    if not cleaned:
        return fallback
    if cleaned.upper() in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned


def _safe_filename(name: str) -> str:
    """同 _safe_component，但保留扩展名（截断只砍主干）"""
    raw = Path(name or "")
    suffix = _OBSIDIAN_UNSAFE_RE.sub("_", sanitize_filename(raw.suffix)) if raw.suffix else ""
    stem = _safe_component(raw.stem, "attachment")
    return f"{stem}{suffix}"


def _safe_relpath(rel_path: str) -> str:
    """清洗附件的相对路径（逐段清洗，丢掉 . 与 ..）"""
    parts = [p for p in re.split(r"[\\/]+", rel_path or "") if p not in ("", ".", "..")]
    if not parts:
        return "attachment"

    safe = [_safe_component(p, "part") for p in parts[:-1]]
    safe.append(_safe_filename(parts[-1]))
    return "/".join(safe)


def _unique_title(title: str, bucket: str, used: set[str]) -> str:
    """同一个桶里重名时追加 (2)/(3)，避免互相覆盖"""
    key = f"{bucket}/{title.lower()}"
    if key not in used:
        used.add(key)
        return title

    index = 2
    while True:
        candidate = f"{title} ({index})"
        candidate_key = f"{bucket}/{candidate.lower()}"
        if candidate_key not in used:
            used.add(candidate_key)
            return candidate
        index += 1


def _normal_week(week: object) -> int | None:
    """把 Material.week 归一化成 0..60 的整数，越界 / 非法一律当作无周次"""
    if week is None or isinstance(week, bool):
        return None
    try:
        value = int(week)                                # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= _MAX_WEEK else None


def _week_dirname(week: int | None) -> str:
    """周次 → 文件夹名"""
    return UNSORTED_DIRNAME if week is None else f"Week {week:02d}"


def _kind_of(material: Material) -> str:
    """材料类型，缺失时回退 other"""
    return (material.kind or "").strip() or "other"


def _safe_int(value: object) -> int:
    """尽力转成 int，失败给 0"""
    try:
        return int(value)                                # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _iso(timestamp: float) -> str:
    """mtime → ISO 8601（UTC）；非法值返回空串"""
    try:
        return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat()
    except (OSError, OverflowError, TypeError, ValueError):
        return ""


def _now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串"""
    return datetime.now(timezone.utc).isoformat()


def _yaml_str(value: str) -> str:
    """转成带引号的 YAML 标量（换行压成空格）"""
    text = str(value or "").replace("\\", "\\\\").replace('"', '\\"')
    text = re.sub(r"[\r\n]+", " ", text)
    return f'"{text}"'
