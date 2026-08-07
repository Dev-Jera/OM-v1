"""
Mock Payments Client.

Purpose:
- Provides a fake payment integration used for development/testing
- Does NOT make any network calls
- Returns deterministic or simulated payment responses

Usage:
- Wired in src/api/main.py when running in development mode
- Called by PaymentFlow via the PaymentClient interface

Behavior guidelines:
- initiate_payment(...) should return a transaction reference and "pending" status
- check_status(...) should return "completed" or "failed" based on mock rules

Swap:
Replace this mock client with the real HTTP client in clients/real_http/payments.py
when payment API details are provided.
"""
