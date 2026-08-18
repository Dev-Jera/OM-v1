"""System-generated demo-data walkthrough.

Drives ~25 real conversations through the LIVE chatbot API so the metrics and
dashboard reflect demo data that the system itself produced (not random seeder
figures).

Scenarios:
  12 resolved      - product question -> answer -> "bye" -> completion "yes"
   4 escalated     - agent request -> confirmation -> escalate + agent join
   4 unresolved    - question -> answer -> "bye" -> completion "no"
   2 guided quote -> payment (travel insurance full form + MTN mock payment)
   3 trust-unit    - same user, 3 quick back-to-back sessions (repeat-user)

Safe to re-run (demo-* users only). Uses X-API-KEY on every call.
"""

import sys
import time
from datetime import date, timedelta

import requests

API = "https://om-v1.onrender.com/api/v1"
API_KEY = "JAWNlQeUuLQNMNLWWAfwJSCH72K6GFtueLsR0s6uUdU"
HEADERS = {"X-API-KEY": API_KEY, "Content-Type": "application/json"}

S = requests.Session()
S.trust_env = False

COMPLETION_ASK = "Did I answer everything"

RESULTS = []


def api(path, payload=None, method="post", timeout=180):
    url = f"{API}{path}"
    if method == "get":
        r = S.get(url, headers=HEADERS, timeout=timeout)
    else:
        r = S.post(url, headers=HEADERS, json=payload or {}, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"{method.upper()} {path} -> HTTP {r.status_code}: {r.text[:400]}")
    return r.json()


def new_session(user_id):
    data = api("/session", {"user_id": user_id})
    sid = data.get("session_id") or data.get("id")
    return sid


def send(sid, user_id, message):
    body = api("/chat/message", {"session_id": sid, "user_id": user_id, "message": message})
    resp = body.get("response") or {}
    return resp


def answer_text(resp):
    return str(resp.get("response") or "").strip()


def say(sid, user_id, message, label="", quiet=False):
    resp = send(sid, user_id, message)
    text = answer_text(resp)
    if not quiet:
        print(f"    [{label}] U: {message[:70]}")
        print(f"    [{label}] MIA: {text[:160]}")
    return resp, text


def resolved(user_id, question):
    print(f"\n== RESOLVED {user_id}")
    sid = new_session(user_id)
    resp, text = say(sid, user_id, question, "Q")
    if not text:
        RESULTS.append((user_id, "resolved", "empty-answer"))
        return
    resp, text = say(sid, user_id, "bye", "bye")
    if COMPLETION_ASK not in text:
        RESULTS.append((user_id, "resolved", "no-completion"))
        return
    resp, text = say(sid, user_id, "yes", "fin")
    out = "resolved" if resp.get("outcome") == "resolved" else "unexpected"
    RESULTS.append((user_id, "resolved", out))


def escalated(user_id, request_msg):
    print(f"\n== ESCALATED {user_id}")
    sid = new_session(user_id)
    resp, text = say(sid, user_id, request_msg, "ask")
    if not text:
        RESULTS.append((user_id, "escalated", "empty-answer"))
        return
    resp, text = say(sid, user_id, "yes", "confirm")
    if resp.get("mode") == "escalated" or resp.get("escalated"):
        api("/escalate/agent-join", {"session_id": sid, "agent_id": "agent-1"})
        RESULTS.append((user_id, "escalated", "escalated+agent"))
        return
    # Fallback: force escalation through the direct endpoint.
    api("/escalate", {"session_id": sid, "reason": "customer_requested_agent"})
    api("/escalate/agent-join", {"session_id": sid, "agent_id": "agent-1"})
    RESULTS.append((user_id, "escalated", "escalated-via-endpoint"))


def unresolved(user_id, question):
    print(f"\n== UNRESOLVED {user_id}")
    sid = new_session(user_id)
    resp, text = say(sid, user_id, question, "Q")
    if not text:
        RESULTS.append((user_id, "unresolved", "empty-answer"))
        return
    resp, text = say(sid, user_id, "bye", "bye")
    if COMPLETION_ASK not in text:
        RESULTS.append((user_id, "unresolved", "no-completion"))
        return
    resp, text = say(sid, user_id, "no", "fin")
    out = "unresolved" if resp.get("outcome") == "unresolved" else "unexpected"
    RESULTS.append((user_id, "unresolved", out))


