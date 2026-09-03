import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from zoho_create_modules import ESCALATIONS_MODULE, FIELD_API_NAMES, METRICS_MODULE  # noqa: E402

VALID_DATA_TYPES = {
    "text", "textarea", "integer", "double", "percent", "date", "datetime",
    "picklist", "phone", "email", "url", "checkbox",
}


def test_metrics_module_definition_is_well_formed():
    assert METRICS_MODULE["module_name"] == "Mia_Bot_Metrics"
    labels = [f["field_label"] for f in METRICS_MODULE["fields"]]
    assert len(labels) == len(set(labels)), "field labels must be unique"
    for field in METRICS_MODULE["fields"]:
        assert field["data_type"] in VALID_DATA_TYPES
    assert "Metric Date" in labels


def test_escalations_module_definition_is_well_formed():
    assert ESCALATIONS_MODULE["module_name"] == "MiaEscalations"
    labels = [f["field_label"] for f in ESCALATIONS_MODULE["fields"]]
    assert len(labels) == len(set(labels))
    for field in ESCALATIONS_MODULE["fields"]:
        assert field["data_type"] in VALID_DATA_TYPES
    status = next(f for f in ESCALATIONS_MODULE["fields"] if f["field_label"] == "Status")
    values = [v["actual_value"] for v in status["pick_list_values"]]
    assert values == ["New", "In Progress", "Closed"]


def test_expected_api_names_match_label_derivation():
    """CRM derives api names from labels (spaces -> underscores). The push
    code writes to these exact names, so keep the two in lockstep."""
    for module in (METRICS_MODULE, ESCALATIONS_MODULE):
        expected = FIELD_API_NAMES[module["module_name"]]
        derived = [f["field_label"].replace(" ", "_") for f in module["fields"]]
        assert derived == expected, f"{module['module_name']}: labels no longer map to the api names the push code uses"


def test_metrics_fields_cover_everything_push_writes():
    from src.integrations.zoho.push_metrics import impact_payload_to_crm_record

    daily = impact_payload_to_crm_record({}, "2026-08-18")
    hourly = impact_payload_to_crm_record({}, "2026-08-18", metric_hour=14)
    expected = FIELD_API_NAMES["Mia_Bot_Metrics"]
    # Daily rows omit Metric_Hour; hourly rows include it. Together they cover all documented fields.
    assert sorted(set(daily) | set(hourly)) == sorted(expected)


def test_escalation_fields_cover_everything_push_writes():
    from src.integrations.zoho.escalation_push import build_escalation_record

    record = build_escalation_record(session_id="s", reason="r", user_id=None, metadata=None, db=None)
    expected = FIELD_API_NAMES["MiaEscalations"]
    assert sorted(record.keys()) == sorted(expected)
