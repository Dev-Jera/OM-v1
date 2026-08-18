import json

import pytest

from src.integrations.zoho.sync import run_zoho_sync

WEB_LINE = json.dumps(
    {
        "id": "website:product:personal/insure/serenicare:overview:chunk:0.0",
        "doc_id": "website:product:personal/insure/serenicare",
        "type": "product",
        "text": "Serenicare covers dental and optical care.",
    },
    ensure_ascii=False,
)

STALE_ZOHO_LINE = json.dumps(
    {
        "id": "zoho:product:old-product:catalogue:chunk:0.0",
        "doc_id": "zoho:product:old-product",
        "type": "product",
        "text": "Old stale zoho chunk.",
    },
    ensure_ascii=False,
)

RECORDS = [
    {
        "id": "1",
        "Product_Name": "Somesa Education Plan",
        "Description": "A flexible savings plan for education.",
        "Product_Category": "Savings",
        "Active": True,
        "Unit_Price": "150000",
        "Product_Code": "SOM-1",
    },
    {
        "id": "2",
        "Product_Name": "Travel Sure Plus",
        "Description": "Comprehensive travel cover.",
        "Product_Category": "Travel",
        "Active": True,
        "Unit_Price": "250000",
        "Product_Code": "TRV-1",
    },
]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ZOHO_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "csec")
    monkeypatch.setenv("ZOHO_REFRESH_TOKEN", "rt")
    monkeypatch.setenv("ZOHO_REGION", "com")


@pytest.fixture
def fake_zoho(monkeypatch):
    class FakeCollector:
        def __init__(self, token_manager, module="Products", fields=None):
            self.token_manager = token_manager
            self.module = module
            self.fields = fields
            self.records = RECORDS

        def fetch_records(self, limit=None):
            return self.records if limit is None else self.records[:limit]

    class FakeTokenManager:
        def __init__(self, client_id, client_secret, refresh_token, region="com", session=None):
            self.client_id = client_id

    monkeypatch.setattr("src.integrations.zoho.sync.ZohoCRMProductsCollector", FakeCollector)
    monkeypatch.setattr("src.integrations.zoho.sync.ZohoTokenManager", FakeTokenManager)


def _read_lines(path):
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_sync_merges_zoho_chunks_and_preserves_website(env, fake_zoho, tmp_path):
    chunks_file = tmp_path / "website_chunks.jsonl"
    chunks_file.write_text(f"{WEB_LINE}\n{STALE_ZOHO_LINE}\n", encoding="utf-8")
    index_file = tmp_path / "website_index.json"
    index_file.write_text(json.dumps({"website:product:personal/insure/serenicare": {"type": "product"}}), encoding="utf-8")

    result = run_zoho_sync(chunks_file=chunks_file, index_file=index_file)

    assert result.records == 2
    assert result.chunks == 2
    assert result.replaced == 1
    lines = _read_lines(chunks_file)
    assert len(lines) == 3, "website line + 2 fresh zoho chunks"
    assert WEB_LINE in lines
    assert STALE_ZOHO_LINE not in lines
    zoho_doc_ids = [json.loads(l)["doc_id"] for l in lines if l.startswith('{"id": "zoho:')]
    assert zoho_doc_ids == ["zoho:product:somesa-education-plan", "zoho:product:travel-sure-plus"]

    index = json.loads(index_file.read_text(encoding="utf-8"))
    assert "zoho:product:somesa-education-plan" in index
    assert index["zoho:product:somesa-education-plan"]["type"] == "product"
    assert "website:product:personal/insure/serenicare" in index


def test_sync_is_idempotent(env, fake_zoho, tmp_path):
    chunks_file = tmp_path / "website_chunks.jsonl"
    chunks_file.write_text(f"{WEB_LINE}\n", encoding="utf-8")
    index_file = tmp_path / "website_index.json"

    run_zoho_sync(chunks_file=chunks_file, index_file=index_file)
    first = _read_lines(chunks_file)
    run_zoho_sync(chunks_file=chunks_file, index_file=index_file)
    second = _read_lines(chunks_file)

    def _zoho_signature(lines):
        return sorted(
            json.loads(l)["doc_id"]
            for l in lines
            if l.startswith('{"id": "zoho:')
        )

    assert _zoho_signature(first) == _zoho_signature(second), "re-running must not duplicate zoho chunks"
    assert len(_zoho_signature(second)) == 2
    assert len(second) == 3, "only the website line + 2 zoho chunks"


def test_sync_limit_pulls_fewer_records(env, fake_zoho, tmp_path):
    chunks_file = tmp_path / "website_chunks.jsonl"
    chunks_file.write_text("", encoding="utf-8")
    index_file = tmp_path / "website_index.json"

    result = run_zoho_sync(chunks_file=chunks_file, index_file=index_file, limit=1)

    assert result.records == 1
    assert result.chunks == 1
    lines = _read_lines(chunks_file)
    assert len(lines) == 1
    assert "somesa-education-plan" in lines[0]


def test_sync_requires_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("ZOHO_CLIENT_ID", raising=False)
    monkeypatch.delenv("ZOHO_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("ZOHO_REFRESH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="ZOHO_CLIENT_ID"):
        run_zoho_sync(chunks_file=tmp_path / "x.jsonl", index_file=tmp_path / "x.json")
