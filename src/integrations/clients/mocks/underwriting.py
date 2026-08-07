"""Backward-compatible exports for underwriting mocks.

Primary implementation now lives under
``src.integrations.clients.mocks.underwriting_mocks.underwriting`` so all
underwriting mock assets stay in one folder.
"""

from .underwriting_mocks.underwriting import MockUnderwritingClient, mock_underwriting_client

__all__ = ["MockUnderwritingClient", "mock_underwriting_client"]
# Compatibility re-export module.
