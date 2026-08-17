#!/usr/bin/env python3
"""
Retrieval safety quiz: measure how often the expected page lands in the bot's top-k.

Run against the live config/vector store:
  python scripts/eval_retrieval.py

Prints per-question results plus a summary: Hit@1, Hit@5, MRR.
The quiz lives in config/retrieval_eval.json and grows over time.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # run without .env if python-dotenv not installed

from src.rag import retrieve_context
from src.utils.rag_config_loader import load_rag_config


def _rank_of(hits, expected_doc_id: str) -> int:
    """1-based rank of the expected page among the hits, or 0 if absent."""
    for i, h in enumerate(hits, start=1):
        if (h.get("payload") or {}).get("doc_id") == expected_doc_id:
            return i
    return 0


def _chunk_rank_of(hits, expected_chunk_id: str) -> int:
    """1-based rank of the expected chunk among the hits, or 0 if absent."""
    for i, h in enumerate(hits, start=1):
        if h.get("id") == expected_chunk_id:
            return i
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the retrieval safety quiz and print scores.")
    parser.add_argument("--config", type=Path, default=None, help="Path to rag_config.yml")
    parser.add_argument("--eval", type=Path, default=None, help="Path to the eval questions JSON")
    parser.add_argument("--top-k", type=int, default=None, help="Override top_k from config")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print the top hit for each question")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    cfg = load_rag_config(args.config)
    top_k = args.top_k or cfg.retrieval.top_k

    eval_path = args.eval or Path(__file__).resolve().parent.parent / "config" / "retrieval_eval.json"
    with open(eval_path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    print(f"Running {len(questions)} retrieval questions (top_k={top_k})...")
    print()

    hit_at_1 = 0
    hit_at_5 = 0
    mrr_sum = 0.0
    chunk_hit_at_1 = 0
    chunk_hit_at_5 = 0
    chunk_mrr_sum = 0.0
    has_chunk = 0

    for q in questions:
        question = q["question"]
        expected = q["doc_id"]
        expected_chunk = q.get("chunk_id")
        hits = retrieve_context(question, cfg, top_k=top_k)

        rank = _rank_of(hits, expected)
        top = hits[0] if hits else None
        top_doc = (top or {}).get("payload", {}).get("doc_id") if top else None

        if rank == 1:
            hit_at_1 += 1
        if 1 <= rank <= top_k:
            hit_at_5 += 1
        if rank > 0:
            mrr_sum += 1.0 / rank

        chunk_line = ""
        if expected_chunk:
            has_chunk += 1
            crank = _chunk_rank_of(hits, expected_chunk)
            if crank == 1:
                chunk_hit_at_1 += 1
            if 1 <= crank <= top_k:
                chunk_hit_at_5 += 1
            if crank > 0:
                chunk_mrr_sum += 1.0 / crank
            chunk_line = f"   chunk_rank: {crank}/{top_k}"

        status = "HIT " if rank > 0 else "MISS"
        print(f"[{status}] {question}")
        print(f"        expected: {expected}")
        print(f"        rank: {rank}/{top_k}   top_doc: {top_doc}{chunk_line}")
        if args.verbose and top:
            p = top.get("payload") or {}
            text = (p.get("text") or "").strip().replace("\n", " ")
            print(f"        top title: {p.get('title')} | top text: {text[:120]}")

    n = len(questions)
    hit5 = hit_at_5
    mrr = mrr_sum / n if n else 0.0
    print()
    print(f"=== Summary (top_k={top_k}, {n} questions) ===")
    print(f"Hit@1 : {hit_at_1}/{n} = {hit_at_1 / n * 100:.1f}%")
    print(f"Hit@{top_k} : {hit5}/{n} = {hit5 / n * 100:.1f}%")
    print(f"MRR   : {mrr:.3f}")
    if has_chunk:
        ch5 = chunk_hit_at_5
        print()
        print(f"=== Chunk-level (how-to) Summary ({has_chunk} questions with chunk_id) ===")
        print(f"Chunk Hit@1 : {chunk_hit_at_1}/{has_chunk} = {chunk_hit_at_1 / has_chunk * 100:.1f}%")
        print(f"Chunk Hit@{top_k} : {ch5}/{has_chunk} = {ch5 / has_chunk * 100:.1f}%")
        print(f"Chunk MRR   : {chunk_mrr_sum / has_chunk:.3f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())