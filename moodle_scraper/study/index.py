"""
study.index — 本地课件索引

扫描已下载到磁盘的课程目录，构建一个可查询、可序列化的索引：
根目录下的每个一级子目录视为一门课程，直接放在根目录里的文件
归到以根目录名命名的课程下。

本模块不产生任何用户可见输出（不 print、不 input），
只返回 dataclass，由调用方负责展示。

⚠️ 免责声明: 本工具仅供学生处理本人已注册课程的课件。
Disclaimer: For students to process their own course materials only.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# 索引文件的默认文件名（点开头 → 天然会被扫描逻辑跳过）
INDEX_FILENAME: str = ".moodle-index.json"

# 索引格式版本号，方便未来消费方做兼容判断
INDEX_VERSION: int = 1

# 只索引"文档类"扩展名（小写，含点）
DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".ppt", ".pptx", ".doc", ".docx",
    ".txt", ".md", ".csv", ".xlsx",
})

# 可以直接按纯文本读取的扩展名
PLAIN_TEXT_EXTENSIONS: frozenset[str] = frozenset({".txt", ".md", ".csv"})

# 允许尝试抽取文本的扩展名（其余一律留空字符串）
_TEXT_CAPABLE_EXTENSIONS: frozenset[str] = PLAIN_TEXT_EXTENSIONS | {".pdf"}

# 文件类型关键词（按优先级从上到下匹配，命中即停）
_KIND_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("exam", ("exam", "quiz", "midterm", "midsem", "final", "finals")),
    ("assignment", ("assignment", "assign", "assessment", "homework", "hw",
                    "coursework", "project")),
    ("lab", ("lab", "laboratory", "practical", "prac")),
    ("tutorial", ("tutorial", "tut")),
    ("workshop", ("workshop", "seminar")),
    ("lecture", ("lecture", "lect", "lec", "slide", "slides", "topic", "chapter")),
    ("notes", ("note", "notes", "summary", "handout", "reading",
               "reference", "cheatsheet", "revision")),
)

# 周次解析模式（按优先级排列：week > wk > topic > lecture > 单字母缩写）
_WEEK_PATTERNS: tuple[str, ...] = (
    r"\bweeks?\s*0*(\d{1,2})\b",
    r"\bwk\s*0*(\d{1,2})\b",
    r"\btopics?\s*0*(\d{1,2})\b",
    r"\blectures?\s*0*(\d{1,2})\b",
    r"\blec\s*0*(\d{1,2})\b",
    r"\bw\s*0*(\d{1,2})\b",
    r"\bl\s*0*(\d{1,2})\b",
)

# 合理的周次上限，避免把年份 / 学号误判成周次
_MAX_WEEK: int = 60

# 搜索打分权重：文件名 > 课程名 > 正文
_SCORE_NAME: int = 3
_SCORE_COURSE: int = 2
_SCORE_TEXT: int = 1


@dataclass
class Material:
    """磁盘上的一份课件"""
    path: str            # 绝对路径
    rel_path: str        # 相对课程目录（统一用 / 分隔）
    name: str            # 不含扩展名的文件名
    ext: str             # ".pdf"（小写，含点）
    course: str          # 课程文件夹名
    size: int            # 字节
    modified: float      # mtime
    kind: str            # lecture / lab / workshop / tutorial / notes / exam / assignment / other
    week: int | None     # 从文件名解析，解析不到为 None
    text: str = ""       # 提取的文本预览，不可用时为 ""


@dataclass
class CourseIndex:
    """一次扫描得到的完整索引"""
    root: str
    generated_at: str                                        # ISO 8601
    courses: dict[str, list[Material]] = field(default_factory=dict)

    def all_materials(self) -> list[Material]:
        """
        展平所有课程的材料

        :returns: 按课程名、相对路径排序的材料列表
        """
        items: list[Material] = []
        for course in self.course_names():
            items.extend(self.courses.get(course, []))
        return items

    def course_names(self) -> list[str]:
        """:returns: 排序后的课程名列表"""
        return sorted(self.courses.keys(), key=lambda n: n.lower())

    def search(
        self,
        query: str,
        *,
        course: str | None = None,
        limit: int = 20,
    ) -> list[Material]:
        """
        在文件名 / 课程名 / 正文里做不区分大小写的子串搜索

        文件名命中的排在正文命中的前面。

        :param query: 查询串，空串返回空列表
        :param course: 只在该课程内搜索（不区分大小写的精确匹配）
        :param limit: 最多返回条数，<= 0 时不限制
        :returns: 按相关度降序排列的材料列表
        """
        q = (query or "").strip().lower()
        if not q:
            return []

        course_filter = course.strip().lower() if course else None
        scored: list[tuple[int, str, str, Material]] = []

        for item in self.all_materials():
            if course_filter is not None and item.course.lower() != course_filter:
                continue

            score = 0
            if q in item.name.lower():
                score = _SCORE_NAME
            elif q in item.course.lower():
                score = _SCORE_COURSE
            elif item.text and q in item.text.lower():
                score = _SCORE_TEXT

            if score:
                # 次级排序键保证结果稳定可预测
                scored.append((score, item.course.lower(), item.rel_path.lower(), item))

        scored.sort(key=lambda row: (-row[0], row[1], row[2]))
        results = [row[3] for row in scored]
        if limit and limit > 0:
            results = results[:limit]
        return results

    def to_dict(self) -> dict:
        """:returns: 可直接 json.dumps 的字典"""
        return {
            "version": INDEX_VERSION,
            "root": self.root,
            "generated_at": self.generated_at,
            "courses": {
                name: [asdict(m) for m in materials]
                for name, materials in self.courses.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> CourseIndex:
        """
        从 to_dict() 的结果还原索引

        单条损坏的记录会被跳过，不影响其余数据。
        """
        raw_courses = data.get("courses") or {}
        courses: dict[str, list[Material]] = {}

        if isinstance(raw_courses, dict):
            for name, items in raw_courses.items():
                materials: list[Material] = []
                for item in items or []:
                    material = _material_from_dict(item, str(name))
                    if material is not None:
                        materials.append(material)
                courses[str(name)] = materials

        return cls(
            root=str(data.get("root", "")),
            generated_at=str(data.get("generated_at", "")),
            courses=courses,
        )


def build_index(
    root: str | Path,
    *,
    extract_text: bool = True,
    text_chars: int = 2000,
) -> CourseIndex:
    """
    扫描 root 下的课件，构建索引

    每个一级子目录算一门课程（递归收集其中的文件）；直接躺在 root 里的
    文件归到以 root 目录名命名的课程下。点开头的文件/目录、.part 临时文件、
    索引文件本身以及非文档类扩展名都会被跳过。

    :param root: 课件根目录
    :param extract_text: 是否尝试抽取文本预览
    :param text_chars: 每个文件最多抽取多少字符
    :returns: CourseIndex（root 不存在时 courses 为空）
    """
    root_path = Path(root).expanduser()
    try:
        root_path = root_path.resolve()
    except OSError:
        pass

    index = CourseIndex(root=str(root_path), generated_at=_now_iso(), courses={})
    if not root_path.is_dir():
        return index

    try:
        entries = sorted(root_path.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return index

    # 根目录里的散装文件 → 归到以根目录名命名的"课程"
    loose_course = root_path.name or str(root_path)
    loose: list[Material] = []

    for entry in entries:
        try:
            if entry.is_dir():
                if entry.name.startswith("."):
                    continue
                materials = _scan_course_dir(
                    entry, entry.name,
                    extract_text=extract_text, text_chars=text_chars,
                )
                if materials:
                    index.courses[entry.name] = materials
            elif entry.is_file() and _is_indexable(entry.name):
                material = _make_material(
                    entry, root_path, loose_course,
                    extract_text=extract_text, text_chars=text_chars,
                )
                if material is not None:
                    loose.append(material)
        except OSError:
            continue  # 单个条目出错不影响整体

    if loose:
        loose.sort(key=lambda m: m.rel_path.lower())
        index.courses.setdefault(loose_course, []).extend(loose)

    return index


def save_index(index: CourseIndex, path: str | Path) -> None:
    """
    把索引写成 JSON（先写 .part 再原子替换）

    :param index: 待保存的索引
    :param path: 目标文件路径
    """
    target = Path(path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)

    part = target.with_name(target.name + ".part")
    payload = json.dumps(index.to_dict(), ensure_ascii=False, indent=2)
    part.write_text(payload, encoding="utf-8")
    os.replace(str(part), str(target))


def load_index(path: str | Path) -> CourseIndex | None:
    """
    读取 JSON 索引

    :param path: 索引文件路径
    :returns: CourseIndex；文件缺失或内容损坏时返回 None
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    try:
        return CourseIndex.from_dict(data)
    except Exception:
        return None


