"""
测试 study.index — 全部离线，用 tmp_path 造一棵假的课件目录树
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from moodle_scraper.study.index import (
    INDEX_FILENAME,
    CourseIndex,
    Material,
    build_index,
    detect_kind,
    detect_week,
    extract_pdf_text,
    load_index,
    save_index,
)


def _write(path: Path, content: str = "x") -> Path:
    """写一个文件（自动建父目录）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_tree(root: Path) -> Path:
    """
    构造一棵典型的课件树：

    root/
        COMP1511/
            Week1_Lecture.pdf
            Lab_02.txt              （正文含 quantum）
            sub/Week 3 Tutorial.txt
            .hidden.pdf             （应跳过）
            broken.pdf.part         （应跳过）
            image.png               （非文档类，应跳过）
        PHYS1231/
            quantum.txt
            Assignment_1.pdf
            .cache/secret.pdf       （隐藏目录，应跳过）
        loose_notes.md              （根目录散装文件）
    """
    comp = root / "COMP1511"
    _write(comp / "Week1_Lecture.pdf", "pdf-bytes")
    _write(comp / "Lab_02.txt", "this lab covers quantum tunnelling")
    _write(comp / "sub" / "Week 3 Tutorial.txt", "tutorial content")
    _write(comp / ".hidden.pdf", "nope")
    _write(comp / "broken.pdf.part", "nope")
    _write(comp / "image.png", "nope")

    phys = root / "PHYS1231"
    _write(phys / "quantum.txt", "nothing interesting here")
    _write(phys / "Assignment_1.pdf", "pdf-bytes")
    _write(phys / ".cache" / "secret.pdf", "nope")

    _write(root / "loose_notes.md", "loose material")
    return root


class TestBuildIndex:
    """build_index 按一级子目录分组并遵守跳过规则"""

    def test_groups_by_course_folder(self, tmp_path):
        _make_tree(tmp_path)
        index = build_index(tmp_path)
        assert "COMP1511" in index.courses
        assert "PHYS1231" in index.courses
        assert len(index.courses["PHYS1231"]) == 2

    def test_loose_files_grouped_under_root_name(self, tmp_path):
        _make_tree(tmp_path)
        index = build_index(tmp_path)
        assert tmp_path.name in index.courses
        names = [m.name for m in index.courses[tmp_path.name]]
        assert names == ["loose_notes"]

    def test_skips_dotfiles_partials_and_unknown_ext(self, tmp_path):
        _make_tree(tmp_path)
        index = build_index(tmp_path)
        all_names = [m.rel_path for m in index.all_materials()]
        assert not any(".hidden" in n for n in all_names)
        assert not any(n.endswith(".part") for n in all_names)
        assert not any(n.endswith(".png") for n in all_names)
        assert not any("secret" in n for n in all_names)   # 隐藏目录

    def test_skips_index_file_itself(self, tmp_path):
        _make_tree(tmp_path)
        _write(tmp_path / "COMP1511" / INDEX_FILENAME, "{}")
        index = build_index(tmp_path)
        assert not any(m.name in INDEX_FILENAME for m in index.all_materials())

    def test_recurses_into_subfolders(self, tmp_path):
        _make_tree(tmp_path)
        index = build_index(tmp_path)
        rels = [m.rel_path for m in index.courses["COMP1511"]]
        assert "sub/Week 3 Tutorial.txt" in rels   # 相对课程目录，正斜杠

    def test_material_fields(self, tmp_path):
        _make_tree(tmp_path)
        index = build_index(tmp_path)
        lecture = next(m for m in index.all_materials() if m.name == "Week1_Lecture")
        assert Path(lecture.path).is_absolute()
        assert Path(lecture.path).is_file()
        assert lecture.ext == ".pdf"
        assert lecture.course == "COMP1511"
        assert lecture.size > 0
        assert lecture.modified > 0
        assert lecture.kind == "lecture"
        assert lecture.week == 1

    def test_extract_text_toggle(self, tmp_path):
        _make_tree(tmp_path)
        with_text = build_index(tmp_path, extract_text=True)
        lab = next(m for m in with_text.all_materials() if m.name == "Lab_02")
        assert "quantum" in lab.text

        without_text = build_index(tmp_path, extract_text=False)
        lab2 = next(m for m in without_text.all_materials() if m.name == "Lab_02")
        assert lab2.text == ""

    def test_text_chars_truncates(self, tmp_path):
        _write(tmp_path / "C1" / "notes.txt", "a" * 500)
        index = build_index(tmp_path, text_chars=10)
        assert len(index.courses["C1"][0].text) == 10

    def test_missing_root_returns_empty_index(self, tmp_path):
        index = build_index(tmp_path / "does_not_exist")
        assert index.courses == {}
        assert index.generated_at

    def test_empty_root(self, tmp_path):
        index = build_index(tmp_path)
        assert index.courses == {}
        assert index.all_materials() == []

    def test_accepts_str_path(self, tmp_path):
        _make_tree(tmp_path)
        index = build_index(str(tmp_path))
        assert "COMP1511" in index.courses

    def test_all_document_extensions_indexed(self, tmp_path):
        course = tmp_path / "C1"
        for ext in (".pdf", ".ppt", ".pptx", ".doc", ".docx",
                    ".txt", ".md", ".csv", ".xlsx"):
            _write(course / f"file{ext}")
        _write(course / "skip.zip")
        _write(course / "skip.exe")
        index = build_index(tmp_path)
        assert len(index.courses["C1"]) == 9

    def test_extension_case_insensitive(self, tmp_path):
        _write(tmp_path / "C1" / "LECTURE.PDF")
        index = build_index(tmp_path)
        material = index.courses["C1"][0]
        assert material.ext == ".pdf"


