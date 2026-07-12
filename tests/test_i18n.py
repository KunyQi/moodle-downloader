"""
测试 i18n — 中/英目录完整性、t() 格式化、语言切换与配置加载
"""
from __future__ import annotations

import string

import pytest

from moodle_scraper import i18n
from moodle_scraper.config import AppConfig
from moodle_scraper.i18n import (
    CATALOGS,
    DEFAULT_LANGUAGE,
    get_language,
    resolve_language,
    set_language,
    t,
)


@pytest.fixture(autouse=True)
def _restore_language():
    """每个测试后恢复默认语言，避免全局状态泄漏"""
    yield
    set_language(DEFAULT_LANGUAGE)


def _format_fields(template: str) -> set[str]:
    """提取模板中的 {field} 名称"""
    return {
        field for _, field, _, _ in string.Formatter().parse(template)
        if field is not None
    }


class TestCatalogIntegrity:
    """中英目录必须键集一致、占位符一致"""

    def test_catalogs_have_same_keys(self):
        zh_keys = set(CATALOGS["zh"])
        en_keys = set(CATALOGS["en"])
        assert zh_keys == en_keys, (
            f"仅中文有: {zh_keys - en_keys}; 仅英文有: {en_keys - zh_keys}"
        )

    def test_placeholders_match_between_languages(self):
        for key in CATALOGS["zh"]:
            zh_fields = _format_fields(CATALOGS["zh"][key])
            en_fields = _format_fields(CATALOGS["en"][key])
            assert zh_fields == en_fields, f"{key}: zh={zh_fields} en={en_fields}"

    def test_no_empty_messages(self):
        for lang, catalog in CATALOGS.items():
            for key, template in catalog.items():
                assert template.strip(), f"{lang}:{key} 为空"


class TestTranslate:
    """t() 取词与格式化"""

    def test_default_language_is_chinese(self):
        assert get_language() == "zh"
        assert t("flow.cancelled") == "已取消"

    def test_english_after_set_language(self):
        set_language("en")
        assert t("flow.cancelled") == "Cancelled"

    def test_formats_kwargs(self):
        set_language("en")
        assert t("flow.confirm_download", count=5) == "5 files found. Download now?"

    def test_formats_kwargs_chinese(self):
        assert t("flow.confirm_download", count=5) == "共 5 个文件，确认下载？"

    def test_unknown_key_returns_key(self):
        assert t("no.such.key") == "no.such.key"

    def test_missing_kwargs_returns_template(self):
        # 缺少格式参数时不抛异常，返回未格式化模板
        result = t("flow.confirm_download", wrong_field=1)
        assert "{count}" in result

    def test_every_key_formats_without_error(self):
        """所有键在两种语言下都能用占位符字段格式化"""
        for lang in CATALOGS:
            set_language(lang)
            for key, template in CATALOGS[lang].items():
                kwargs = {f: "x" for f in _format_fields(template)}
                out = t(key, **kwargs) if kwargs else t(key)
                assert isinstance(out, str) and out


class TestLanguageResolution:
    """语言别名解析与切换"""

    @pytest.mark.parametrize("alias", ["en", "EN", "En", "english", "en-US", "en_US", "en-AU"])
    def test_english_aliases(self, alias):
        assert resolve_language(alias) == "en"

    @pytest.mark.parametrize("alias", ["zh", "ZH", "cn", "zh-CN", "zh_cn", "chinese", "中文"])
    def test_chinese_aliases(self, alias):
        assert resolve_language(alias) == "zh"

    @pytest.mark.parametrize("bad", ["", "klingon", "fr", None])
    def test_unknown_returns_none(self, bad):
        assert resolve_language(bad) is None

    def test_set_language_accepts_alias(self):
        assert set_language("English") == "en"
        assert get_language() == "en"

    def test_set_language_rejects_unknown(self):
        with pytest.raises(ValueError):
            set_language("klingon")
        # 失败后语言保持不变
        assert get_language() == DEFAULT_LANGUAGE


class TestConfigLanguage:
    """AppConfig 从 config.toml 读取 language"""

    def test_default_is_chinese(self):
        assert AppConfig().language == "zh"

    def test_loads_language_from_toml(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text('[ui]\nlanguage = "en"\n', encoding="utf-8")
        cfg = AppConfig.load(cfg_file)
        assert cfg.language == "en"

    def test_missing_language_falls_back(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text('[ui]\ntheme = "default"\n', encoding="utf-8")
        cfg = AppConfig.load(cfg_file)
        assert cfg.language == "zh"