def detect_kind(filename: str) -> str:
    """
    按文件名关键词猜测材料类型

    :param filename: 文件名（可含扩展名）
    :returns: lecture / lab / workshop / tutorial / notes / exam / assignment / other
    """
    tokens = _tokenize(filename)
    if not tokens:
        return "other"

    for kind, keywords in _KIND_KEYWORDS:
        for token in tokens:
            if any(token.startswith(kw) for kw in keywords):
                return kind
    return "other"


def detect_week(filename: str) -> int | None:
    """
    从文件名解析周次，支持 Week 3 / week03 / Wk 3 / W3 / Topic 3 / Lecture 3 / L3

    :param filename: 文件名（可含扩展名）
    :returns: 周次数字，解析不到返回 None
    """
    normalized = _normalize(filename)
    if not normalized:
        return None

    for pattern in _WEEK_PATTERNS:
        match = re.search(pattern, normalized)
        if match:
            try:
                value = int(match.group(1))
            except ValueError:
                continue
            if 0 <= value <= _MAX_WEEK:
                return value
    return None


def extract_pdf_text(path: str | Path, max_chars: int = 2000) -> str:
    """
    抽取文件的文本预览

    .txt/.md/.csv 直接按 utf-8 读取；.pdf 依次尝试 pypdf、pdfminer，
    两个库都没装或抽取失败时返回空串——本函数永远不抛异常。

    :param path: 文件路径
    :param max_chars: 最多返回多少字符
    :returns: 文本预览，不可用时为 ""
    """
    if max_chars <= 0:
        return ""

    target = Path(path)
    try:
        if not target.is_file():
            return ""
    except OSError:
        return ""

    suffix = target.suffix.lower()

    if suffix in PLAIN_TEXT_EXTENSIONS:
        try:
            return target.read_text(encoding="utf-8", errors="ignore")[:max_chars]
        except (OSError, ValueError):
            return ""

    if suffix != ".pdf":
        return ""

    text = _extract_with_pypdf(target, max_chars)
    if text:
        return text
    return _extract_with_pdfminer(target, max_chars)


