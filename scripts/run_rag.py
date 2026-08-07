#!/usr/bin/env python3
"""
Query the RAG index:
- embed query
- retrieve top-k chunks (pgvector or Qdrant)
- print sources + (optional) generate answer

Chat mode: run with --chat for an interactive back-and-forth in the terminal.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # run without .env if python-dotenv not installed

from src.utils.rag_config_loader import load_rag_config
from src.rag import retrieve_context
from src.rag.generate import generate_with_gemini
from src.rag.query import get_vector_table_count

# Commands that exit chat mode
CHAT_EXIT = frozenset({"quit", "exit", "q", "bye"})


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def run_one_question(question: str, cfg, top_k: int, verbose: bool) -> None:
    """Retrieve context and optionally generate answer for a single question."""
    hits = retrieve_context(question, cfg, top_k=top_k)

    if not hits:
        print("\n### Retrieved context\n")
        n = get_vector_table_count(cfg) if cfg else None
        if n is not None:
            print(f"(No chunks matched. Table '{getattr(cfg.vector_store, 'collection', 'old_mutual_chunks')}' has {n} rows.)")
            if n > 0:
                print("So the DB has data — same DATABASE_URL and table. The query may not match any rows.")
                print("Check that this run uses the same config (table, embedding model) as when you ran generate_embeddings.")
            else:
                print("Table is empty. Populate with: python scripts/generate_embeddings.py")
        else:
            print("(Could not get table count. Populate with: python scripts/generate_embeddings.py)")
        print("Uses DATABASE_URL and config/rag_config.yml; chunks from data/processed/.\n")
        print("### Answer\n")
        print("I couldn't find any relevant content in the knowledge base for that question.")
        if n and n > 0:
            print("The vector store has data; try rephrasing or check embedding model vs. ingest.")
        else:
            print("If you just set up RAG, run: python scripts/generate_embeddings.py")
        return

    if verbose:
        print("\n### Retrieved context\n")
        for i, h in enumerate(hits, start=1):
            p = h["payload"]
            print(f"[{i}] score={h['score']:.4f} chunk_id={h['id']}")
            print(f"    type={p.get('type')} chunk_type={p.get('chunk_type')} title={p.get('title')}")
            print(f"    url={p.get('url')}")
            if p.get("section_heading"):
                print(f"    heading={p.get('section_heading')}")
            text = (p.get("text") or "").strip()
            preview = text[:350].replace("\n", "\\n")
            print(f"    text={preview}")
            print()

    if cfg.generation.enabled:
        try:
            if cfg.generation.backend == "gemini":
                answer = generate_with_gemini(
                    question=question,
                    hits=hits,
                    model=cfg.generation.model,
                    api_key_env=cfg.generation.api_key_env,
                )
            else:
                from openai import OpenAI
                client = OpenAI()
                context = "\n\n".join([h["payload"].get("text", "") for h in hits])
                prompt = (
                    "You are a helpful assistant. Answer the question using ONLY the context.\n"
                    "If the context is insufficient, say what is missing.\n\n"
                    f"Question: {question}\n\n"
                    f"Context:\n{context}\n"
                )
                resp = client.chat.completions.create(
                    model=cfg.generation.model,
                    messages=[{"role": "user", "content": prompt}],
                )
                answer = resp.choices[0].message.content

            print("\n### Answer\n")
            print(answer)
        except Exception as e:
            print("\n### Answer\n")
            print(f"[Generation failed: {type(e).__name__}: {e}]")
            print("Fix generator quota/keys or disable generation in config.")
    else:
        print("\n### Top contexts (generation disabled)\n")
        for i, h in enumerate(hits[:5], start=1):
            print(f"[{i}] {h['payload'].get('text', '')[:200]}...")
            print()


def chat_loop(cfg, top_k: int, verbose: bool) -> None:
    """Interactive chat: prompt, answer, repeat until user types quit/exit/q."""
    print("RAG chat (Old Mutual). Type a question and press Enter.")
    print("Commands: quit, exit, q, bye — end session. Ctrl+D or empty line also exits.\n")
    while True:
        try:
            line = input("You: ").strip()
        except EOFError:
            print("\nBye.")
            break
        if not line:
            print("(empty — use quit to exit)")
            continue
        if line.lower() in CHAT_EXIT:
            print("Bye.")
            break
        run_one_question(line, cfg, top_k, verbose)
        print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query Old Mutual RAG index. Use --chat for interactive mode."
    )
    parser.add_argument(
        "question",
        type=str,
        nargs="?",
        default=None,
        help="Single question (omit when using --chat)",
    )
    parser.add_argument("--chat", "-c", action="store_true", help="Run in chat mode (back-and-forth in terminal)")
    parser.add_argument("--config", type=Path, default=None, help="Path to rag_config.yml")
    parser.add_argument("--top-k", type=int, default=None, help="Override top_k from config")
    parser.add_argument("--verbose", "-v", action="store_true", help="In chat mode, show retrieved context each turn")
    args = parser.parse_args()

    if args.chat and args.question is not None:
        parser.error("Do not pass a question when using --chat; use --chat to start a conversation.")

    if not args.chat and args.question is None:
        parser.error("Provide a question, or use --chat for interactive mode. Examples:\n  python scripts/run_rag.py 'What is Serenicare?'\n  python scripts/run_rag.py --chat")

    setup_logging(args.verbose)
    cfg = load_rag_config(args.config)
    top_k = args.top_k or cfg.retrieval.top_k

    if args.chat:
        chat_loop(cfg, top_k, args.verbose)
    else:
        run_one_question(args.question, cfg, top_k, args.verbose)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

