"""Synthetic demo-data seeder.

Writes realistic conversations, events and metrics into the database so the
admin dashboards show meaningful volumes and trends before real production
traffic arrives. Safe to re-run: each run creates a fresh randomized dataset.

Not for production use with real customers.
"""

import random
from datetime import datetime, timedelta
from typing import Any, Dict

random.seed(20260817)

PRODUCTS = [
    "Motor Private",
    "Personal Accident",
    "Travel Insurance",
    "Serenicare",
    "Fire & Domestic",
]

SAMPLE_QUESTIONS = [
    "How much does motor comprehensive cover?",
    "What is the excess on this policy?",
    "Can I extend my travel insurance?",
    "Do you cover pre-existing conditions?",
    "How long does a claim take?",
    "What documents do I need?",
    "Is there a waiting period?",
    "Can I pay monthly?",
]


def seed_demo_data(db: Any, days: int = 30) -> Dict[str, int]:
    now = datetime.utcnow()
    start = now - timedelta(days=days)
    span_seconds = int((now - start).total_seconds())

    stats: Dict[str, int] = {
        "users": 0,
        "conversations": 0,
        "events": 0,
        "metrics": 0,
        "quotes": 0,
        "payments": 0,
    }

    users = []
    for i in range(40):
        user = db.get_or_create_user(f"25670{i:05d}0")
        users.append(user)
    stats["users"] = len(users)

    # Link most users to a Zoho contact so repeat detection can demo the
    # Zoho-identity basis (same human across phones). A few users share a
    # contact id to show cross-phone merging.
    if hasattr(db, "set_zoho_contact"):
        for i, user in enumerate(users):
            if random.random() < 0.6:
                db.set_zoho_contact(user.id, f"ZOHO-{(i * 7) % 31}")

    for conv_index in range(160):
        user = random.choice(users)
        ts = start + timedelta(seconds=random.randint(0, span_seconds))
        mode = "guided" if random.random() < 0.35 else "conversational"
        conv = db.create_conversation(user_id=str(user.id), mode=mode, created_at=ts)
        conversation_id = conv.id
        stats["conversations"] += 1

        # Path attribution: first interaction style.
        roll = random.random()
        if roll < 0.30:
            path, source = "guided_flow", "start_flow"
        elif roll < 0.42:
            path, source = "direct_agent", "button"
        else:
            path, source = "freeform", "chat"
        db.add_conversation_event(
            conversation_id=conversation_id,
            event_type="conversation_path",
            payload={"path": path, "source": source},
            created_at=ts,
        )
        db.add_conversation_event(
            conversation_id=conversation_id,
            event_type="chat_request",
            payload={"mode": mode, "has_form_data": mode == "guided"},
            created_at=ts,
        )
        stats["events"] += 2

        db.add_message(
            conversation_id=conversation_id,
            role="user",
            content=random.choice(SAMPLE_QUESTIONS),
            metadata={},
        )
        db.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content="Here is some information about that.",
            metadata={},
        )

        # Latency + retrieval quality metrics.
        db.add_rag_metric(
            metric_type="response_latency",
            value=round(random.uniform(1.2, 7.5), 2),
            conversation_id=conversation_id,
            created_at=ts,
        )
        db.add_rag_metric(
            metric_type="retrieval_accuracy",
            value=round(random.uniform(0.7, 0.98), 4),
            conversation_id=conversation_id,
            created_at=ts,
        )
        db.add_rag_metric(
            metric_type="confidence_score",
            value=round(random.uniform(0.3, 0.95), 4),
            conversation_id=conversation_id,
            created_at=ts,
        )
        stats["metrics"] += 3

        outcome_roll = random.random()
        if outcome_roll < 0.72:
            db.add_rag_metric(
                metric_type="completion_outcome", value=1.0,
                conversation_id=conversation_id, created_at=ts + timedelta(minutes=2),
            )
            db.add_conversation_event(
                conversation_id=conversation_id, event_type="completion_confirmed",
                payload={"outcome": 1.0}, created_at=ts + timedelta(minutes=2),
            )
            stats["events"] += 1
        elif outcome_roll < 0.82:
            db.add_rag_metric(
                metric_type="completion_outcome", value=0.0,
                conversation_id=conversation_id, created_at=ts + timedelta(minutes=2),
            )
            db.add_conversation_event(
                conversation_id=conversation_id, event_type="completion_confirmed",
                payload={"outcome": 0.0}, created_at=ts + timedelta(minutes=2),
            )
            stats["events"] += 1
        elif outcome_roll < 0.90:
            db.add_rag_metric(
                metric_type="unanswered_questions", value=1.0,
                conversation_id=conversation_id, created_at=ts,
            )
            db.add_conversation_event(
                conversation_id=conversation_id, event_type="unanswered_question",
                payload={"question": random.choice(SAMPLE_QUESTIONS), "reason": "low_confidence"},
                created_at=ts,
            )
            stats["events"] += 1
        else:
            db.add_rag_metric(
                metric_type="service_errors", value=1.0,
                conversation_id=conversation_id, created_at=ts,
            )
            db.add_conversation_event(
                conversation_id=conversation_id, event_type="service_error",
                payload={"reason": "quota_exhausted"}, created_at=ts,
            )
            stats["events"] += 1

        # Escalations: ~18% escalate, most get an agent join.
        if random.random() < 0.18:
            escal_ts = ts + timedelta(minutes=1)
            db.add_conversation_event(
                conversation_id=conversation_id, event_type="escalation_confirmed",
                payload={"source": "button", "reason": "customer_requested_agent"}, created_at=escal_ts,
            )
            stats["events"] += 1
            if random.random() < 0.85:
                db.add_conversation_event(
                    conversation_id=conversation_id, event_type="agent_joined",
                    payload={"agent_id": "agent-1"},
                    created_at=escal_ts + timedelta(seconds=random.randint(30, 300)),
                )
                stats["events"] += 1

        # CSAT: ~35% of resolved conversations leave a rating.
        if outcome_roll < 0.72 and random.random() < 0.35:
            db.add_conversation_event(
                conversation_id=conversation_id, event_type="csat",
                payload={"rating": random.randint(1, 5), "feedback": ""},
                created_at=ts + timedelta(minutes=3),
            )
            stats["events"] += 1

        # Guided conversations produce quotes; some proceed to payment.
        if mode == "guided" and random.random() < 0.5:
            product = random.choice(PRODUCTS)
            quote = db.create_quote(
                user_id=str(user.id),
                product_id=product.lower().replace(" ", "_"),
                premium_amount=round(random.uniform(15000, 150000), 2),
                product_name=product,
                status="pending",
                generated_at=ts,
            )
            stats["quotes"] += 1
            if random.random() < 0.28:
                db.create_payment_transaction(
                    reference=f"PAY-DEMO-{conv_index}",
                    provider="mtn",
                    provider_reference=f"ref-demo-{conv_index}",
                    phone_number=user.phone_number,
                    amount=quote.premium_amount,
                    currency="UGX",
                    status="SUCCESS",
                    created_at=ts + timedelta(minutes=10),
                )
                stats["payments"] += 1

    return stats