class TestDetectKind:
    """按文件名关键词判断材料类型"""

    def test_known_kinds(self):
        assert detect_kind("Week1_Lecture.pdf") == "lecture"
        assert detect_kind("lec03_slides.pptx") == "lecture"
        assert detect_kind("Lab_02_manual.pdf") == "lab"
        assert detect_kind("practical-3.pdf") == "lab"
        assert detect_kind("Workshop 4.docx") == "workshop"
        assert detect_kind("tutorial_5.pdf") == "tutorial"
        assert detect_kind("Tut06.pdf") == "tutorial"
        assert detect_kind("course_notes.md") == "notes"
        assert detect_kind("Final_Exam_2024.pdf") == "exam"
        assert detect_kind("quiz2.pdf") == "exam"
        assert detect_kind("Assignment_1.pdf") == "assignment"
        assert detect_kind("homework3.docx") == "assignment"

    def test_unknown_is_other(self):
        assert detect_kind("random_file.pdf") == "other"
        assert detect_kind("outline.pdf") == "other"
        assert detect_kind("") == "other"

    def test_case_insensitive(self):
        assert detect_kind("LECTURE_1.PDF") == "lecture"
        assert detect_kind("lEcTuRe.pdf") == "lecture"

    def test_substring_inside_word_does_not_match(self):
        # syllabus 里含 "lab"，但不应被判成 lab
        assert detect_kind("syllabus.pdf") == "other"

    def test_priority_exam_over_lecture(self):
        assert detect_kind("Lecture_Exam_Review.pdf") == "exam"


class TestDetectWeek:
    """从文件名解析周次"""

    def test_week_formats(self):
        assert detect_week("Week 3 slides.pdf") == 3
        assert detect_week("week03_notes.pdf") == 3
        assert detect_week("Week_10.pdf") == 10
        assert detect_week("Wk 7 lab.pdf") == 7
        assert detect_week("wk08.pdf") == 8
        assert detect_week("W3.pdf") == 3
        assert detect_week("Topic 3 intro.pdf") == 3
        assert detect_week("Lecture 5.pdf") == 5
        assert detect_week("lecture05.pptx") == 5
        assert detect_week("L3.pdf") == 3

    def test_no_week_returns_none(self):
        assert detect_week("syllabus.pdf") is None
        assert detect_week("course_outline.docx") is None
        assert detect_week("") is None

    def test_week_takes_priority_over_lecture(self):
        assert detect_week("Week_2_Lecture_9.pdf") == 2

    def test_ignores_implausible_numbers(self):
        # 年份不该被当成周次
        assert detect_week("PHYS1231_T2_2026.pdf") is None

    def test_separators(self):
        assert detect_week("PHYS1231-week-4-lab.pdf") == 4
        assert detect_week("phys.week.4.pdf") == 4


