"""
测试 study.notebook — 全部离线，索引在内存里手工拼出来
"""
from __future__ import annotations

import json
from pathlib import Path

from moodle_scraper.study.index import CourseIndex, Material
from moodle_scraper.study.notebook import (
    DEFAULT_DAYS,
    DayPlan,
    build_plan,
    build_revision_notebook,
    notebook_dict,
)


def _material(
    course: str,
    name: str,
    *,
    ext: str = ".pdf",
    kind: str = "lecture",
    week: int | None = None,
    text: str = "",
) -> Material:
    """造一份内存里的 Material（不碰磁盘）"""
    rel = f"{name}{ext}"
    return Material(
        path=f"/root/{course}/{rel}",
        rel_path=rel,
        name=name,
        ext=ext,
        course=course,
        size=1024,
        modified=1_700_000_000.0,
        kind=kind,
        week=week,
        text=text,
    )


def _index() -> CourseIndex:
    """
    两门课的索引：

    COMP1511: Week1_Lecture(1) / Lab_02(2) / Assignment_1(None)
    PHYS1231: Week1_Quantum(1) / Week3_Tutorial(3) / Final_Exam(None)
    """
    return CourseIndex(
        root="/root",
        generated_at="2026-07-28T10:20:30+00:00",
        courses={
            "COMP1511": [
                _material("COMP1511", "Week1_Lecture", kind="lecture", week=1),
                _material("COMP1511", "Lab_02", kind="lab", week=2),
                _material("COMP1511", "Assignment_1", kind="assignment"),
            ],
            "PHYS1231": [
                _material("PHYS1231", "Week1_Quantum", kind="lecture", week=1),
                _material("PHYS1231", "Week3_Tutorial", kind="tutorial", week=3),
                _material("PHYS1231", "Final_Exam", kind="exam"),
            ],
        },
    )


def _empty_index() -> CourseIndex:
    """没有任何材料的索引"""
    return CourseIndex(root="/root", generated_at="2026-07-28T10:20:30+00:00", courses={})


def _text_of(notebook: dict) -> str:
    """把所有单元格的 source 拼成一整块文本，便于做内容断言"""
    return "\n".join("".join(cell["source"]) for cell in notebook["cells"])


def _cells_of(notebook: dict, cell_type: str) -> list[dict]:
    """按类型挑单元格"""
    return [c for c in notebook["cells"] if c["cell_type"] == cell_type]


class TestNotebookStructure:
    """notebook_dict 产出合法的 nbformat 4 结构"""

    def test_top_level_keys(self):
        nb = notebook_dict(_index())
        assert nb["nbformat"] == 4
        assert nb["nbformat_minor"] == 5
        assert isinstance(nb["cells"], list) and nb["cells"]
        assert isinstance(nb["metadata"], dict)

    def test_kernelspec_is_python3(self):
        nb = notebook_dict(_index())
        assert nb["metadata"]["kernelspec"]["name"] == "python3"
        assert nb["metadata"]["language_info"]["name"] == "python"

    def test_every_cell_has_required_keys(self):
        nb = notebook_dict(_index())
        for cell in nb["cells"]:
            assert cell["cell_type"] in {"markdown", "code"}
            assert isinstance(cell["id"], str) and cell["id"]
            assert isinstance(cell["metadata"], dict)
            assert isinstance(cell["source"], list)
            assert all(isinstance(line, str) for line in cell["source"])

    def test_cell_ids_are_unique(self):
        nb = notebook_dict(_index())
        ids = [cell["id"] for cell in nb["cells"]]
        assert len(ids) == len(set(ids))

    def test_code_cells_have_outputs_and_execution_count(self):
        nb = notebook_dict(_index())
        code_cells = _cells_of(nb, "code")
        assert len(code_cells) >= 2
        for cell in code_cells:
            assert cell["outputs"] == []
            assert cell["execution_count"] is None

    def test_markdown_cells_have_no_output_keys(self):
        nb = notebook_dict(_index())
        for cell in _cells_of(nb, "markdown"):
            assert "outputs" not in cell
            assert "execution_count" not in cell

    def test_every_source_line_ends_with_newline(self):
        nb = notebook_dict(_index())
        for cell in nb["cells"]:
            for line in cell["source"]:
                assert line.endswith("\n"), f"{cell['id']}: {line!r}"

    def test_code_cells_are_valid_python(self):
        nb = notebook_dict(_index())
        for cell in _cells_of(nb, "code"):
            compile("".join(cell["source"]), f"<{cell['id']}>", "exec")

    def test_expected_sections_present(self):
        text = _text_of(notebook_dict(_index()))
        assert "# 📚 复习笔记本" in text
        assert "## 课程概览" in text
        assert "每日复习计划" in text
        assert "## 🧠 自测区" in text

    def test_header_shows_index_generated_at(self):
        text = _text_of(notebook_dict(_index()))
        assert "2026-07-28 10:20" in text

    def test_output_is_deterministic(self):
        index = _index()
        assert notebook_dict(index) == notebook_dict(index)


