"""
Real HTTP integration clients.

These clients are intended to communicate with real external systems via HTTP, e.g.:
- Old Mutual underwriting APIs
- payment APIs / MoMo integrations
- Zoho product catalogue APIs

Important:
- Must implement the same interfaces as the mock clients
- Must return data shaped according to src/integrations/contracts/*

Switching:
The selection of mock vs real clients should happen in src/api/main.py only.
"""
