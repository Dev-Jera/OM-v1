"""
Mock integration clients.

These clients return fake (but realistic) responses without calling any external API.
They are used when:
- Old Mutual APIs are not yet available
- We want to test flows end-to-end without external dependencies

Important:
- Mock clients must follow the SAME interface as real HTTP clients.
- Mock clients should return data shaped according to src/integrations/contracts/*

Switching to real:
When real endpoints and credentials are provided, swap clients in src/api/main.py
to use clients/real_http/* implementations instead.
"""
