"""
Contracts (data models).

This folder defines the request/response shapes for external integrations.
Examples:
- Payment request/response formats
- Underwriting quote request/response formats
- Product catalogue item formats

Why this exists:
- Ensures consistent data structures across mock and real clients
- Prevents “guessing” payload formats in multiple places
- Makes integration safer: flows rely on stable models, not on ad-hoc dicts

Both mock and real HTTP clients should use these contracts.
"""
