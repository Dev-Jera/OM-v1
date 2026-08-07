"""Local Travel Insurance underwriting, premium, quotation, and PDF logic."""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:  # pragma: no cover - optional dependency
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    REPORTLAB_AVAILABLE = True
except Exception:  # pragma: no cover - environment-dependent
    colors = None  # type: ignore[assignment]
    TA_CENTER = TA_LEFT = TA_RIGHT = 0  # type: ignore[assignment]
    A4 = (595.27, 841.89)  # type: ignore[assignment]
    ParagraphStyle = dict  # type: ignore[assignment]
    getSampleStyleSheet = None  # type: ignore[assignment]
    mm = 1  # type: ignore[assignment]
    HRFlowable = Image = Paragraph = SimpleDocTemplate = Spacer = Table = TableStyle = object  # type: ignore[assignment]
    REPORTLAB_AVAILABLE = False


def _resolve_logo_path() -> Optional[Path]:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "image" / "download.png"
        if candidate.exists():
            return candidate
    return None


def _logo_flowable(width: float = 30 * mm, height: float = 12 * mm) -> Optional[Any]:
    if not REPORTLAB_AVAILABLE:
        return None
    logo_path = _resolve_logo_path()
    if not logo_path:
        return None
    try:
        return Image(str(logo_path), width=width, height=height)
    except Exception:
        return None


USD_TO_UGX = 3_700
EUR_TO_UGX = int(USD_TO_UGX * 1.08)

TRAVEL_PRODUCTS: List[Dict[str, Any]] = [
    {
        "id": "worldwide_essential",
        "label": "Worldwide Essential",
        "currency": "USD",
        "description": "Simple insurance for worry-free international travel",
        "daily_rates": {"0_17": 1.20, "18_69": 2.50, "70_75": 4.50, "76_80": 7.00, "81_85": 10.00},
        "benefits": {
            "Emergency medical expenses": "Up to $40,000",
            "Personal liability": "Up to $100,000",
        },
    },
    {
        "id": "worldwide_elite",
        "label": "Worldwide Elite",
        "currency": "USD",
        "description": "Comprehensive cover for confident world travel",
        "daily_rates": {"0_17": 1.80, "18_69": 3.80, "70_75": 6.50, "76_80": 10.00, "81_85": 15.00},
        "benefits": {
            "Emergency medical expenses": "Up to $100,000",
            "Personal liability": "Up to $500,000",
        },
    },
    {
        "id": "schengen_essential",
        "label": "Schengen Essential",
        "currency": "EUR",
        "description": "Core cover for travel to the Schengen-area",
        "daily_rates": {"0_17": 1.10, "18_69": 2.20, "70_75": 4.00, "76_80": 6.50, "81_85": 9.50},
        "benefits": {
            "Emergency medical expenses": "Up to EUR 30,000",
            "Personal liability": "Up to EUR 50,000",
        },
    },
    {
        "id": "schengen_elite",
        "label": "Schengen Elite",
        "currency": "EUR",
        "description": "Enhanced benefits for travel to the Schengen-area",
        "daily_rates": {"0_17": 1.60, "18_69": 3.20, "70_75": 5.80, "76_80": 9.00, "81_85": 13.00},
        "benefits": {
            "Emergency medical expenses": "Up to EUR 100,000",
            "Personal liability": "Up to EUR 200,000",
        },
    },
    {
        "id": "student_cover",
        "label": "Student Cover",
        "currency": "USD",
        "description": "Flexible travel cover designed for students abroad",
        "daily_rates": {"0_17": 1.00, "18_69": 1.80, "70_75": 4.00, "76_80": 6.50, "81_85": 9.50},
        "benefits": {
            "Emergency medical expenses": "Up to $50,000",
            "Study interruption": "Up to $5,000",
        },
    },
    {
        "id": "africa_asia",
        "label": "Africa & Asia",
        "currency": "USD",
        "description": "Tailored protection for trips across Africa and Asia",
        "daily_rates": {"0_17": 0.90, "18_69": 1.80, "70_75": 3.50, "76_80": 5.50, "81_85": 8.00},
        "benefits": {
            "Emergency medical expenses": "Up to $25,000",
            "Personal liability": "Up to $50,000",
        },
    },
    {
        "id": "inbound_karibu",
        "label": "Inbound Karibu",
        "currency": "USD",
        "description": "Travel insurance for visitors coming to Uganda",
        "daily_rates": {"0_17": 1.00, "18_69": 2.00, "70_75": 3.80, "76_80": 6.00, "81_85": 9.00},
        "benefits": {
            "Emergency medical expenses": "Up to $30,000",
            "Lost baggage": "Up to $500",
        },
    },
]

