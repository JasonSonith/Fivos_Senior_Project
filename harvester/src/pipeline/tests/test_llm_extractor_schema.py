import pytest
from pipeline.llm_extractor import PAGE_FIELDS_SCHEMA


def test_schema_includes_new_fields():
    props = PAGE_FIELDS_SCHEMA["properties"]
    assert "indicationsForUse" in props
    assert "contraindications" in props
    assert "deviceClass" in props


def test_schema_no_longer_has_premarket_submissions():
    """premarketSubmissions moved to regex in Task 7; LLM no longer sees it."""
    assert "premarketSubmissions" not in PAGE_FIELDS_SCHEMA["properties"]


def test_deviceClass_enum_restriction():
    props = PAGE_FIELDS_SCHEMA["properties"]
    assert props["deviceClass"]["enum"] == ["I", "II", "III", None]