def guided_quote_payment(user_id):
    print(f"\n== GUIDED QUOTE -> PAYMENT {user_id}")
    sid = new_session(user_id)
    resp, text = say(sid, user_id, "I want to get a quote for travel insurance", "Q")
    d1 = (date.today() + timedelta(days=14)).isoformat()
    d2 = (date.today() + timedelta(days=20)).isoformat()
    form = api(
        "/forms/travel-insurance/full",
        {
            "user_id": user_id,
            "data": {
                "product_id": "worldwide_essential",
                "first_name": "Ruth",
                "middle_name": "N",
                "surname": "Atim",
                "phone_number": "0773333333",
                "email": "ruth@example.com",
                "travel_party": "myself_only",
                "num_travellers_18_69": 1,
                "num_travellers_0_17": 0,
                "num_travellers_70_75": 0,
                "num_travellers_76_80": 0,
                "num_travellers_81_85": 0,
                "departure_country": "Uganda",
                "destination_country": "Kenya",
                "departure_date": d1,
                "return_date": d2,
                "terms_and_conditions_agreed": True,
                "consent_data_outside_uganda": True,
                "consent_child_data": False,
                "consent_marketing": False,
                "passport_number": "B1234567",
                "date_of_birth": "1992-05-10",
                "occupation": "Designer",
                "postal_address": "P.O. Box 123, Kampala",
                "town_city": "Kampala",
                "office_number": "0414000000",
                "ec_surname": "Akena",
                "ec_relationship": "Sister",
                "ec_phone_number": "0773444444",
                "ec_email": "family@example.com",
            },
        },
    )
    quote_id = form.get("quote_id")
    premium = form.get("total_premium_ugx") or form.get("monthly_premium") or 10000
    print(f"    quote_id={quote_id} premium={premium}")
    if not quote_id:
        RESULTS.append((user_id, "guided", "no-quote"))
        return
    api(
        "/payments/initiate",
        {
            "quote_id": quote_id,
            "provider": "mtn",
            "phone_number": "256773333333",
            "amount": float(premium),
            "currency": "UGX",
        },
    )
    api(f"/payments/mock/trigger-callback/{quote_id}", {"outcome": "success"})
    status = api(f"/payments/status/{quote_id}", method="get")
    pay_status = (status.get("status") or status.get("payment_status") or "").upper()
    print(f"    payment status: {pay_status}")
    RESULTS.append((user_id, "guided", f"quote+payment={pay_status}"))


def trust_unit(user_id):
    questions = [
        "How do I check my Unit Trust balance?",
        "How do I buy more unit trust units?",
        "How do I redeem my unit trust units?",
    ]
    print(f"\n== TRUST-UNIT {user_id} (3 back-to-back sessions)")
    for q in questions:
        sid = new_session(user_id)
        resp, text = say(sid, user_id, q, "Q")
        RESULTS.append((user_id, "trust-unit", "ok" if text else "empty-answer"))
        time.sleep(1)


def main():
    resolved_qs = [
        "What does the Serenicare health plan cover?",
        "How do I pay for my Umbrella scheme contributions?",
        "What is the excess on motor private insurance?",
        "What does Personal Accident insurance cover?",
        "Can I extend my travel insurance cover?",
        "Is there a waiting period for maternity on Serenicare?",
        "How long does a claims process take?",
        "What documents do I need to make a claim?",
        "Can I pay my premiums monthly?",
        "How do I register for my Unit Trust?",
        "What is covered by the Fire and Domestic policy?",
        "How do I get a quote for motor insurance?",
    ]
    esc_reqs = [
        "I need to speak to a human agent about my claim",
        "Can I talk to someone from customer care?",
        "Please connect me to a human, this is urgent",
        "I want to speak to an agent please",
    ]
    unr_qs = [
        "What is the exact premium for fire insurance in Kampala?",
        "How do I cancel my policy and get a refund?",
        "What happens to my savings if the fund performs poorly?",
        "Can I insure my business premises?",
    ]

    for i, q in enumerate(resolved_qs, 1):
        resolved(f"demo-res-{i:02d}", q)
    for i, r in enumerate(esc_reqs, 1):
        escalated(f"demo-esc-{i:02d}", r)
    for i, q in enumerate(unr_qs, 1):
        unresolved(f"demo-unr-{i:02d}", q)
    guided_quote_payment("demo-gui-01")
    guided_quote_payment("demo-gui-02")
    trust_unit("demo-trust-01")

    print("\n\n==== WALKTHROUGH SUMMARY ====")
    from collections import Counter

    by_kind = Counter(r[1] for r in RESULTS)
    print(f"total conversations: {len(RESULTS)}")
    for kind, n in sorted(by_kind.items()):
        print(f"  {kind}: {n}")
    print("\nper-conversation detail:")
    for r in RESULTS:
        print("  ", r)


if __name__ == "__main__":
    main()