class TestContent:
    """概览 / 计划 / 自测区的内容"""

    def test_every_material_appears_in_quiz(self):
        nb = notebook_dict(_index())
        quiz = "".join(_cells_of(nb, "markdown")[-1]["source"])
        for name in ("Week1_Lecture", "Lab_02", "Assignment_1",
                     "Week1_Quantum", "Week3_Tutorial", "Final_Exam"):
            assert f"**{name}**" in quiz

    def test_quiz_has_checkbox_and_recall_prompt(self):
        quiz = "".join(_cells_of(notebook_dict(_index()), "markdown")[-1]["source"])
        assert "- [ ] **Week1_Lecture**" in quiz
        assert "空白回忆：" in quiz
        assert "一句话总结：" in quiz

    def test_overview_lists_both_courses(self):
        text = _text_of(notebook_dict(_index()))
        assert "| COMP1511 |" in text
        assert "| PHYS1231 |" in text

    def test_load_cell_embeds_root_and_course(self):
        code = "".join(_cells_of(notebook_dict(_index(), course="COMP1511"), "code")[0]["source"])
        assert 'ROOT = "/root"' in code
        assert 'COURSE = "COMP1511"' in code
        assert "load_index" in code and "build_index" in code

    def test_load_cell_course_is_none_without_filter(self):
        code = "".join(_cells_of(notebook_dict(_index()), "code")[0]["source"])
        assert "COURSE = None" in code

    def test_progress_cell_uses_only_stdlib(self):
        code = "".join(_cells_of(notebook_dict(_index()), "code")[1]["source"])
        assert "import matplotlib" not in code
        assert "import pandas" not in code
        assert "from collections import Counter" in code

    def test_pipes_in_names_are_escaped(self):
        index = CourseIndex(
            root="/root",
            generated_at="2026-07-28T10:20:30+00:00",
            courses={"A|B": [_material("A|B", "week|1", week=1)]},
        )
        nb = notebook_dict(index)
        plan = "".join(_cells_of(nb, "markdown")[1]["source"])
        assert "A\\|B" in _text_of(nb)
        assert "week\\|1" in plan

    def test_empty_index_still_valid(self):
        nb = notebook_dict(_empty_index())
        assert nb["nbformat"] == 4
        assert nb["metadata"]["moodle_scraper"]["material_count"] == 0
        for cell in _cells_of(nb, "code"):
            compile("".join(cell["source"]), "<cell>", "exec")


class TestCourseFilter:
    """course 参数只保留一门课"""

    def test_filter_keeps_only_that_course(self):
        text = _text_of(notebook_dict(_index(), course="COMP1511"))
        assert "Week1_Lecture" in text
        assert "Week1_Quantum" not in text
        assert "Final_Exam" not in text

    def test_filter_is_case_insensitive(self):
        nb = notebook_dict(_index(), course="comp1511")
        assert nb["metadata"]["moodle_scraper"]["material_count"] == 3

    def test_unknown_course_yields_empty_notebook(self):
        nb = notebook_dict(_index(), course="NOPE9999")
        assert nb["metadata"]["moodle_scraper"]["material_count"] == 0
        assert "没有匹配的材料" in _text_of(nb)

    def test_no_filter_keeps_everything(self):
        nb = notebook_dict(_index())
        assert nb["metadata"]["moodle_scraper"]["material_count"] == 6
        assert nb["metadata"]["moodle_scraper"]["course"] == ""


class TestDays:
    """days 参数控制计划表的长度"""

    def test_default_days(self):
        nb = notebook_dict(_index())
        assert nb["metadata"]["moodle_scraper"]["days"] == DEFAULT_DAYS

    def test_plan_table_has_one_row_per_day(self):
        for days in (1, 3, 7, 10):
            plan = "".join(_cells_of(notebook_dict(_index(), days=days), "markdown")[1]["source"])
            rows = [line for line in plan.splitlines() if line.startswith("| 第 ")]
            assert len(rows) == days
            assert f"（{days} 天）" in plan

    def test_days_clamped_to_at_least_one(self):
        for days in (0, -5):
            nb = notebook_dict(_index(), days=days)
            assert nb["metadata"]["moodle_scraper"]["days"] == 1

    def test_days_capped(self):
        nb = notebook_dict(_index(), days=9999)
        assert nb["metadata"]["moodle_scraper"]["days"] <= 60


