#!/usr/bin/env python3
"""
Test script for the Travel Insurance flow via the chatbot API.

Start the API first (in another terminal):
  cd /path/to/rag
  uvicorn src.api.main:app --host 127.0.0.1 --port 8000

Then run this script:
  python scripts/test_travel_insurance_api.py
  python scripts/test_travel_insurance_api.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict

import requests


def post_json(url: str, data: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    r = requests.post(url, json=data, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_json(url: str, timeout: int = 30) -> Dict[str, Any]:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Travel Insurance flow via chatbot API")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--user-id", default="test-travel-001", help="User identifier")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    user_id = args.user_id

    print("=== Travel Insurance flow API test ===\n")
    print(f"Base URL: {base}")
    print(f"User ID:  {user_id}\n")

    # 1) Create session
    print("1) POST /api/v1/session")
    try:
        out = post_json(f"{base}/api/v1/session", {"user_id": user_id})
        session_id = out["session_id"]
        print(f"   session_id: {session_id}\n")
    except requests.RequestException as e:
        print(f"   FAIL: {e}")
        if "Connection refused" in str(e) or "Failed to establish" in str(e):
            print("   → Start the API first: uvicorn src.api.main:app --host 127.0.0.1 --port 8000")
        return 1

    # 2) Start Travel Insurance flow via message trigger
    print("2) POST /api/v1/chat/message (trigger: 'I want travel insurance')")
    try:
        out = post_json(
            f"{base}/api/v1/chat/message",
            {"user_id": user_id, "session_id": session_id, "message": "I want travel insurance"},
        )
        resp = out.get("response", {})
        if isinstance(resp, dict):
            inner = resp.get("response", resp)
            msg = inner.get("message", str(inner)) if isinstance(inner, dict) else str(inner)
            products = inner.get("products", []) if isinstance(inner, dict) else []
            print(f"   response: {msg[:100]}...")
            print(f"   products: {len(products)} options\n")
        else:
            print(f"   response: {str(resp)[:150]}\n")
    except requests.RequestException as e:
        print(f"   FAIL: {e}\n")
        return 1

    # 3) Submit product selection
    print("3) POST /api/v1/chat/message (form_data: product_selection)")
    try:
        out = post_json(
            f"{base}/api/v1/chat/message",
            {"user_id": user_id, "session_id": session_id, "message": "", "form_data": {"product_id": "worldwide_essential"}},
        )
        payload = out.get("response", {})
        inner = payload.get("response", payload) if isinstance(payload, dict) else payload
        msg = inner.get("message", str(inner)[:80]) if isinstance(inner, dict) else str(inner)[:80]
        print(f"   next: {msg}\n")
    except requests.RequestException as e:
        print(f"   FAIL: {e}\n")
        return 1

    # 4) Submit about you
    print("4) POST /api/v1/chat/message (form_data: about_you)")
    try:
        out = post_json(
            f"{base}/api/v1/chat/message",
            {
                "user_id": user_id,
                "session_id": session_id,
                "message": "",
                "form_data": {
                    "first_name": "Jane",
                    "surname": "Traveler",
                    "email": "jane@example.com",
                    "phone_number": "0772123456",
                },
            },
        )
        payload = out.get("response", {})
        inner = payload.get("response", payload) if isinstance(payload, dict) else payload
        msg = inner.get("message", str(inner)[:80]) if isinstance(inner, dict) else str(inner)[:80]
        print(f"   next: {msg}\n")
    except requests.RequestException as e:
        print(f"   FAIL: {e}\n")
        return 1

    # 5) Get session state
    print("5) GET /api/v1/session/{session_id}")
    try:
        state = get_json(f"{base}/api/v1/session/{session_id}")
        print(f"   flow={state.get('current_flow')} step={state.get('current_step')} step_name={state.get('step_name')}\n")
    except requests.RequestException as e:
        print(f"   FAIL: {e}\n")
        return 1

    # 6) Get travel insurance schema
    print("6) GET /api/v1/flows/travel_insurance/schema")
    try:
        schema = get_json(f"{base}/api/v1/flows/travel_insurance/schema")
        steps = schema.get("steps", [])
        print(f"   flow_id={schema.get('flow_id')} steps={len(steps)}\n")
    except requests.RequestException as e:
        print(f"   FAIL: {e}\n")
        return 1

    print("=== Travel Insurance flow API test completed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
