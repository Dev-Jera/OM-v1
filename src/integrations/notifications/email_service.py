from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


def _first_non_empty(data: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


class EmailService:
    def __init__(self) -> None:
        self.smtp_host = os.getenv("SMTP_HOST", "").strip()
        self.smtp_port = int(os.getenv("SMTP_PORT", "587").strip() or "587")
        self.smtp_user = os.getenv("SMTP_USER", "").strip()
        self.smtp_pass = os.getenv("SMTP_PASS", "").strip()
        self.smtp_from_email = os.getenv("SMTP_FROM_EMAIL", "").strip()
        self.smtp_from_name = os.getenv("SMTP_FROM_NAME", "Old Mutual").strip() or "Old Mutual"
        self.smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}

    def _is_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from_email)

    def _from_header(self) -> str:
        if self.smtp_from_name:
            return f"{self.smtp_from_name} <{self.smtp_from_email}>"
        return self.smtp_from_email

    def _send_message(self, message: EmailMessage) -> Dict[str, Any]:
        if not self._is_enabled():
            return {
                "sent": False,
                "provider": "smtp",
                "reason": "smtp_not_configured",
            }

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as smtp:
                if self.smtp_use_tls:
                    smtp.starttls()
                if self.smtp_user and self.smtp_pass:
                    smtp.login(self.smtp_user, self.smtp_pass)
                smtp.send_message(message)
            return {
                "sent": True,
                "provider": "smtp",
                "to": message.get("To"),
                "subject": message.get("Subject"),
            }
        except Exception as exc:
            logger.warning("Email send failed: %s", exc)
            return {
                "sent": False,
                "provider": "smtp",
                "reason": str(exc),
            }

    def send_email(
        self,
        *,
        to_email: str,
        subject: str,
        body_text: str,
        attachment_bytes: Optional[bytes] = None,
        attachment_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        to_value = str(to_email or "").strip()
        if not to_value:
            return {"sent": False, "provider": "smtp", "reason": "missing_recipient"}

        msg = EmailMessage()
        msg["From"] = self._from_header()
        msg["To"] = to_value
        msg["Subject"] = subject
        msg.set_content(body_text)

        if attachment_bytes:
            filename = attachment_filename or "document.pdf"
            msg.add_attachment(
                attachment_bytes,
                maintype="application",
                subtype="pdf",
                filename=filename,
            )

        return self._send_message(msg)

    def send_final_quote_email(
        self,
        *,
        to_email: str,
        quote_payload: Dict[str, Any],
        attachment_bytes: Optional[bytes] = None,
        attachment_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        metadata = dict(quote_payload.get("metadata") or {})
        original_input = dict(metadata.get("original_input_payload") or {})
        first_name = _first_non_empty(original_input, "first_name", "firstName") or "Customer"

        quote_id = str(quote_payload.get("quote_id") or "")
        product_name = str(quote_payload.get("product_name") or quote_payload.get("product_id") or "Insurance")
        premium = quote_payload.get("premium")
        currency = str(quote_payload.get("currency") or "UGX")
        policy_start = str(quote_payload.get("policy_start_date") or "TBD")
        valid_until = str(quote_payload.get("valid_until") or "")
        download_url = str(quote_payload.get("download_url") or "")

        premium_display = f"{premium:,.2f}" if isinstance(premium, (int, float)) else str(premium or "-")
        subject = f"Your Final Quote {quote_id}"
        body = (
            f"Hello {first_name},\n\n"
            f"Your final quote for {product_name} is ready.\n"
            f"Quote ID: {quote_id}\n"
            f"Premium: {currency} {premium_display}\n"
            f"Policy Start Date: {policy_start}\n"
            f"Valid Until: {valid_until}\n"
            f"Download Link: {download_url}\n\n"
            "Thank you for choosing Old Mutual."
        )

        return self.send_email(
            to_email=to_email,
            subject=subject,
            body_text=body,
            attachment_bytes=attachment_bytes,
            attachment_filename=attachment_filename or f"quote_{quote_id}.pdf",
        )

    def send_policy_confirmation_email(
        self,
        *,
        to_email: str,
        policy_payload: Dict[str, Any],
        payment_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payment = dict(payment_payload or {})

        customer_name = _first_non_empty(policy_payload, "customer_name") or "Customer"
        policy_id = str(policy_payload.get("policy_id") or "")
        quote_id = str(policy_payload.get("quote_id") or "")
        status = str(policy_payload.get("status") or "")
        start_date = str(policy_payload.get("start_date") or "")
        end_date = str(policy_payload.get("end_date") or "")
        premium = policy_payload.get("premium_amount") or policy_payload.get("premium") or payment.get("amount")
        currency = str(policy_payload.get("currency") or payment.get("currency") or "UGX")
        payment_reference = str(payment.get("reference") or quote_id)
        payment_status = str(payment.get("status") or "")

        premium_display = f"{premium:,.2f}" if isinstance(premium, (int, float)) else str(premium or "-")
        subject = f"Policy Confirmation {policy_id or quote_id}"
        body = (
            f"Hello {customer_name},\n\n"
            "Your policy confirmation is ready.\n"
            f"Policy ID: {policy_id}\n"
            f"Quote ID: {quote_id}\n"
            f"Policy Status: {status}\n"
            f"Policy Start Date: {start_date}\n"
            f"Policy End Date: {end_date}\n"
            f"Payment Reference: {payment_reference}\n"
            f"Payment Status: {payment_status}\n"
            f"Amount: {currency} {premium_display}\n\n"
            "Thank you for choosing Old Mutual."
        )

        return self.send_email(
            to_email=to_email,
            subject=subject,
            body_text=body,
        )


email_service = EmailService()