class TestBuildPlan:
    """build_plan 的分配与间隔重复"""

    def test_returns_one_entry_per_day(self):
        plans = build_plan(_index(), days=4)
        assert len(plans) == 4
        assert [p.day for p in plans] == [1, 2, 3, 4]
        assert all(isinstance(p, DayPlan) for p in plans)

    def test_all_materials_scheduled_exactly_once(self):
        plans = build_plan(_index(), days=4)
        scheduled = [m.name for p in plans for m in p.materials]
        assert sorted(scheduled) == sorted([
            "Assignment_1", "Final_Exam", "Lab_02",
            "Week1_Lecture", "Week1_Quantum", "Week3_Tutorial",
        ])

    def test_earlier_weeks_come_first(self):
        plans = build_plan(_index(), days=6)
        order = [m.name for p in plans for m in p.materials]
        assert set(order[:2]) == {"Week1_Lecture", "Week1_Quantum"}
        # 没有周次的材料排在最后
        assert set(order[-2:]) == {"Assignment_1", "Final_Exam"}

    def test_first_day_has_no_reviews(self):
        plans = build_plan(_index(), days=5)
        assert plans[0].reviews == []

    def test_second_day_reviews_first_day(self):
        plans = build_plan(_index(), days=6)
        expected = [m.name for m in plans[0].materials]
        assert [m.name for m in plans[1].reviews] == expected

    def test_reviews_are_deduplicated(self):
        plans = build_plan(_index(), days=10)
        for plan in plans:
            paths = [m.path for m in plan.reviews]
            assert len(paths) == len(set(paths))

    def test_more_days_than_materials_leaves_empty_days(self):
        plans = build_plan(_index(), days=12)
        assert sum(len(p.materials) for p in plans) == 6
        assert any(not p.materials for p in plans)

    def test_empty_index_gives_empty_days(self):
        plans = build_plan(_empty_index(), days=3)
        assert len(plans) == 3
        assert all(not p.materials and not p.reviews for p in plans)


class TestBuildRevisionNotebook:
    """写盘行为"""

    def test_writes_file_and_returns_path(self, tmp_path):
        out = tmp_path / "revision.ipynb"
        returned = build_revision_notebook(_index(), out)
        assert Path(returned) == out
        assert out.is_file()

    def test_file_round_trips_identically(self, tmp_path):
        out = tmp_path / "revision.ipynb"
        build_revision_notebook(_index(), out, days=5)
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded == notebook_dict(_index(), days=5)

    def test_respects_course_and_days(self, tmp_path):
        out = tmp_path / "comp.ipynb"
        build_revision_notebook(_index(), out, course="COMP1511", days=3)
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["metadata"]["moodle_scraper"] == {
            "course": "COMP1511",
            "days": 3,
            "generated_at": "2026-07-28T10:20:30+00:00",
            "material_count": 3,
        }

    def test_creates_missing_parent_directories(self, tmp_path):
        out = tmp_path / "deep" / "nested" / "revision.ipynb"
        build_revision_notebook(_index(), out)
        assert out.is_file()

    def test_no_part_file_left_behind(self, tmp_path):
        out = tmp_path / "revision.ipynb"
        build_revision_notebook(_index(), out)
        assert list(tmp_path.glob("*.part")) == []

    def test_overwrites_existing_file(self, tmp_path):
        out = tmp_path / "revision.ipynb"
        out.write_text("garbage", encoding="utf-8")
        build_revision_notebook(_index(), out)
        assert json.loads(out.read_text(encoding="utf-8"))["nbformat"] == 4

    def test_accepts_str_path(self, tmp_path):
        out = str(tmp_path / "revision.ipynb")
        assert build_revision_notebook(_index(), out) == out
        assert Path(out).is_file()


class TestQuizCourseGrouping:
    """自测区按课程归组：材料按周次排序，不能让课程标题反复出现"""

    def test_each_course_heading_appears_once(self):
        # 两门课的周次交错（1/3 与 2/4），排序后会 A B A B 地交替
        text = _quiz_text(_index())
        headings = [line for line in text.splitlines() if line.startswith("### ")]

        assert headings == ["### COMP1511", "### PHYS1231"]
        assert len(headings) == len(set(headings))

    def test_all_materials_still_listed(self):
        text = _quiz_text(_index())

        for name in ("Week1_Lecture", "Lab_02", "Assignment_1",
                     "Week1_Quantum", "Week3_Tutorial", "Final_Exam"):
            assert f"**{name}**" in text

    def test_materials_sit_under_their_own_course(self):
        text = _quiz_text(_index())
        comp = text.index("### COMP1511")
        phys = text.index("### PHYS1231")

        # COMP 的材料都在 COMP 标题之后、PHYS 标题之前
        for name in ("Week1_Lecture", "Lab_02", "Assignment_1"):
            assert comp < text.index(f"**{name}**") < phys
        for name in ("Week1_Quantum", "Week3_Tutorial", "Final_Exam"):
            assert text.index(f"**{name}**") > phys

    def test_within_course_revision_order_preserved(self):
        text = _quiz_text(_index())

        # 组内仍按周次排序，未标注周次的排最后
        assert text.index("**Week1_Quantum**") < text.index("**Week3_Tutorial**")
        assert text.index("**Week3_Tutorial**") < text.index("**Final_Exam**")


def _quiz_text(index: CourseIndex) -> str:
    """取出自测区单元格的完整文本"""
    cells = notebook_dict(index)["cells"]
    quiz = [c for c in cells if c["id"] == "cell-quiz"]
    assert len(quiz) == 1
    return "".join(quiz[0]["source"])
