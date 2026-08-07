import json
from pathlib import Path

from general_information.general_info_handler import generate_general_info_files
from src.api.main import _general_info_candidate_paths, _normalize_general_info_key


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_processed_product_documents_load_successfully():
    input_path = _repo_root() / "data" / "processed" / "website_documents.jsonl"
    assert input_path.exists()

    found_product = False
    found_serenicare = False

    with input_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            doc = json.loads(line)
            if doc.get("type") != "product":
                continue
            found_product = True
            if doc.get("product_id") == "serenicare":
                found_serenicare = True
                break

    assert found_product
    assert found_serenicare


def test_generate_general_info_for_serenicare(tmp_path: Path):
    input_path = _repo_root() / "data" / "processed" / "website_documents.jsonl"
    summary = generate_general_info_files(input_path=input_path, output_dir=tmp_path, overwrite=False)

    assert summary["seen_products"] > 0

    serenicare_file = tmp_path / "serenicare.json"
    assert serenicare_file.exists()

    payload = json.loads(serenicare_file.read_text(encoding="utf-8"))

    assert payload["product_id"] == "serenicare"
    assert payload["title"]
    assert payload["definition"]
    assert isinstance(payload["benefits"], list)
    assert payload["benefits"]
    assert payload["eligibility"]
    assert payload["source_url"]


def test_general_info_alias_resolution_travel_to_canonical():
    normalized = _normalize_general_info_key("website:product:personal/insure/serenicare")
    assert normalized == "serenicare"

    normalized_path = _normalize_general_info_key("personal/insure/serenicare")
    assert normalized_path == "serenicare"

    candidates = _general_info_candidate_paths("travel", Path("general_information/product_json"))
    assert candidates
    assert candidates[0].name in {"travel.json", "travel-sure-plus-insurance.json"}
