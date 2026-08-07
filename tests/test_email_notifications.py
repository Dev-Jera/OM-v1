from __future__ import annotations

import importlib
from typing import Any, Dict, List

from src.integrations.notifications.email_service import EmailService
from src.integrations.payments.payment_service import PaymentService


email_service_module = importlib.import_module("src.integrations.notifications.email_service")


def test_email_service_returns_noop_when_smtp_not_configured(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM_EMAIL", raising=False)

    service = EmailService()
    result = service.send_email(
        to_email="customer@example.com",
        subject="Subject",
        body_text="Body",
    )

    assert result["sent"] is False
    assert result["reason"] == "smtp_not_configured"


def test_email_service_sends_attachment_when_configured(monkeypatch):
    captured: List[Dict[str, Any]] = []

    class _FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int = 20) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            return None

        def login(self, _user: str, _password: str):
            return None

        def send_message(self, message):
            captured.append(
                {
                    "to": message.get("To"),
                    "subject": message.get("Subject"),
                    "attachments": len(list(message.iter_attachments())),
                }
            )

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("SMTP_FROM_NAME", "Old Mutual")
    monkeypatch.setenv("SMTP_USER", "test-user")
    monkeypatch.setenv("SMTP_PASS", "test-pass")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    monkeypatch.setattr(email_service_module.smtplib, "SMTP", _FakeSMTP)

    service = EmailService()
    result = service.send_final_quote_email(
        to_email="customer@example.com",
        quote_payload={
            "quote_id": "FQ-123",
            "product_name": "Personal Accident",
            "premium": 25000,
            "currency": "UGX",
            "policy_start_date": "2026-04-10",
            "valid_until": "2026-05-10T00:00:00",
            "download_url": "/api/v1/products/quotes/FQ-123/download",
            "metadata": {"original_input_payload": {"first_name": "Monica"}},
        },
        attachment_bytes=b"%PDF-1.4 test",
        attachment_filename="quote_FQ-123.pdf",
    )

    assert result["sent"] is True
    assert captured
    assert captured[0]["to"] == "customer@example.com"
    assert captured[0]["attachments"] == 1


def test_webhook_success_sends_policy_confirmation_once(monkeypatch, db):
    reference = "quote-policy-1"
    db.create_payment_transaction(
        reference=reference,
        provider="mtn",
        provider_reference="MTN-INIT-1",
        phone_number="256771234567",
        amount=50000,
        currency="UGX",
        status="PENDING",
        metadata={
            "customer_email": "customer@example.com",
            "customer_name": "Monica",
            "policy": {
                "policy_id": "POL-1",
                "quote_id": reference,
                "status": "ISSUED",
                "start_date": "2026-04-01",
                "end_date": "2027-04-01",
                "currency": "UGX",
                "premium_amount": 50000,
            },
        },
    )

    calls: List[Dict[str, Any]] = []

    def _fake_send(*, to_email: str, policy_payload: Dict[str, Any], payment_payload: Dict[str, Any]):
        calls.append(
            {
                "to_email": to_email,
                "policy_id": policy_payload.get("policy_id"),
                "payment_status": payment_payload.get("status"),
            }
        )
        return {"sent": True, "provider": "smtp"}

    monkeypatch.setattr(
        "src.integrations.payments.payment_service.email_service.send_policy_confirmation_email",
        _fake_send,
    )

    service = PaymentService(db=db)
    payload = {
        "reference": reference,
        "provider": "mtn",
        "provider_reference": "MTN-SUCCESS-1",
        "status": "SUCCESS",
    }
    signature = service._signature_for_payload(payload)

    first = service.apply_webhook_callback(payload, signature)
    assert first["updated"] is True
    assert first["policy_confirmation_email"]["sent"] is True
    assert len(calls) == 1

    second = service.apply_webhook_callback(payload, signature)
    assert second["updated"] is False
    assert len(calls) == 1