_PRODUCT_BY_ID = {product["id"]: product for product in TRAVEL_PRODUCTS}
_MAX_TRIP_DAYS = {
    "worldwide_essential": 180,
    "worldwide_elite": 180,
    "schengen_essential": 90,
    "schengen_elite": 90,
    "student_cover": 365,
    "africa_asia": 180,
    "inbound_karibu": 90,
}
_GROUP_DISCOUNTS: List[Tuple[int, float]] = [(10, 0.10), (5, 0.05), (1, 0.00)]
_TRAINING_LEVY_RATE = 0.010
_STAMP_DUTY = 15_000


def _fmt_ugx(amount: float) -> str:
    return f"UGX {int(round(amount)):,}"


def _fmt_local(amount: float, currency: str) -> str:
    prefix = "EUR" if currency == "EUR" else "USD"
    return f"{prefix} {amount:,.2f}"


def _pull(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return default


def _text(value: Any, default: str = "-") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "undefined", "nan"}:
        return default
    return text


def _flatten(flow_data: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for key in (
        "about_you",
        "travel_party_and_trip",
        "selected_product",
        "emergency_contact",
        "bank_details",
    ):
        source = flow_data.get(key)
        if isinstance(source, dict):
            merged.update(source)
    merged.update(flow_data)
    return merged


def _safe_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except (ValueError, TypeError):
        return None


def _trip_days(departure: Any, return_date: Any) -> int:
    start_date = _safe_date(departure)
    end_date = _safe_date(return_date)
    if not start_date or not end_date:
        return 1
    return max(1, (end_date - start_date).days + 1)


def _age_from_dob(dob: Any) -> Optional[int]:
    dob_date = _safe_date(dob)
    if not dob_date:
        return None
    today = date.today()
    return today.year - dob_date.year - ((today.month, today.day) < (dob_date.month, dob_date.day))


def _age_bucket(age: Optional[int]) -> str:
    if age is None:
        return "18_69"
    if age <= 17:
        return "0_17"
    if age <= 69:
        return "18_69"
    if age <= 75:
        return "70_75"
    if age <= 80:
        return "76_80"
    return "81_85"


def _group_discount(count: int) -> Tuple[float, str]:
    for threshold, rate in _GROUP_DISCOUNTS:
        if count >= threshold:
            label = f"Group discount ({count} travellers, {int(rate * 100)}%)" if rate else ""
            return rate, label
    return 0.0, ""


def _get_product(product_data: Any) -> Dict[str, Any]:
    if isinstance(product_data, str):
        return _PRODUCT_BY_ID.get(product_data, TRAVEL_PRODUCTS[0])
    if isinstance(product_data, dict):
        product_id = product_data.get("id", "")
        if product_id in _PRODUCT_BY_ID:
            return _PRODUCT_BY_ID[product_id]
    return TRAVEL_PRODUCTS[0]


def underwrite(data: Dict[str, Any]) -> Dict[str, Any]:
    flat = _flatten(data)
    trip = data.get("travel_party_and_trip") or {}
    product = _get_product(_pull(flat, "selected_product", default={}))
    max_days = _MAX_TRIP_DAYS.get(product.get("id", ""), 180)
    trip_days = _trip_days(trip.get("departure_date"), trip.get("return_date"))

    reasons: List[str] = []
    risk_factors: List[str] = []
    score = 0

    if trip_days > max_days:
        reasons.append(
            f"Trip duration ({trip_days} days) exceeds maximum of {max_days} days for {product.get('label', 'this product')}."
        )
        score += 30

    destination = trip.get("destination_country", "")
    blocked = ["Afghanistan", "Syria", "Yemen", "Libya", "Somalia", "Iraq", "South Sudan"]
    if any(country.lower() in str(destination).lower() for country in blocked):
        reasons.append(f"Destination '{destination}' is a high-risk territory - cover unavailable.")
        score += 60

    decision = "decline" if score >= 50 else "refer" if score >= 20 else "accept"
    return {"decision": decision, "reasons": reasons, "risk_factors": risk_factors, "risk_score": score}


def calculate_premium(data: Dict[str, Any]) -> Dict[str, Any]:
    flat = _flatten(data)
    product = _get_product(_pull(flat, "selected_product", default={}))
    trip = data.get("travel_party_and_trip") or {}
    rates = product.get("daily_rates", {"18_69": 2.50})
    currency = product.get("currency", "USD")
    trip_days = _trip_days(trip.get("departure_date"), trip.get("return_date"))

    member_premiums: Dict[str, float] = {}
    party = trip.get("travel_party", "myself_only")

    if party == "group":
        buckets = {
            "0_17": int(trip.get("num_travellers_0_17", 0) or 0),
            "18_69": int(trip.get("num_travellers_18_69", 0) or 0),
            "70_75": int(trip.get("num_travellers_70_75", 0) or 0),
            "76_80": int(trip.get("num_travellers_76_80", 0) or 0),
            "81_85": int(trip.get("num_travellers_81_85", 0) or 0),
        }
        for bucket, count in buckets.items():
            if not count:
                continue
            rate = rates.get(bucket, rates.get("18_69", 2.50))
            label = f"Travellers aged {bucket.replace('_', '–')} (x{count})"
            member_premiums[label] = rate * trip_days * count
        total_travellers = int(trip.get("total_travellers", 1) or 1)
    else:
        for index, key in enumerate(["traveller_1_date_of_birth", "traveller_2_date_of_birth"], start=1):
            dob = trip.get(key)
            if not dob and index > 1:
                continue
            age = _age_from_dob(dob)
            bucket = _age_bucket(age)
            rate = rates.get(bucket, rates.get("18_69", 2.50))
            label = f"Traveller {index}" + (f" (age {age})" if age is not None else "")
            member_premiums[label] = rate * trip_days
            if party == "myself_only":
                break
        total_travellers = 1 if party == "myself_only" else 2

    gross_local = sum(member_premiums.values())
    discount_rate, discount_label = _group_discount(total_travellers)
    discount_local = gross_local * discount_rate
    net_local = gross_local - discount_local
    fx_rate = EUR_TO_UGX if currency == "EUR" else USD_TO_UGX
    net_ugx = net_local * fx_rate
    training_levy_ugx = net_ugx * _TRAINING_LEVY_RATE
    stamp_duty_ugx = float(_STAMP_DUTY)
    total_ugx = net_ugx + training_levy_ugx + stamp_duty_ugx
    total_local = net_local + (training_levy_ugx + stamp_duty_ugx) / fx_rate

    return {
        "product_id": product.get("id", ""),
        "product_label": product.get("label", ""),
        "currency": currency,
        "days": trip_days,
        "total_travellers": total_travellers,
        "member_premiums": {key: round(value, 2) for key, value in member_premiums.items()},
        "gross_local": round(gross_local, 2),
        "discount_local": round(discount_local, 2),
        "discount_label": discount_label,
        "net_local": round(net_local, 2),
        "training_levy_ugx": round(training_levy_ugx, 2),
        "stamp_duty_ugx": round(stamp_duty_ugx, 2),
        "total_local": round(total_local, 2),
        "total_ugx": round(total_ugx, 2),
        "total_usd": round(total_local, 2) if currency == "USD" else round(total_local * 1.08, 2),
        "monthly": round(total_ugx, 2),
        "annual": round(total_ugx, 2),
        "total": round(total_ugx, 2),
        "breakdown": {
            "member_premiums": {key: round(value, 2) for key, value in member_premiums.items()},
            "gross_local": round(gross_local, 2),
            "discount_local": round(discount_local, 2),
            "net_local": round(net_local, 2),
            "fx_rate": fx_rate,
            "net_ugx": round(net_ugx, 2),
            "training_levy_ugx": round(training_levy_ugx, 2),
            "stamp_duty_ugx": round(stamp_duty_ugx, 2),
        },
        "formatted": {
            "gross_local": _fmt_local(gross_local, currency),
            "discount_local": _fmt_local(discount_local, currency),
            "net_local": _fmt_local(net_local, currency),
            "training_levy_ugx": _fmt_ugx(training_levy_ugx),
            "stamp_duty_ugx": _fmt_ugx(stamp_duty_ugx),
            "total_local": _fmt_local(total_local, currency),
            "total_ugx": _fmt_ugx(total_ugx),
        },
        "underwriting": underwrite(data),
    }


def build_quotation(flow_data: Dict[str, Any], quote_id: Optional[str] = None) -> Dict[str, Any]:
    flat = _flatten(flow_data)
    product = _get_product(_pull(flat, "selected_product", default={}))
    pricing = calculate_premium(flow_data)
    travellers = flow_data.get("travellers") or []
    primary_traveller = travellers[0] if isinstance(travellers, list) and travellers else {}
    name_parts = [
        _text(_pull(primary_traveller, "first_name", default=_pull(flat, "first_name", default="")), default=""),
        _text(_pull(primary_traveller, "middle_name", default=_pull(flat, "middle_name", default="")), default=""),
        _text(_pull(primary_traveller, "surname", default=_pull(flat, "surname", default="")), default=""),
    ]
    full_name = " ".join(filter(None, name_parts)) or "—"
    today = date.today()
    trip = flow_data.get("travel_party_and_trip") or {}
    emergency_contact = flow_data.get("emergency_contact") or {}

    return {
        "quote_number": quote_id or f"OMU-TI-{today.strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}",
        "quote_date": today.isoformat(),
        "valid_until": (today + timedelta(days=30)).isoformat(),
        "insurer": "Old Mutual Life Assurance Company Uganda Limited",
        "product": product.get("label", "Travel Insurance"),
        "description": product.get("description", ""),
        "client": {
            "full_name": full_name,
            "email": _text(_pull(primary_traveller, "email", default=_pull(flat, "email", default="—")), default="—"),
            "mobile": _text(_pull(primary_traveller, "phone_number", default=_pull(flat, "phone_number", default="—")), default="—"),
            "date_of_birth": _text(_pull(primary_traveller, "date_of_birth", default="—"), default="—"),
            "occupation": _text(_pull(primary_traveller, "occupation", default="—"), default="—"),
            "passport_number": _text(_pull(primary_traveller, "passport_number", default="—"), default="—"),
            "nationality_type": _text(_pull(primary_traveller, "nationality_type", default="—"), default="—").replace("_", " ").title(),
            "postal_address": _text(_pull(primary_traveller, "postal_address", default="—"), default="—"),
            "town_city": _text(_pull(primary_traveller, "town_city", default="—"), default="—"),
        },
        "trip": {
            "travel_party": _text(_pull(trip, "travel_party", default=_pull(flat, "travel_party", default="—")), default="—"),
            "departure_country": trip.get("departure_country", "—"),
            "destination_country": trip.get("destination_country", "—"),
            "departure_date": trip.get("departure_date", "—"),
            "return_date": trip.get("return_date", "—"),
            "trip_days": pricing["days"],
            "total_travellers": pricing["total_travellers"],
        },
        "emergency_contact": {
            "name": _text(emergency_contact.get("surname"), default="—"),
            "relationship": _text(emergency_contact.get("relationship"), default="—"),
            "phone": _text(emergency_contact.get("phone_number"), default="—"),
            "email": _text(emergency_contact.get("email"), default="—"),
            "address": _text(emergency_contact.get("home_address"), default="—"),
        },
        "benefits": product.get("benefits", {}),
        "pricing": pricing,
        "underwriting": pricing["underwriting"],
        "disclaimer": (
            "This quotation is valid for 30 days from the quote date. Premium rates are indicative and subject to "
            "final underwriting approval. Benefits are subject to policy terms and conditions. Travel to high-risk "
            "territories may not be covered. Old Mutual Uganda is regulated by the Insurance Regulatory Authority of "
            "Uganda (IRA). Cover commences only upon receipt of full premium payment."
        ),
    }


def build_travel_insurance_underwriting(payload: Dict[str, Any], quote_id: str) -> Dict[str, Any]:
    flat = _flatten(payload)
    pricing = calculate_premium(payload)
    underwriting = pricing["underwriting"]
    decision = {
        "accept": "APPROVED",
        "refer": "REFERRED",
        "decline": "DECLINED",
    }.get(str(underwriting.get("decision", "accept")).lower(), "APPROVED")

    requirements = [{"type": "underwriting", "message": reason} for reason in underwriting.get("reasons", [])]
    requirements.extend({"type": "underwriting", "message": factor} for factor in underwriting.get("risk_factors", []))

    return {
        "quote_id": quote_id,
        "premium": pricing["total_ugx"],
        "currency": "UGX",
        "decision_status": decision,
        "requirements": requirements,
        "product_mock": "travel_insurance",
        "product_id": _get_product(_pull(flat, "selected_product", default={})).get("id", ""),
        "breakdown": pricing["breakdown"],
    }


def build_travel_insurance_premium(payload: Dict[str, Any]) -> Dict[str, Any]:
    return calculate_premium(payload)


def build_travel_insurance_quote(payload: Dict[str, Any], underwriting: Dict[str, Any]) -> Dict[str, Any]:
    quotation = build_quotation(payload, underwriting.get("quote_id"))
    pricing = quotation["pricing"]
    return {
        "quote_id": underwriting.get("quote_id") or quotation["quote_number"],
        "premium": pricing["total_ugx"],
        "amount": pricing["total_ugx"],
        "payable_amount": pricing["total_ugx"],
        "currency": "UGX",
        "status": "QUOTED",
        "product_mock": "travel_insurance",
        "billing_frequency": "single_trip",
        "breakdown": pricing["breakdown"],
        "quotation": quotation,
    }


def generate_quote_pdf(quotation: Dict[str, Any]) -> bytes:
    if not REPORTLAB_AVAILABLE:  # pragma: no cover - environment-dependent
        client = quotation.get("client", {})
        trip = quotation.get("trip", {})
        emergency = quotation.get("emergency_contact", {})
        underwriting = quotation.get("underwriting", {})
        decision_label = {
            "accept": "ACCEPTED",
            "refer": "REFERRED",
            "decline": "DECLINED",
        }.get(str(underwriting.get("decision", "accept")).lower(), "ACCEPTED")
        content = [
            "Travel Insurance Quotation",
            f"Quote Number: {quotation.get('quote_number', '-')}" ,
            f"Client: {client.get('full_name', '-')}" ,
            f"Email: {client.get('email', '-')}" ,
            f"Mobile: {client.get('mobile', '-')}" ,
            f"Passport: {client.get('passport_number', '-')}" ,
            f"Product: {quotation.get('product', '-')}" ,
            f"Destination: {trip.get('destination_country', '-')}" ,
            f"Trip Days: {trip.get('trip_days', '-')}" ,
            f"Emergency Contact: {emergency.get('name', '-')} / {emergency.get('phone', '-')}" ,
            f"Underwriting Decision: {decision_label}",
            f"Total Premium: {quotation.get('pricing', {}).get('formatted', {}).get('total_ugx', '-')}" ,
        ]
        for note in underwriting.get("reasons", []):
            content.append(f"Underwriting Note: {note}")
        for factor in underwriting.get("risk_factors", []):
            content.append(f"Risk Factor: {factor}")
        return ("%PDF-1.4\n" + "\n".join(content) + "\n%%EOF").encode("utf-8")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    base = getSampleStyleSheet()
    green = colors.HexColor("#006835")
    light_green = colors.HexColor("#e8f5e9")
    light = colors.HexColor("#f7f7f7")
    line = colors.HexColor("#cccccc")
    dark = colors.HexColor("#1a1a1a")
    mid = colors.HexColor("#555555")
    page_width = A4[0] - 32 * mm

    header_title = ParagraphStyle(
        "ti_header_title", parent=base["Normal"], fontSize=20, leading=24, textColor=colors.white, fontName="Helvetica-Bold", alignment=TA_LEFT
    )
    header_sub = ParagraphStyle(
        "ti_header_sub",
        parent=base["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#ccffcc"),
        fontName="Helvetica",
        alignment=TA_LEFT,
    )
    header_right_label = ParagraphStyle(
        "ti_header_rl",
        parent=base["Normal"],
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#aaddaa"),
        fontName="Helvetica",
        alignment=TA_RIGHT,
    )
    header_right_value = ParagraphStyle(
        "ti_header_rv",
        parent=base["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.white,
        fontName="Helvetica-Bold",
        alignment=TA_RIGHT,
    )
    section_style = ParagraphStyle(
        "ti_section", parent=base["Normal"], fontSize=9, leading=12, textColor=colors.white, fontName="Helvetica-Bold"
    )
    label_style = ParagraphStyle("ti_label", parent=base["Normal"], fontSize=8, leading=11, textColor=mid, fontName="Helvetica")
    value_style = ParagraphStyle("ti_value", parent=base["Normal"], fontSize=8.5, leading=11, textColor=dark, fontName="Helvetica-Bold")
    amount_style = ParagraphStyle("ti_amount", parent=base["Normal"], fontSize=8.5, leading=11, textColor=dark, fontName="Helvetica", alignment=TA_RIGHT)
    amount_total_style = ParagraphStyle(
        "ti_amount_total",
        parent=base["Normal"],
        fontSize=11,
        leading=14,
        textColor=green,
        fontName="Helvetica-Bold",
        alignment=TA_RIGHT,
    )
    disclaimer_style = ParagraphStyle("ti_disclaimer", parent=base["Normal"], fontSize=6.5, leading=9, textColor=mid, fontName="Helvetica-Oblique")
    footer_style = ParagraphStyle("ti_footer", parent=base["Normal"], fontSize=7, leading=9, textColor=mid, fontName="Helvetica", alignment=TA_CENTER)
    risk_style = ParagraphStyle("ti_risk", parent=base["Normal"], fontSize=8.5, leading=11, textColor=colors.HexColor("#2e7d32"), fontName="Helvetica-Bold")

    def spacer(height: float = 3) -> Spacer:
        return Spacer(1, height * mm)

    def section_bar(title: str) -> Table:
        table = Table([[Paragraph(title, section_style)]], colWidths=[page_width])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), green),
            ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ]))
        return table

    def kv_4col(rows: List[Tuple[str, str]]) -> Table:
        width = page_width / 4
        data_rows = []
        for idx in range(0, len(rows), 2):
            left = rows[idx]
            right = rows[idx + 1] if idx + 1 < len(rows) else ("", "")
            data_rows.append([
                Paragraph(left[0], label_style),
                Paragraph(left[1], value_style),
                Paragraph(right[0], label_style),
                Paragraph(right[1], value_style),
            ])
        table = Table(data_rows, colWidths=[width, width, width, width])
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, line),
            ("LINEAFTER", (1, 0), (1, -1), 0.3, line),
        ]
        for idx in range(0, len(data_rows), 2):
            style.append(("BACKGROUND", (0, idx), (-1, idx), light))
        table.setStyle(TableStyle(style))
        return table

    def benefits_table(benefits: Dict[str, str]) -> Table:
        rows = [[Paragraph(key, label_style), Paragraph(value, value_style)] for key, value in benefits.items()]
        table = Table(rows, colWidths=[page_width * 0.55, page_width * 0.45])
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, line),
        ]
        for idx in range(0, len(rows), 2):
            style.append(("BACKGROUND", (0, idx), (-1, idx), light))
        table.setStyle(TableStyle(style))
        return table

    def pricing_table(pricing: Dict[str, Any]) -> Table:
        rows: List[List[Any]] = []
        currency = pricing.get("currency", "USD")

        def add_row(label: str, amount: str, highlight: bool = False) -> None:
            rows.append([
                Paragraph(label, value_style if highlight else label_style),
                Paragraph(amount, amount_total_style if highlight else amount_style),
            ])

        add_row("Trip Duration", f"{pricing.get('days', 0)} days")
        for label, amount in pricing.get("member_premiums", {}).items():
            add_row(f"    {label}", _fmt_local(amount, currency))
        add_row(f"Gross Premium ({currency})", _fmt_local(pricing.get("gross_local", 0), currency))
        if pricing.get("discount_local"):
            add_row(f"- {pricing.get('discount_label', 'Group discount')}", _fmt_local(pricing.get("discount_local", 0), currency))
        add_row(f"Net Premium ({currency})", _fmt_local(pricing.get("net_local", 0), currency))
        add_row("Net Premium (UGX)", _fmt_ugx(pricing.get("breakdown", {}).get("net_ugx", 0)))
        add_row("+ Training Levy (1%)", _fmt_ugx(pricing.get("training_levy_ugx", 0)))
        add_row("+ Stamp Duty", _fmt_ugx(pricing.get("stamp_duty_ugx", 0)))
        rows.append([HRFlowable(width="100%", thickness=1, color=green), HRFlowable(width="100%", thickness=1, color=green)])
        add_row("TOTAL PREMIUM (UGX)", _fmt_ugx(pricing.get("total_ugx", 0)), True)
        add_row(f"Total Premium ({currency})", _fmt_local(pricing.get("total_local", 0), currency))

        table = Table(rows, colWidths=[page_width * 0.65, page_width * 0.35])
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ("LINEBELOW", (0, 0), (-1, -3), 0.3, line),
            ("BACKGROUND", (0, len(rows) - 2), (-1, len(rows) - 2), light_green),
        ]))
        return table

    logo = _logo_flowable()
    left_header: List[Any] = []
    if logo is not None:
        left_header.extend([logo, spacer(1)])
    left_header.extend(
        [
            Paragraph(quotation.get("insurer", "Old Mutual Life Assurance Company Uganda Limited"), header_sub),
            spacer(2),
            Paragraph(quotation.get("product", "Travel Insurance"), header_title),
            spacer(1),
            Paragraph(quotation.get("description", "Travel Insurance Quotation"), header_sub),
        ]
    )

    header = Table([[
        left_header,
        [
            Paragraph("Quote Number", header_right_label),
            Paragraph(quotation.get("quote_number", "-"), header_right_value),
            spacer(1.5),
            Paragraph("Quote Date", header_right_label),
            Paragraph(quotation.get("quote_date", "-"), header_right_value),
            spacer(1.5),
            Paragraph("Valid Until", header_right_label),
            Paragraph(quotation.get("valid_until", "-"), header_right_value),
        ],
    ]], colWidths=[page_width * 0.62, page_width * 0.38])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), green),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 7 * mm),
        ("RIGHTPADDING", (1, 0), (1, -1), 6 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 6 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6 * mm),
    ]))

    client = quotation.get("client", {})
    trip = quotation.get("trip", {})
    emergency_contact = quotation.get("emergency_contact", {})
    pricing = quotation.get("pricing", {})
    underwriting = quotation.get("underwriting", {})
    decision_label = {
        "accept": "ACCEPTED",
        "refer": "REFERRED",
        "decline": "DECLINED",
    }.get(str(underwriting.get("decision", "accept")).lower(), "ACCEPTED")
    underwriting_notes = [str(item) for item in underwriting.get("reasons", []) if str(item).strip()]
    risk_factors = [str(item) for item in underwriting.get("risk_factors", []) if str(item).strip()]

    story = [
        header,
        spacer(4),
        Paragraph(f"Underwriting Decision: {decision_label}", risk_style),
        spacer(3),
        section_bar("POLICYHOLDER DETAILS"),
        kv_4col([
            ("Full Name", str(client.get("full_name", "-"))),
            ("Date of Birth", str(client.get("date_of_birth", "-"))),
            ("Email", str(client.get("email", "-"))),
            ("Mobile", str(client.get("mobile", "-"))),
            ("Occupation", str(client.get("occupation", "-"))),
            ("Passport No.", str(client.get("passport_number", "-"))),
            ("Nationality", str(client.get("nationality_type", "-"))),
            ("Town/City", str(client.get("town_city", "-"))),
            ("Address", str(client.get("postal_address", "-"))),
            ("", ""),
        ]),
        spacer(3),
        section_bar("TRIP DETAILS"),
        kv_4col([
            ("Travel Party", str(trip.get("travel_party", "-"))),
            ("Total Travellers", str(trip.get("total_travellers", 1))),
            ("Departure Country", str(trip.get("departure_country", "-"))),
            ("Destination Country", str(trip.get("destination_country", "-"))),
            ("Departure Date", str(trip.get("departure_date", "-"))),
            ("Return Date", str(trip.get("return_date", "-"))),
            ("Trip Duration", f"{trip.get('trip_days', 0)} days"),
            ("", ""),
        ]),
        spacer(3),
        section_bar("POLICY BENEFITS"),
        benefits_table(quotation.get("benefits", {})),
        spacer(3),
        section_bar("PREMIUM BREAKDOWN"),
        pricing_table(pricing),
    ]

    if underwriting_notes or risk_factors:
        story.extend([
            spacer(3),
            section_bar("UNDERWRITING NOTES"),
            spacer(2),
        ])
        for note in underwriting_notes:
            story.append(Paragraph(f"• {note}", value_style))
            story.append(spacer(1))
        for factor in risk_factors:
            story.append(Paragraph(f"• Risk factor: {factor}", value_style))
            story.append(spacer(1))

    if emergency_contact.get("name") and emergency_contact.get("name") != "-":
        story.extend([
            spacer(3),
            section_bar("EMERGENCY CONTACT / BENEFICIARY"),
            kv_4col([
                ("Name", str(emergency_contact.get("name", "-"))),
                ("Relationship", str(emergency_contact.get("relationship", "-"))),
                ("Phone", str(emergency_contact.get("phone", "-"))),
                ("Email", str(emergency_contact.get("email", "-"))),
                ("Address", str(emergency_contact.get("address", "-"))),
                ("", ""),
            ]),
        ])

    story.extend([
        spacer(4),
        HRFlowable(width="100%", thickness=1, color=green),
        spacer(1),
        Paragraph(quotation.get("disclaimer", ""), disclaimer_style),
        spacer(2),
        Paragraph(
            "Old Mutual Life Assurance Company Uganda Limited is licensed and regulated by the Insurance Regulatory "
            "Authority of Uganda (IRA). This is a computer-generated document.",
            footer_style,
        ),
    ])
    doc.build(story)
    return buffer.getvalue()


class TravelInsurancePremiumService:
    @staticmethod
    def calculate_sync(product_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return calculate_premium(payload.get("data", payload))

    @staticmethod
    def build_quotation_sync(flow_data: Dict[str, Any], quote_id: Optional[str] = None) -> Dict[str, Any]:
        return build_quotation(flow_data, quote_id)

    @staticmethod
    def generate_pdf_sync(flow_data: Dict[str, Any], quote_id: Optional[str] = None) -> bytes:
        return generate_quote_pdf(build_quotation(flow_data, quote_id))
