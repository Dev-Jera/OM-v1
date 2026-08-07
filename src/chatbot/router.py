"""
Compatibility wrapper for ChatRouter.

The original implementation lives in `src/chatbot/flows/router.py`, but
the FastAPI app imports `src.chatbot.router`. This module simply
re-exports the class so both import paths work.
"""

from .flows.router import ChatRouter

__all__ = ["ChatRouter"]
