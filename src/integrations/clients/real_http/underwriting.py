"""
Real Underwriting HTTP Client.

Purpose:
- Sends collected user input (KYC + coverage details) to Old Mutual underwriting endpoints
- Receives premium/decision responses and normalizes them into our contract format

Usage:
- Wired in src/api/main.py when OM underwriting API endpoints are available
- Called by UnderwritingFlow via the UnderwritingClient interface

Implementation notes:
- Use httpx for async requests
- Normalize response fields so flows receive consistent keys (quote_id, premium, status)
- Handle errors gracefully and return actionable error details for the chatbot to display

Important:
- Keep this client as the ONLY place where underwriting HTTP calls are made.
"""
