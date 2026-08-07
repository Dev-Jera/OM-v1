"""Error handling helpers for RAG processing pipeline."""
from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


class ErrorHandler:
    def handle_exception(self, exc: Exception, context: Dict[str, Any] = None) -> Dict[str, Any]:
        logger.error("Unhandled exception in RAG pipeline: %s", exc, exc_info=True)
        return {
            "message": "An internal error occurred while processing your request. Please try again later.",
            "follow_up": False,
            "fallback": True,
            "metadata": {"error": str(exc), "context": context or {}},
        }