class TestSearch:
    """CourseIndex.search 排序 / 过滤 / 截断"""

    def _index(self) -> CourseIndex:
        def m(name, course, text="", rel=None):
            return Material(
                path=f"/root/{course}/{name}.txt",
                rel_path=rel or f"{name}.txt",
                name=name,
                ext=".txt",
                course=course,
                size=10,
                modified=1.0,
                kind="other",
                week=None,
                text=text,
            )

        return CourseIndex(
            root="/root",
            generated_at="2026-01-01T00:00:00+00:00",
            courses={
                "PHYS1231": [
                    m("quantum_lecture", "PHYS1231"),
                    m("intro", "PHYS1231", text="an intro to quantum mechanics"),
                ],
                "COMP1511": [
                    m("linked_lists", "COMP1511", text="quantum is not covered here"),
                    m("arrays", "COMP1511"),
                ],
            },
        )

    def test_name_matches_outrank_text_matches(self):
        results = self._index().search("quantum")
        assert results[0].name == "quantum_lecture"
        assert {r.name for r in results} == {"quantum_lecture", "intro", "linked_lists"}

    def test_case_insensitive(self):
        assert self._index().search("QUANTUM")
        assert self._index().search("Arrays")[0].name == "arrays"

    def test_course_filter(self):
        results = self._index().search("quantum", course="COMP1511")
        assert [r.name for r in results] == ["linked_lists"]

    def test_course_filter_is_case_insensitive(self):
        results = self._index().search("quantum", course="comp1511")
        assert [r.name for r in results] == ["linked_lists"]

    def test_limit(self):
        results = self._index().search("quantum", limit=1)
        assert len(results) == 1
        assert results[0].name == "quantum_lecture"

    def test_course_name_matches(self):
        results = self._index().search("PHYS")
        assert len(results) == 2
        assert all(r.course == "PHYS1231" for r in results)

    def test_empty_query_returns_empty(self):
        assert self._index().search("") == []
        assert self._index().search("   ") == []

    def test_no_match_returns_empty(self):
        assert self._index().search("zzzz-nope") == []

    def test_search_on_built_index(self, tmp_path):
        _make_tree(tmp_path)
        index = build_index(tmp_path)
        # Lab_02.txt 正文含 quantum；PHYS1231/quantum.txt 文件名含 quantum
        results = index.search("quantum")
        assert results[0].name == "quantum"
        assert any(r.name == "Lab_02" for r in results)


class TestCourseIndexHelpers:
    """all_materials / course_names"""

    def test_course_names_sorted(self, tmp_path):
        _make_tree(tmp_path)
        index = build_index(tmp_path)
        names = index.course_names()
        assert names == sorted(names, key=str.lower)
        assert "COMP1511" in names

    def test_all_materials_count(self, tmp_path):
        _make_tree(tmp_path)
        index = build_index(tmp_path)
        # COMP1511: 3, PHYS1231: 2, 根目录散装: 1
        assert len(index.all_materials()) == 6