# ─── 内部函数 ───────────────────────────────────────────────

def _now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串"""
    return datetime.now(timezone.utc).isoformat()


def _normalize(filename: str) -> str:
    """小写化并把非字母数字统一成空格，便于用 \\b 做词边界匹配"""
    stem = Path(filename).stem if filename else ""
    return re.sub(r"[^0-9a-z]+", " ", stem.lower()).strip()


def _tokenize(filename: str) -> list[str]:
    """把文件名切成小写词元（丢弃扩展名）"""
    normalized = _normalize(filename)
    return normalized.split() if normalized else []


def _is_indexable(filename: str) -> bool:
    """判断一个文件名是否应该进入索引"""
    if not filename or filename.startswith("."):
        return False          # 点文件（含索引文件本身）
    if filename == INDEX_FILENAME:
        return False
    lower = filename.lower()
    if lower.endswith(".part"):
        return False          # 下载残片
    return Path(lower).suffix in DOCUMENT_EXTENSIONS


def _scan_course_dir(
    course_dir: Path,
    course_name: str,
    *,
    extract_text: bool,
    text_chars: int,
) -> list[Material]:
    """递归扫描一门课程目录，返回材料列表"""
    materials: list[Material] = []

    for dirpath, dirnames, filenames in os.walk(str(course_dir)):
        # 就地过滤掉隐藏目录，os.walk 就不会再往里走
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        current = Path(dirpath)

        for filename in sorted(filenames):
            if not _is_indexable(filename):
                continue
            material = _make_material(
                current / filename, course_dir, course_name,
                extract_text=extract_text, text_chars=text_chars,
            )
            if material is not None:
                materials.append(material)

    materials.sort(key=lambda m: m.rel_path.lower())
    return materials


def _make_material(
    file_path: Path,
    base_dir: Path,
    course_name: str,
    *,
    extract_text: bool,
    text_chars: int,
) -> Material | None:
    """构造单个 Material；读不到 stat 时返回 None（单个文件失败不影响整体）"""
    try:
        stat = file_path.stat()
    except OSError:
        return None

    try:
        rel = file_path.relative_to(base_dir).as_posix()
    except ValueError:
        rel = file_path.name

    text = ""
    if extract_text and file_path.suffix.lower() in _TEXT_CAPABLE_EXTENSIONS:
        text = extract_pdf_text(file_path, text_chars)

    return Material(
        path=str(file_path),
        rel_path=rel,
        name=file_path.stem,
        ext=file_path.suffix.lower(),
        course=course_name,
        size=stat.st_size,
        modified=stat.st_mtime,
        kind=detect_kind(file_path.name),
        week=detect_week(file_path.name),
        text=text,
    )


def _material_from_dict(item: object, course_name: str) -> Material | None:
    """从字典还原 Material，字段缺失用默认值，彻底损坏时返回 None"""
    if not isinstance(item, dict):
        return None

    try:
        raw_week = item.get("week")
        week = int(raw_week) if raw_week is not None else None
        return Material(
            path=str(item.get("path", "")),
            rel_path=str(item.get("rel_path", "")),
            name=str(item.get("name", "")),
            ext=str(item.get("ext", "")),
            course=str(item.get("course", course_name)),
            size=int(item.get("size", 0)),
            modified=float(item.get("modified", 0.0)),
            kind=str(item.get("kind", "other")),
            week=week,
            text=str(item.get("text", "")),
        )
    except (TypeError, ValueError):
        return None


def _extract_with_pypdf(path: Path, max_chars: int) -> str:
    """用 pypdf 抽取 PDF 文本；库缺失或失败返回 ""（延迟导入，非硬依赖）"""
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except Exception:
        return ""

    try:
        reader = PdfReader(str(path))
        chunks: list[str] = []
        total = 0
        for page in reader.pages:
            piece = page.extract_text() or ""
            if piece:
                chunks.append(piece)
                total += len(piece)
            if total >= max_chars:
                break
        return "\n".join(chunks).strip()[:max_chars]
    except Exception:
        return ""


def _extract_with_pdfminer(path: Path, max_chars: int) -> str:
    """用 pdfminer 抽取 PDF 文本；库缺失或失败返回 ""（延迟导入，非硬依赖）"""
    try:
        from pdfminer.high_level import extract_text as _pdfminer_extract  # type: ignore[import-not-found]
    except Exception:
        return ""

    try:
        return (_pdfminer_extract(str(path)) or "").strip()[:max_chars]
    except Exception:
        return ""
