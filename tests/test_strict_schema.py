from openai_service import _strict_json_schema
from schemas import CandidateQuestion, ReviewResult


def _assert_all_object_fields_required(node):
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            assert node.get("additionalProperties") is False
            assert set(node.get("required", [])) == set(properties)
        for value in node.values():
            _assert_all_object_fields_required(value)
    elif isinstance(node, list):
        for value in node:
            _assert_all_object_fields_required(value)


def test_candidate_schema_is_openai_strict_compatible():
    _assert_all_object_fields_required(_strict_json_schema(CandidateQuestion))


def test_review_schema_requires_issues():
    schema = _strict_json_schema(ReviewResult)
    assert "issues" in schema["required"]
    _assert_all_object_fields_required(schema)