class TestSerialization:
    """to_dict / from_dict / save / load"""

    def test_to_dict_is_json_serializable(self, tmp_path):
        _make_tree(tmp_path)
        index = build_index(tmp_path)
        raw = json.dumps(index.to_dict(), ensure_ascii=False)
        assert "COMP1511" in raw

    def test_round_trip(self, tmp_path):
        _make_tree(tmp_path)
        index = build_index(tmp_path)
        restored = CourseIndex.from_dict(index.to_dict())
        assert restored.root == index.root
        assert restored.generated_at == index.generated_at
        assert restored.course_names() == index.course_names()
        assert restored.all_materials() == index.all_materials()
        assert restored.to_dict() == index.to_dict()

    def test_save_load_round_trip(self, tmp_path):
        _make_tree(tmp_path)
        index = build_index(tmp_path)
        target = tmp_path / INDEX_FILENAME
        save_index(index, target)
        assert target.is_file()
        loaded = load_index(target)
        assert loaded is not None
        assert loaded.all_materials() == index.all_materials()

    def test_save_creates_parent_dirs_and_leaves_no_partial(self, tmp_path):
        index = build_index(tmp_path)
        target = tmp_path / "nested" / "deeper" / INDEX_FILENAME
        save_index(index, target)
        assert target.is_file()
        leftovers = [f for f in os.listdir(target.parent) if f.endswith(".part")]
        assert leftovers == []

    def test_save_accepts_str_path(self, tmp_path):
        index = build_index(tmp_path)
        target = str(tmp_path / "idx.json")
        save_index(index, target)
        assert load_index(target) is not None

    def test_load_missing_file_returns_none(self, tmp_path):
        assert load_index(tmp_path / "nope.json") is None

    def test_load_corrupt_json_returns_none(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json at all", encoding="utf-8")
        assert load_index(bad) is None

    def test_load_non_dict_json_returns_none(self, tmp_path):
        bad = tmp_path / "list.json"
        bad.write_text("[1, 2, 3]", encoding="utf-8")
        assert load_index(bad) is None

    def test_load_empty_file_returns_none(self, tmp_path):
        bad = tmp_path / "empty.json"
        bad.write_text("", encoding="utf-8")
        assert load_index(bad) is None

    def test_from_dict_tolerates_missing_fields(self):
        index = CourseIndex.from_dict({"courses": {"C1": [{"name": "a"}]}})
        assert index.root == ""
        material = index.courses["C1"][0]
        assert material.name == "a"
        assert material.course == "C1"
        assert material.week is None
        assert material.text == ""

    def test_from_dict_skips_broken_entries(self):
        index = CourseIndex.from_dict({
            "root": "/r",
            "generated_at": "now",
            "courses": {"C1": ["not-a-dict", {"name": "ok"}]},
        })
        assert [m.name for m in index.courses["C1"]] == ["ok"]

    def test_from_dict_empty_payload(self):
        index = CourseIndex.from_dict({})
        assert index.courses == {}
        assert index.all_materials() == []


class TestExtractPdfText:
    """extract_pdf_text 永不抛异常"""

    def test_reads_txt_directly(self, tmp_path):
        f = _write(tmp_path / "a.txt", "hello study index")
        assert extract_pdf_text(f) == "hello study index"

    def test_reads_md_directly(self, tmp_path):
        f = _write(tmp_path / "a.md", "# 中文标题")
        assert "中文标题" in extract_pdf_text(f)

    def test_truncates_to_max_chars(self, tmp_path):
        f = _write(tmp_path / "a.txt", "b" * 100)
        assert extract_pdf_text(f, max_chars=5) == "bbbbb"

    def test_zero_max_chars(self, tmp_path):
        f = _write(tmp_path / "a.txt", "content")
        assert extract_pdf_text(f, max_chars=0) == ""

    def test_missing_file_returns_empty(self, tmp_path):
        assert extract_pdf_text(tmp_path / "nope.pdf") == ""
        assert extract_pdf_text(tmp_path / "nope.txt") == ""

    def test_directory_returns_empty(self, tmp_path):
        assert extract_pdf_text(tmp_path) == ""

    def test_unsupported_extension_returns_empty(self, tmp_path):
        f = _write(tmp_path / "a.docx", "binary-ish")
        assert extract_pdf_text(f) == ""

    def test_invalid_pdf_never_raises(self, tmp_path):
        f = _write(tmp_path / "broken.pdf", "definitely not a pdf")
        assert extract_pdf_text(f) == ""

    def test_accepts_str_path(self, tmp_path):
        f = _write(tmp_path / "a.txt", "ok")
        assert extract_pdf_text(str(f)) == "ok"


class _FakePage:
    """假的 PDF 页面"""

    def __init__(self, text: str, boom: bool = False) -> None:
        self._text = text
        self._boom = boom

    def extract_text(self) -> str:
        if self._boom:
            raise RuntimeError("cannot decode page")
        return self._text


def _install_fake_pypdf(monkeypatch, pages, boom: bool = False) -> None:
    """把一个假的 pypdf 塞进 sys.modules（本机没装真库，用它验证懒加载分支）"""
    import sys
    import types

    class _FakeReader:
        def __init__(self, path: str) -> None:
            if boom:
                raise RuntimeError("broken pdf")
            self.pages = list(pages)

    module = types.ModuleType("pypdf")
    module.PdfReader = _FakeReader
    monkeypatch.setitem(sys.modules, "pypdf", module)


def _install_fake_pdfminer(monkeypatch, text: str, boom: bool = False) -> None:
    """把一个假的 pdfminer.high_level 塞进 sys.modules"""
    import sys
    import types

    def _extract_text(path: str) -> str:
        if boom:
            raise RuntimeError("broken pdf")
        return text

    package = types.ModuleType("pdfminer")
    high_level = types.ModuleType("pdfminer.high_level")
    high_level.extract_text = _extract_text
    package.high_level = high_level
    monkeypatch.setitem(sys.modules, "pdfminer", package)
    monkeypatch.setitem(sys.modules, "pdfminer.high_level", high_level)


class TestPdfBackends:
    """PDF 抽取的两条懒加载后端路径（真库缺席时用假模块验证）"""

    def test_uses_pypdf_when_available(self, tmp_path, monkeypatch):
        _install_fake_pypdf(monkeypatch, [_FakePage("page one"), _FakePage("page two")])
        f = _write(tmp_path / "a.pdf", "%PDF-1.4")
        assert extract_pdf_text(f) == "page one\npage two"

    def test_pypdf_result_truncated(self, tmp_path, monkeypatch):
        _install_fake_pypdf(monkeypatch, [_FakePage("x" * 50)])
        f = _write(tmp_path / "a.pdf", "%PDF-1.4")
        assert extract_pdf_text(f, max_chars=7) == "xxxxxxx"

    def test_falls_back_to_pdfminer(self, tmp_path, monkeypatch):
        _install_fake_pypdf(monkeypatch, [], boom=True)     # pypdf 抛异常
        _install_fake_pdfminer(monkeypatch, "  miner text  ")
        f = _write(tmp_path / "a.pdf", "%PDF-1.4")
        assert extract_pdf_text(f) == "miner text"

    def test_both_backends_failing_returns_empty(self, tmp_path, monkeypatch):
        _install_fake_pypdf(monkeypatch, [], boom=True)
        _install_fake_pdfminer(monkeypatch, "", boom=True)
        f = _write(tmp_path / "a.pdf", "%PDF-1.4")
        assert extract_pdf_text(f) == ""

    def test_page_level_failure_never_raises(self, tmp_path, monkeypatch):
        _install_fake_pypdf(monkeypatch, [_FakePage("", boom=True)])
        _install_fake_pdfminer(monkeypatch, "", boom=True)
        f = _write(tmp_path / "a.pdf", "%PDF-1.4")
        assert extract_pdf_text(f) == ""

    def test_build_index_picks_up_pdf_text(self, tmp_path, monkeypatch):
        _install_fake_pypdf(monkeypatch, [_FakePage("entropy and heat")])
        _write(tmp_path / "PHYS1231" / "Week 2 Lecture.pdf", "%PDF-1.4")
        index = build_index(tmp_path)
        material = index.courses["PHYS1231"][0]
        assert material.text == "entropy and heat"
        assert index.search("entropy")[0] is material
