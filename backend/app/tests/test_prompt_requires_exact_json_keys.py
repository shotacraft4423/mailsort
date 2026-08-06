"""Regression coverage for the actual root cause behind "すべてがオフライン
簡易ルールで振り分けられてる", found from real production logs: the
provider call was succeeding every time (no HTTP error) but the model
returned JSON with its own translated key names —
{"案件か人材か": "...", "温度感": "普通"} — instead of
{"mail_type": "...", "temperature": "普通"}. Because ClassificationResult.
mail_type is required, any key-name deviation is a guaranteed
ValidationError, reproducing 100% of the time rather than intermittently.
Both prompt-construction paths must now spell out the literal field names
the model has to use."""
from __future__ import annotations

from app.schemas.classification import ClassificationResult
from app.schemas.extraction import ExtractionResult
from app.services import analysis_service, classification_service


def test_combined_system_prompt_lists_the_literal_classification_field_names(db_session):
    system_prompt, _template_id = analysis_service._combined_system_prompt(db_session)

    assert "mail_type" in system_prompt
    assert "categories" in system_prompt
    assert "reply_required" in system_prompt


def test_combined_system_prompt_lists_the_literal_extraction_field_names(db_session):
    system_prompt, _template_id = analysis_service._combined_system_prompt(db_session)

    assert "project_name" in system_prompt
    assert "unit_price" in system_prompt


def test_combined_prompt_field_list_is_derived_from_the_actual_models(db_session):
    """Guards against the instruction text drifting out of sync with the
    schema if a field is ever renamed/added/removed."""
    system_prompt, _template_id = analysis_service._combined_system_prompt(db_session)

    for field_name in ClassificationResult.model_fields:
        assert field_name in system_prompt
    for field_name in ExtractionResult.model_fields:
        assert field_name in system_prompt


def test_standalone_classify_instruction_lists_the_literal_field_names():
    instruction = classification_service._required_json_key_instruction()

    assert "mail_type" in instruction
    for field_name in ClassificationResult.model_fields:
        assert field_name in instruction
