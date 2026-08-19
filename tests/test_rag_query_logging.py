import logging

import pytest

from src.rag import query as query_module
from src.rag.query import _hit_label, retrieve_context
from src.utils.rag_config_loader import load_rag_config


class FakeExpander:
    def expand_query(self, question):
        return question


class FakeEmbedder:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


HITS = [
    {
        "id": "chunk-a",
        "score": 0.9,
        "payload": {
            "doc_id": "website:product:personal/save-and-invest/somesa-education-plan",
            "title": "Somesa Education Plan",
            "text": "A flexible savings plan for education goals.",
        },
    },
    {
        "id": "chunk-b",
        "score": 0.7,
        "payload": {
            "doc_id": "website:faq/savings",
            "title": "Savings FAQs",
            "text": "Frequently asked questions about savings products.",
        },
    },
    {
        "id": "chunk-c",
        "score": 0.5,
        "payload": {
            "doc_id": "zoho:product:travel-sure-plus",
            "title": "Travel Sure Plus",
            "text": "Comprehensive travel cover for trips abroad.",
        },
    },
]


class FakeVectorStore:
    def search(self, query_vector=None, limit=5, filters=None, **kwargs):
        return [dict(h) for h in HITS[:limit]]


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(query_module, "_RETRIEVAL_CACHE", {})
    monkeypatch.setattr(query_module, "_EMBEDDING_CACHE", {})
    monkeypatch.setattr("src.utils.synonym_expander.SynonymExpander", FakeExpander)
    monkeypatch.setattr(query_module, "_embedder_from_config", lambda c: FakeEmbedder())
    monkeypatch.setattr(query_module, "_vector_store_from_config", lambda c: FakeVectorStore())

    class FakeBM25:
        def load_index(self):
            return False

    monkeypatch.setattr("src.rag.keyword_search.BM25KeywordSearch", FakeBM25)
    return load_rag_config()


def test_hit_label_prefers_doc_id_and_title():
    assert _hit_label(HITS[0]) == "website:product:personal/save-and-invest/somesa-education-plan | Somesa Education Plan"
    assert _hit_label({"id": "x", "score": 0, "payload": {}}) == "x"


def test_candidates_and_final_chunks_are_logged(cfg, caplog):
    with caplog.at_level(logging.INFO, logger="src.rag.query"):
        hits = retrieve_context("tell me about somesa", cfg, top_k=2)

    assert len(hits) == 2
    text = caplog.text

    assert "RAG fetched 3 candidate chunks for 'tell me about somesa'" in text
    for doc_id in ("somesa-education-plan", "website:faq/savings", "zoho:product:travel-sure-plus"):
        assert doc_id in text, f"candidate {doc_id} missing from logs"

    assert "RAG final chunks going to the LLM (2):" in text
    for h in hits:
        assert _hit_label(h) in text, "every final chunk must be logged"
    assert "A flexible savings plan" in text or "Comprehensive travel cover" in text or "Frequently asked" in text, (
        "final chunks include a text snippet"
    )


def test_cache_hit_still_logs_final_chunks(cfg, caplog):
    retrieve_context("same question", cfg, top_k=2)
    caplog.clear()

    with caplog.at_level(logging.INFO, logger="src.rag.query"):
        hits = retrieve_context("same question", cfg, top_k=2)

    assert len(hits) == 2
    assert "Retrieval cache hit for query" in caplog.text
    assert "RAG final chunks going to the LLM (2):" in caplog.text
