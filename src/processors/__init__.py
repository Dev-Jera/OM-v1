"""
Processors package.

Processing turns raw scraped data into cleaned, chunked JSONL suitable for embeddings/RAG.
"""

from .website_processor import WebsiteProcessor
from .oldmutual_cleaner import OldMutualCleaner

__all__ = ["WebsiteProcessor", "OldMutualCleaner"]
