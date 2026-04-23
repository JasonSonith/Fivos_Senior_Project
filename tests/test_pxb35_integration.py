"""End-to-end compare_records test against the PXB35-09-17-080 device.

This device exhibits three new PR1 behaviors simultaneously:
  - Corporate alias on companyName (Medtronic vs Covidien LP)
  - GUDID description is a SKU label (short + contains model number)
  - Trademark symbol stripping on brandName (Visi-Pro™ vs Visi-Pro)
Plus a subset-match on productCodes + premarketSubmissions.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "harvester" / "src"))

import pytest

from validators.comparison_validator import compare_records, FieldStatus


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def harvested():
    with open(FIXTURES / "pxb35_harvested.json") as f:
        return json.load(f)


@pytest.fixture
def gudid():
    with open(FIXTURES / "pxb35_gudid_response.json") as f:
        return json.load(f)


def test_companyName_is_corporate_alias(harvested, gudid):
    per_field, _ = compare_records(harvested, gudid)
    assert per_field["companyName"]["status"] == FieldStatus.CORPORATE_ALIAS
    assert per_field["companyName"]["alias_group"] == "Medtronic"


def test_deviceDescription_is_sku_label_skip(harvested, gudid):
    per_field, _ = compare_records(harvested, gudid)
    assert per_field["deviceDescription"]["status"] == FieldStatus.SKU_LABEL_SKIP
    assert per_field["deviceDescription"]["similarity"] is None


def test_brandName_matches_after_trademark_strip(harvested, gudid):
    per_field, _ = compare_records(harvested, gudid)
    assert per_field["brandName"]["status"] == FieldStatus.MATCH


def test_productCodes_subset_match(harvested, gudid):
    per_field, _ = compare_records(harvested, gudid)
    # harvested ["DYB"] subset of GUDID ["DYB", "OXM"] → match
    assert per_field["productCodes"]["status"] == FieldStatus.MATCH


def test_premarketSubmissions_subset_match(harvested, gudid):
    per_field, _ = compare_records(harvested, gudid)
    # harvested ["K123456"] subset of GUDID ["K123456", "K789012"] → match
    assert per_field["premarketSubmissions"]["status"] == FieldStatus.MATCH


def test_summary_unweighted_all_match(harvested, gudid):
    """All compared fields resolve to match or corporate_alias (both count toward numerator)."""
    _per_field, summary = compare_records(harvested, gudid)
    assert summary["unweighted_numerator"] == summary["unweighted_denominator"]
    assert summary["unweighted_denominator"] > 0


def test_summary_weighted_equals_denominator(harvested, gudid):
    """Same as unweighted — everything matches (counting alias as match)."""
    _per_field, summary = compare_records(harvested, gudid)
    assert summary["numerator"] == summary["denominator"]
