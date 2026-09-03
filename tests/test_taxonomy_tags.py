"""Classifying Consensus tags into our fields.

Every expectation here comes from the live tenant, harvested 2026-08-27 via
the V2 API: 1,005 demos, 40 distinct tags, 1,945 uses, present on 42% of demos.
Nothing in this file is invented — guessing at someone else's vocabulary has
already cost this project twice.
"""
from __future__ import annotations

import pytest

from backend.services.taxonomy import classify_tag, classify_tags

#: The complete vocabulary, with its live frequency, so a change in the source
#: data shows up as a test failure rather than as silently missing metadata.
LIVE_VOCABULARY = [
    # (tag, uses, expected field, expected value)
    ("Prospecting", 275, "funnel_stage", "Awareness"),
    ("Qualifying", 273, "funnel_stage", "Consideration"),
    ("Validating", 124, "funnel_stage", "Decision"),
    ("CAD", 154, "segment", "CAD"),
    ("PLM", 118, "segment", "PLM"),
    ("ALM", 94, "segment", "ALM"),
    ("SLM", 35, "segment", "SLM"),
    ("IOT", 15, "segment", "IoT"),
    ("Technical Walkthrough", 115, "content_depth", "Walkthrough"),
    ("Technical Overview", 90, "content_depth", "Overview"),
    ("Teaser", 80, "content_depth", "Teaser"),
    ("Technical Tour", 9, "content_depth", "Walkthrough"),
    ("Creo", 134, "product", "Creo"),
    ("Codebeamer", 84, "product", "Codebeamer"),
    ("Windchill", 75, "product", "Windchill"),
    ("Navigate", 33, "product", "Navigate"),
    ("Mathcad", 19, "product", "Mathcad"),
    ("Thingworx", 15, "product", "Thingworx"),
    ("ServiceMax", 12, "product", "ServiceMax"),
    ("Modeler", 12, "product", "Modeler"),
    ("Medical Device", 2, "industry", "Medical Device"),
    ("Aerospace and Defense", 1, "industry", "Aerospace and Defense"),
    ("Automotive", 1, "industry", "Automotive"),
]

#: Tags that must stay unclassified. Each for a different reason, and each
#: reason matters more than the tag itself.
DELIBERATELY_UNCLASSIFIED = [
    ("PTC NEXT", "a campaign, not a dimension we model"),
    ("French", "duplicates the structured language field, which is 100% covered"),
    ("Korean", "same"),
    ("Artificial Inteliigence AI", "a topic, and misspelled in the source data"),
]


@pytest.mark.parametrize("tag,uses,field,value",
                         LIVE_VOCABULARY, ids=[t[0] for t in LIVE_VOCABULARY])
def test_every_live_tag_lands_in_the_right_field(tag, uses, field, value):
    assert classify_tag(tag) == (field, value)


@pytest.mark.parametrize("tag,why", DELIBERATELY_UNCLASSIFIED,
                         ids=[t[0] for t in DELIBERATELY_UNCLASSIFIED])
def test_tags_we_do_not_model_survive_as_plain_tags(tag, why):
    assert classify_tag(tag) is None, why


def test_case_differences_between_the_platforms_are_absorbed():
    """Consensus writes IOT and Thingworx; SharePoint writes IoT and
    ThingWorx. Two of forty tags, and both would have silently lost their
    segment or product."""
    assert classify_tag("IOT") == ("segment", "IoT")
    assert classify_tag("iot") == ("segment", "IoT")
    assert classify_tag("Thingworx")[0] == "product"


def test_a_brand_name_is_its_own_product():
    """The three commonest product tags -- Creo, Windchill, Codebeamer -- are
    family names. An earlier version required family_of(tag) != tag, so each
    excluded itself and product coverage was 86 of 1,005 instead of 415."""
    for brand in ("Creo", "Windchill", "Codebeamer"):
        assert classify_tag(brand) == ("product", brand)


def test_one_demo_fills_four_fields_at_once():
    """The reason tags are worth having. A real record from the tenant."""
    result = classify_tags(["PTC NEXT", "CAD", "Creo", "Prospecting", "Qualifying"])

    assert result["segment"] == "CAD"
    assert result["products"] == ["Creo"]
    assert result["content_depth"] is None
    assert result["funnel_stage"] == "Awareness", "first tag wins, not dict order"
    # PTC NEXT is not modelled and must not have become a product.
    assert "PTC NEXT" not in result["products"]


def test_conflicting_tags_keep_the_first_rather_than_an_arbitrary_one():
    assert classify_tags(["PLM", "CAD"])["segment"] == "PLM"
    assert classify_tags(["CAD", "PLM"])["segment"] == "CAD"


def test_several_products_all_survive():
    """A demo genuinely can cover more than one, so products accumulate where
    the single-valued fields do not."""
    assert classify_tags(["Creo", "Windchill", "Creo"])["products"] \
        == ["Creo", "Windchill"]


def test_empty_and_missing_tags_are_safe():
    for value in (None, [], [""], ["   "]):
        result = classify_tags(value)
        assert result["segment"] is None and result["products"] == []
