"""
测试 study.obsidian — 全部离线，Material 直接在内存里构造，导出到 tmp_path
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from moodle_scraper.study.index import CourseIndex, Material
from moodle_scraper.study.obsidian import ExportResult, export_vault


MTIME: float = 1_700_000_000.0
MTIME_ISO: str = datetime.fromtimestamp(MTIME, tz=timezone.utc).isoformat()


def _material(
    name: str,
    *,
    course: str = "PHYS1231",
    week: int | None = None,
    kind: str = "lecture",
    ext: str = ".pdf",
    path: str | None = None,
    rel_path: str | None = None,
    size: int = 1024,
    modified: float = MTIME,
    text: str = "",
) -> Material:
    """造一份材料（path 默认是个不存在的假路径，够用即可）"""
    filename = f"{name}{ext}"
    return Material(
        path=path if path is not None else str(Path("/fake") / course / filename),
        rel_path=rel_path if rel_path is not None else filename,
        name=name,
        ext=ext,
        course=course,
        size=size,
        modified=modified,
        kind=kind,
        week=week,
        text=text,
    )


def _index(**courses: list[Material]) -> CourseIndex:
    """用关键字参数拼一个索引：_index(PHYS1231=[...])"""
    return CourseIndex(root="/fake", generated_at="2026-01-01T00:00:00+00:00",
                       courses=dict(courses))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict[str, str]:
    """把首个 --- 块解析成 {字段: 原始值字符串}"""
    lines = text.splitlines()
    assert lines and lines[0] == "---", "笔记必须以 YAML frontmatter 开头"
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            break
        key, _, value = line.partition(": ")
        fields[key.strip()] = value.strip()
    return fields


def _unquote(value: str) -> str:
    """还原 _yaml_str 写出的带引号标量"""
    return value.strip('"').replace('\\\\', '\\').replace('\\"', '"')


class TestVaultLayout:
    """目录结构：课程文件夹 / 周次桶 / Unsorted / MOC"""

    def test_creates_course_dir_and_moc(self, tmp_path):
        index = _index(PHYS1231=[_material("Lecture 1", week=1)])
        export_vault(index, tmp_path / "vault")

        moc = tmp_path / "vault" / "PHYS1231" / "PHYS1231.md"
        assert moc.is_file()

    def test_week_bucket_is_zero_padded(self, tmp_path):
        index = _index(PHYS1231=[
            _material("Lecture 3", week=3),
            _material("Lecture 12", week=12),
        ])
        export_vault(index, tmp_path)

        assert (tmp_path / "PHYS1231" / "Week 03" / "Lecture 3.md").is_file()
        assert (tmp_path / "PHYS1231" / "Week 12" / "Lecture 12.md").is_file()

    def test_missing_week_goes_to_unsorted(self, tmp_path):
        index = _index(PHYS1231=[_material("Syllabus", kind="notes")])
        export_vault(index, tmp_path)

        assert (tmp_path / "PHYS1231" / "Unsorted" / "Syllabus.md").is_file()

    def test_out_of_range_week_goes_to_unsorted(self, tmp_path):
        index = _index(PHYS1231=[_material("Weird", week=2026)])
        export_vault(index, tmp_path)

        assert (tmp_path / "PHYS1231" / "Unsorted" / "Weird.md").is_file()

    def test_no_attachments_dir_without_copy_files(self, tmp_path):
        index = _index(PHYS1231=[_material("Lecture 1", week=1)])
        export_vault(index, tmp_path)

        assert not (tmp_path / "PHYS1231" / "_attachments").exists()

    def test_vault_dir_is_created_and_absolute(self, tmp_path):
        target = tmp_path / "nested" / "vault"
        result = export_vault(_index(PHYS1231=[_material("A", week=1)]), target)

        assert target.is_dir()
        assert Path(result.vault_dir).is_absolute()
        assert Path(result.vault_dir) == target.resolve()


class TestExportResult:
    """计数：courses / notes_written / skipped / files_copied"""

    def test_counts_notes_and_moc(self, tmp_path):
        index = _index(PHYS1231=[
            _material("Lecture 1", week=1),
            _material("Lab 2", week=2, kind="lab"),
        ])
        result = export_vault(index, tmp_path)

        assert isinstance(result, ExportResult)
        assert result.courses == 1
        assert result.notes_written == 3        # 2 篇材料 + 1 篇 MOC
        assert result.skipped == 0
        assert result.files_copied == 0

    def test_multiple_courses(self, tmp_path):
        index = _index(
            PHYS1231=[_material("Lecture 1", week=1)],
            COMP1511=[_material("Lab 1", course="COMP1511", week=1, kind="lab")],
        )
        result = export_vault(index, tmp_path)

        assert result.courses == 2
        assert result.notes_written == 4
        assert (tmp_path / "PHYS1231" / "PHYS1231.md").is_file()
        assert (tmp_path / "COMP1511" / "COMP1511.md").is_file()

    def test_empty_course_produces_nothing(self, tmp_path):
        index = _index(PHYS1231=[], COMP1511=[_material("Lab 1", course="COMP1511")])
        result = export_vault(index, tmp_path)

        assert result.courses == 1
        assert not (tmp_path / "PHYS1231").exists()

    def test_empty_index(self, tmp_path):
        result = export_vault(_index(), tmp_path)

        assert result.courses == 0
        assert result.notes_written == 0


class TestNoteFrontmatter:
    """每篇笔记的 YAML frontmatter"""

    def _note(self, tmp_path, material: Material) -> str:
        export_vault(_index(PHYS1231=[material]), tmp_path)
        bucket = "Unsorted" if material.week is None else f"Week {material.week:02d}"
        return _read(tmp_path / "PHYS1231" / bucket / f"{material.name}.md")

    def test_core_fields(self, tmp_path):
        material = _material("Lecture 3", week=3, kind="lecture", size=4096)
        fields = _frontmatter(self._note(tmp_path, material))

        assert _unquote(fields["course"]) == "PHYS1231"
        assert _unquote(fields["title"]) == "Lecture 3"
        assert fields["week"] == "3"
        assert _unquote(fields["kind"]) == "lecture"
        assert fields["size"] == "4096"

    def test_source_is_absolute_path(self, tmp_path):
        material = _material("Lecture 3", week=3)
        fields = _frontmatter(self._note(tmp_path, material))

        assert _unquote(fields["source"]) == material.path

    def test_modified_is_iso(self, tmp_path):
        fields = _frontmatter(self._note(tmp_path, _material("Lecture 3", week=3)))

        assert _unquote(fields["modified"]) == MTIME_ISO

    def test_week_null_when_unknown(self, tmp_path):
        fields = _frontmatter(self._note(tmp_path, _material("Syllabus")))

        assert fields["week"] == "null"

    def test_tags(self, tmp_path):
        fields = _frontmatter(self._note(tmp_path, _material("Lecture 3", week=3)))

        assert fields["tags"] == "[moodle, PHYS1231, lecture, week-03]"

    def test_tags_without_week(self, tmp_path):
        fields = _frontmatter(self._note(tmp_path, _material("Notes", kind="notes")))

        assert fields["tags"] == "[moodle, PHYS1231, notes]"

    def test_blank_kind_falls_back_to_other(self, tmp_path):
        fields = _frontmatter(self._note(tmp_path, _material("Thing", kind="")))

        assert _unquote(fields["kind"]) == "other"
        assert fields["tags"] == "[moodle, PHYS1231, other]"


class TestNoteBody:
    """正文：链接 / 复习要点 / 摘要 / 反向链接"""

    def _note(self, tmp_path, material: Material) -> str:
        export_vault(_index(PHYS1231=[material]), tmp_path)
        bucket = "Unsorted" if material.week is None else f"Week {material.week:02d}"
        return _read(tmp_path / "PHYS1231" / bucket / f"{material.name}.md")

    def test_heading_and_backlink(self, tmp_path):
        body = self._note(tmp_path, _material("Lecture 3", week=3))

        assert "# Lecture 3" in body
        assert "[[PHYS1231]]" in body

    def test_markdown_link_to_source(self, tmp_path):
        material = _material("Lecture 3", week=3)
        body = self._note(tmp_path, material)

        assert f"[{Path(material.path).name}](<{Path(material.path).as_posix()}>)" in body
        assert "![[" not in body            # 没复制文件就不该有嵌入

    def test_review_section_has_empty_bullets(self, tmp_path):
        body = self._note(tmp_path, _material("Lecture 3", week=3))

        assert "## 复习要点" in body
        section = body.split("## 复习要点", 1)[1]
        assert section.count("\n- ") >= 3

    def test_summary_callout_present_when_text(self, tmp_path):
        material = _material("Lecture 3", week=3, text="quantum tunnelling\nsecond line")
        body = self._note(tmp_path, material)

        assert "## 摘要" in body
        assert "> [!summary]" in body
        assert "> quantum tunnelling" in body
        assert "> second line" in body

    def test_summary_absent_when_no_text(self, tmp_path):
        body = self._note(tmp_path, _material("Lecture 3", week=3, text="   "))

        assert "## 摘要" not in body
        assert "[!summary]" not in body

    def test_note_is_utf8_and_starts_with_frontmatter(self, tmp_path):
        body = self._note(tmp_path, _material("讲义 一", week=1, text="中文摘要"))

        assert body.startswith("---\n")
        assert "中文摘要" in body


class TestCourseMoc:
    """课程 MOC：统计 + 分组 wikilink"""

    def _moc(self, tmp_path, materials: list[Material]) -> str:
        export_vault(_index(PHYS1231=materials), tmp_path)
        return _read(tmp_path / "PHYS1231" / "PHYS1231.md")

    def test_frontmatter(self, tmp_path):
        moc = self._moc(tmp_path, [
            _material("Lecture 1", week=1),
            _material("Lab 2", week=2, kind="lab"),
        ])
        fields = _frontmatter(moc)

        assert _unquote(fields["course"]) == "PHYS1231"
        assert fields["type"] == "course-moc"
        assert fields["materials"] == "2"
        assert fields["tags"] == "[moodle, PHYS1231, moc]"

    def test_kind_counts(self, tmp_path):
        moc = self._moc(tmp_path, [
            _material("Lecture 1", week=1),
            _material("Lecture 2", week=2),
            _material("Lab 1", week=1, kind="lab"),
        ])

        assert "| lecture | 2 |" in moc
        assert "| lab | 1 |" in moc

    def test_wikilinks_per_note(self, tmp_path):
        moc = self._moc(tmp_path, [
            _material("Lecture 3", week=3),
            _material("Syllabus", kind="notes"),
        ])

        assert "[[PHYS1231/Week 03/Lecture 3|Lecture 3]]" in moc
        assert "[[PHYS1231/Unsorted/Syllabus|Syllabus]]" in moc

    def test_week_sections_sorted_with_unsorted_last(self, tmp_path):
        moc = self._moc(tmp_path, [
            _material("Syllabus", kind="notes"),
            _material("Lecture 10", week=10),
            _material("Lecture 2", week=2),
        ])

        assert moc.index("### Week 02") < moc.index("### Week 10") < moc.index("### Unsorted")


class TestSkipAndOverwrite:
    """已存在的笔记默认不覆盖"""

    def _index_with(self, text: str) -> CourseIndex:
        return _index(PHYS1231=[_material("Lecture 1", week=1, text=text)])

    def test_second_export_skips_everything(self, tmp_path):
        export_vault(self._index_with("first"), tmp_path)
        result = export_vault(self._index_with("second"), tmp_path)

        assert result.notes_written == 0
        assert result.skipped == 2               # 1 篇材料 + 1 篇 MOC
        assert "first" in _read(tmp_path / "PHYS1231" / "Week 01" / "Lecture 1.md")

    def test_overwrite_rewrites_notes(self, tmp_path):
        export_vault(self._index_with("first"), tmp_path)
        result = export_vault(self._index_with("second"), tmp_path, overwrite=True)

        assert result.notes_written == 2
        assert result.skipped == 0
        note = _read(tmp_path / "PHYS1231" / "Week 01" / "Lecture 1.md")
        assert "second" in note
        assert "first" not in note

    def test_skipped_notes_still_listed_in_moc(self, tmp_path):
        export_vault(self._index_with("first"), tmp_path)
        (tmp_path / "PHYS1231" / "PHYS1231.md").unlink()
        export_vault(self._index_with("first"), tmp_path)

        moc = _read(tmp_path / "PHYS1231" / "PHYS1231.md")
        assert "[[PHYS1231/Week 01/Lecture 1|Lecture 1]]" in moc

    def test_foreign_file_is_not_clobbered(self, tmp_path):
        note = tmp_path / "PHYS1231" / "Week 01" / "Lecture 1.md"
        note.parent.mkdir(parents=True)
        note.write_text("手写内容", encoding="utf-8")

        result = export_vault(self._index_with("x"), tmp_path)

        assert _read(note) == "手写内容"
        assert result.skipped == 1


class TestCopyFiles:
    """copy_files=True 时复制原文件并改用嵌入语法"""

    def _real_material(self, tmp_path, *, rel_path: str | None = None) -> Material:
        source = tmp_path / "src" / "Lecture 3.pdf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"%PDF-fake")
        return _material("Lecture 3", week=3, path=str(source), rel_path=rel_path)

    def test_copies_file_and_embeds(self, tmp_path):
        vault = tmp_path / "vault"
        material = self._real_material(tmp_path)
        result = export_vault(_index(PHYS1231=[material]), vault, copy_files=True)

        copied = vault / "PHYS1231" / "_attachments" / "Lecture 3.pdf"
        assert copied.is_file()
        assert copied.read_bytes() == b"%PDF-fake"
        assert result.files_copied == 1

        note = _read(vault / "PHYS1231" / "Week 03" / "Lecture 3.md")
        assert "![[_attachments/Lecture 3.pdf]]" in note

    def test_preserves_nested_rel_path(self, tmp_path):
        vault = tmp_path / "vault"
        material = self._real_material(tmp_path, rel_path="slides/Lecture 3.pdf")
        export_vault(_index(PHYS1231=[material]), vault, copy_files=True)

        assert (vault / "PHYS1231" / "_attachments" / "slides" / "Lecture 3.pdf").is_file()
        note = _read(vault / "PHYS1231" / "Week 03" / "Lecture 3.md")
        assert "![[_attachments/slides/Lecture 3.pdf]]" in note

    def test_missing_source_falls_back_to_link(self, tmp_path):
        vault = tmp_path / "vault"
        material = _material("Ghost", week=1)          # path 指向不存在的文件
        result = export_vault(_index(PHYS1231=[material]), vault, copy_files=True)

        assert result.files_copied == 0
        assert not (vault / "PHYS1231" / "_attachments").exists()
        note = _read(vault / "PHYS1231" / "Week 01" / "Ghost.md")
        assert "![[" not in note
        assert Path(material.path).as_posix() in note

    def test_existing_attachment_not_recopied(self, tmp_path):
        vault = tmp_path / "vault"
        material = self._real_material(tmp_path)
        export_vault(_index(PHYS1231=[material]), vault, copy_files=True)
        result = export_vault(_index(PHYS1231=[material]), vault, copy_files=True)

        assert result.files_copied == 0

    def test_overwrite_recopies_attachment(self, tmp_path):
        vault = tmp_path / "vault"
        material = self._real_material(tmp_path)
        export_vault(_index(PHYS1231=[material]), vault, copy_files=True)

        Path(material.path).write_bytes(b"%PDF-updated")
        result = export_vault(_index(PHYS1231=[material]), vault,
                              copy_files=True, overwrite=True)

        copied = vault / "PHYS1231" / "_attachments" / "Lecture 3.pdf"
        assert result.files_copied == 1
        assert copied.read_bytes() == b"%PDF-updated"


class TestSanitizing:
    """文件名清洗：Windows 非法字符 / 重名 / 空名"""

    def test_illegal_chars_in_note_name(self, tmp_path):
        index = _index(PHYS1231=[_material('Week 1: Intro/Outro?', week=1)])
        export_vault(index, tmp_path)

        notes = list((tmp_path / "PHYS1231" / "Week 01").glob("*.md"))
        assert len(notes) == 1
        assert not set(notes[0].stem) & set('\\/*?:"<>|')

    def test_illegal_chars_in_course_name(self, tmp_path):
        index = CourseIndex(root="/fake", generated_at="", courses={
            "PHYS1231: T2/2026": [_material("Lecture 1", course="PHYS1231: T2/2026", week=1)],
        })
        result = export_vault(index, tmp_path)

        assert result.courses == 1
        dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
        assert len(dirs) == 1
        assert not set(dirs[0].name) & set('\\/*?:"<>|')
        assert (dirs[0] / f"{dirs[0].name}.md").is_file()

    def test_duplicate_names_in_same_bucket(self, tmp_path):
        index = _index(PHYS1231=[
            _material("Lecture", week=1),
            _material("Lecture", week=1, ext=".pptx"),
        ])
        result = export_vault(index, tmp_path)

        notes = sorted(p.name for p in (tmp_path / "PHYS1231" / "Week 01").glob("*.md"))
        assert notes == ["Lecture (2).md", "Lecture.md"]
        assert result.notes_written == 3

    def test_same_name_in_different_weeks_kept_apart(self, tmp_path):
        index = _index(PHYS1231=[
            _material("Lecture", week=1),
            _material("Lecture", week=2),
        ])
        export_vault(index, tmp_path)

        assert (tmp_path / "PHYS1231" / "Week 01" / "Lecture.md").is_file()
        assert (tmp_path / "PHYS1231" / "Week 02" / "Lecture.md").is_file()

    def test_blank_name_gets_fallback(self, tmp_path):
        index = _index(PHYS1231=[_material("   ", week=1, path="")])
        result = export_vault(index, tmp_path)

        assert result.notes_written == 2
        assert (tmp_path / "PHYS1231" / "Week 01" / "Untitled.md").is_file()


class TestRobustness:
    """单份材料出错不能中断整批导出"""

    def test_failing_material_does_not_abort(self, tmp_path, monkeypatch):
        from moodle_scraper.study import obsidian

        original = obsidian._render_note

        def flaky(material, course_title, title, week, attachment):
            if material.name == "Bad":
                raise RuntimeError("boom")
            return original(material, course_title, title, week, attachment)

        monkeypatch.setattr(obsidian, "_render_note", flaky)

        index = _index(PHYS1231=[
            _material("Good 1", week=1),
            _material("Bad", week=1),
            _material("Good 2", week=2),
        ])
        result = export_vault(index, tmp_path)

        assert result.notes_written == 3          # 2 篇好材料 + MOC
        assert (tmp_path / "PHYS1231" / "Week 01" / "Good 1.md").is_file()
        assert (tmp_path / "PHYS1231" / "Week 02" / "Good 2.md").is_file()
        assert not (tmp_path / "PHYS1231" / "Week 01" / "Bad.md").exists()

        moc = _read(tmp_path / "PHYS1231" / "PHYS1231.md")
        assert "Bad" not in moc

    def test_failing_course_does_not_abort(self, tmp_path, monkeypatch):
        from moodle_scraper.study import obsidian

        original = obsidian._export_course

        def flaky(vault_path, course_name, materials, **kwargs):
            if course_name == "BAD1001":
                raise RuntimeError("boom")
            return original(vault_path, course_name, materials, **kwargs)

        monkeypatch.setattr(obsidian, "_export_course", flaky)

        index = _index(
            BAD1001=[_material("X", course="BAD1001", week=1)],
            PHYS1231=[_material("Lecture 1", week=1)],
        )
        result = export_vault(index, tmp_path)

        assert result.courses == 1
        assert (tmp_path / "PHYS1231" / "PHYS1231.md").is_file()

    def test_reexport_into_existing_vault_dir(self, tmp_path):
        (tmp_path / "existing.md").write_text("keep me", encoding="utf-8")
        export_vault(_index(PHYS1231=[_material("Lecture 1", week=1)]), tmp_path)

        assert _read(tmp_path / "existing.md") == "keep me"

    def test_zero_size_and_bad_mtime(self, tmp_path):
        material = _material("Odd", week=1, size=0, modified=-1.0)
        export_vault(_index(PHYS1231=[material]), tmp_path)

        fields = _frontmatter(_read(tmp_path / "PHYS1231" / "Week 01" / "Odd.md"))
        assert fields["size"] == "0"
        assert "modified" in fields               # 非法 mtime 也不能炸
