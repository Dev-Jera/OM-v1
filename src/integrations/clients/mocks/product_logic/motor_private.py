"""Local Motor Private underwriting, premium, and quotation logic."""

from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _data(payload: Dict[str, Any]) -> Dict[str, Any]:
    base = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(base, dict):
        return {}

    merged = dict(base)
    for section in ("motor_frontend", "about_you", "vehicle_details"):
        section_data = base.get(section)
        if isinstance(section_data, dict):
            merged.update(section_data)

    if merged.get("selected_benefits") in (None, "", []):
        merged["selected_benefits"] = base.get("additional_benefits") or []
    if merged.get("excess_choice") in (None, "", []):
        merged["excess_choice"] = base.get("excess_parameters") or []

    return merged


def _boolish(value: Any) -> bool:
    return str(value).strip().lower() in {"yes", "true", "1"}


def _fmt_ugx(value: float) -> str:
    return f"UGX {int(round(float(value or 0))):,}"


def _pick(data: Dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def _normalized_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def build_motor_private_underwriting(payload: Dict[str, Any], quote_id: str) -> Dict[str, Any]:
    data = _data(payload)
    requirements: List[Dict[str, Any]] = []

    vehicle_value = float(data.get("vehicle_value_ugx") or data.get("carValue") or 0)
    if vehicle_value <= 0:
        requirements.append(
            {
                "type": "validation",
                "field": "vehicle_value_ugx",
                "message": "Vehicle value is required and must be greater than zero.",
            }
        )

    year_of_manufacture = data.get("year_of_manufacture") or data.get("yearOfManufacture")
    vehicle_age = None
    if year_of_manufacture not in (None, ""):
        try:
            vehicle_age = max(0, date.today().year - int(year_of_manufacture))
        except (TypeError, ValueError):
            requirements.append(
                {
                    "type": "validation",
                    "field": "year_of_manufacture",
                    "message": "Year of manufacture must be a valid year.",
                }
            )

    region = str(data.get("car_usage_region") or data.get("regionBounds") or "Within Uganda")
    if vehicle_value > 150_000_000:
        requirements.append(
            {
                "type": "underwriting",
                "field": "vehicle_value_ugx",
                "message": "High-value vehicles require manual underwriting review.",
            }
        )
    if vehicle_age is not None and vehicle_age > 15:
        requirements.append(
            {
                "type": "underwriting",
                "field": "year_of_manufacture",
                "message": "Vehicles older than 15 years require manual underwriting review.",
            }
        )
    if "outside east africa" in region.lower():
        requirements.append(
            {
                "type": "underwriting",
                "field": "car_usage_region",
                "message": "Regional use outside East Africa requires manual underwriting review.",
            }
        )

    if any(req["type"] == "validation" for req in requirements):
        decision_status = "DECLINED"
    elif any(req["type"] == "underwriting" for req in requirements):
        decision_status = "REFERRED"
    else:
        decision_status = "APPROVED"

    premium = build_motor_private_premium(payload) if decision_status != "DECLINED" else {
        "base_premium": 0.0,
        "alarm_discount": 0.0,
        "tracker_discount": 0.0,
        "pvt_fee": 0.0,
        "region_fee": 0.0,
        "with_ea_fee": 0.0,
        "outside_ea_fee": 0.0,
        "alternative_accommodation": 0.0,
        "car_hire": 0.0,
        "excess_discount": 0.0,
        "subtotal": 0.0,
        "training_levy": 0.0,
        "sticker_fee": 6000.0,
        "vat": 0.0,
        "stamp_duty": 35000.0,
        "total": 0.0,
        "premium": 0.0,
        "premiumString": "0",
    }

    return {
        "quote_id": quote_id,
        "premium": premium["total"],
        "currency": "UGX",
        "decision_status": decision_status,
        "requirements": requirements,
        "product_mock": "motor_private",
        "breakdown": {
            "annual_base": premium["base_premium"],
            "risk_loading": premium["region_fee"] + premium["pvt_fee"],
            "levies": premium["training_levy"] + premium["sticker_fee"] + premium["stamp_duty"],
            "taxes": premium["vat"],
            "annual_total": premium["total"],
            "monthly_total": premium["total"],
            **premium,
        },
    }


def build_motor_private_premium(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = _data(payload)
    car_value = float(data.get("vehicle_value_ugx") or data.get("carValue") or 32_000_000)
    region = str(data.get("car_usage_region") or data.get("regionBounds") or "Within Uganda")
    has_alarm = _boolish(data.get("car_alarm_installed") or data.get("alarmDiscountRate") or "no")
    has_tracker = _boolish(data.get("tracking_system_installed") or data.get("trackerDiscountRate") or "no")

    selected_benefits = data.get("selected_benefits") or data.get("additional_benefits") or []
    if isinstance(selected_benefits, str):
        selected_benefits = [item.strip().lower() for item in selected_benefits.split(",") if item.strip()]
    else:
        selected_benefits = [str(item).strip().lower() for item in selected_benefits]

    excess_choice = data.get("excess_choice") or data.get("excessValue") or ""
    if isinstance(excess_choice, list):
        excess_choice = excess_choice[0] if excess_choice else "excess_1"
    excess_choice = str(excess_choice).lower()

    base_premium = round(car_value * 0.04)
    alarm_discount = round(base_premium * -0.05) if has_alarm else 0
    tracker_discount = round(base_premium * -0.15) if has_tracker else 0
    pvt_fee = round(base_premium * 0.0025) if "political_violence" in selected_benefits else 0

    with_ea_fee = round(base_premium * 0.2) if "east africa" in region.lower() and "outside" not in region.lower() else 0
    outside_ea_fee = round(base_premium * 0.3) if "outside east africa" in region.lower() else 0

    alternative_accommodation = round(300_000 * 0.1 * 1.1859) if "alternative_accommodation" in selected_benefits else 0
    car_hire = round(100_000 * 0.1 * 1.1859) if "car_hire" in selected_benefits else 0

    excess_discount = 0
    if "excess_1" in excess_choice or "10%" in excess_choice:
        excess_discount = round(base_premium * -0.10)
    elif "excess_2" in excess_choice or "15%" in excess_choice:
        excess_discount = round(base_premium * -0.15)
    elif "excess_3" in excess_choice or "25%" in excess_choice:
        excess_discount = round(base_premium * -0.25)

    subtotal = max(
        0,
        base_premium
        + alarm_discount
        + tracker_discount
        + pvt_fee
        + with_ea_fee
        + outside_ea_fee
        + alternative_accommodation
        + car_hire
        + excess_discount,
    )
    training_levy = round(subtotal * 0.005)
    sticker_fee = 6000
    vat = round((subtotal + training_levy + sticker_fee) * 0.18)
    stamp_duty = 35000
    total = max(0, stamp_duty + subtotal + training_levy + vat + sticker_fee)

    return {
        "base_premium": float(base_premium),
        "alarm_discount": float(alarm_discount),
        "tracker_discount": float(tracker_discount),
        "pvt_fee": float(pvt_fee),
        "region_fee": float(with_ea_fee + outside_ea_fee),
        "with_ea_fee": float(with_ea_fee),
        "outside_ea_fee": float(outside_ea_fee),
        "alternative_accommodation": float(alternative_accommodation),
        "car_hire": float(car_hire),
        "excess_discount": float(excess_discount),
        "subtotal": float(subtotal),
        "training_levy": float(training_levy),
        "sticker_fee": float(sticker_fee),
        "sticker_fees": float(sticker_fee),
        "vat": float(vat),
        "stamp_duty": float(stamp_duty),
        "total": float(total),
        "premium": float(total),
        "premiumString": str(total),
    }


def build_motor_private_quote(payload: Dict[str, Any], underwriting: Dict[str, Any]) -> Dict[str, Any]:
    premium = build_motor_private_premium(payload)
    return {
        "quote_id": underwriting["quote_id"],
        "premium": premium["total"],
        "amount": premium["total"],
        "currency": "UGX",
        "status": "QUOTED",
        "product_mock": "motor_private",
        "billing_frequency": "annual",
        "breakdown": premium,
    }


def build_motor_private_quotation(flow_data: Dict[str, Any], quote_id: Optional[str] = None) -> Dict[str, Any]:
    data = _data(flow_data)
    # Premium must be cached from flow step 4; fail loudly if missing
    pricing = flow_data.get("_cached_motor_private_premium")
    if not isinstance(pricing, dict):
        raise ValueError("Premium cache missing; quotation builder requires completed flow with step 4 calculation")
    preview_quotation = data.get("preview_quotation") if isinstance(data.get("preview_quotation"), dict) else {}
    preview_underwriting = preview_quotation.get("underwriting") if isinstance(preview_quotation.get("underwriting"), dict) else {}
    underwriting = {
        "decision": str(preview_underwriting.get("decision", "accept")),
        "risk_factors": list(preview_underwriting.get("risk_factors", [])),
        "reasons": list(preview_underwriting.get("reasons", [])),
    }

    first = str(_pick(data, "first_name", "firstName", default="")).strip()
    middle = str(_pick(data, "middle_name", "middleName", default="")).strip()
    surname = str(_pick(data, "surname", "last_name", default="")).strip()
    full_name = " ".join(part for part in [first, middle, surname] if part) or "—"

    today = date.today()
    start_raw = str(_pick(data, "cover_start_date", "policy_start_date", "policyStartDate", default=today.isoformat()))
    try:
        start_date = date.fromisoformat(start_raw[:10])
        end_date = date(start_date.year + 1, start_date.month, start_date.day)
    except Exception:
        start_date = today
        end_date = today + timedelta(days=365)

    quote_number = quote_id or f"OMU-MP-{today.strftime('%Y%m%d')}-{str(today.toordinal())[-4:]}"
    selected_benefits = _normalized_list(_pick(data, "additional_benefits", "selected_benefits", default=[]))
    benefit_labels = {
        "political_violence": "Political Violence & Terrorism",
        "alternative_accommodation": "Alternative Accommodation",
        "car_hire": "Car Hire",
    }
    excess_choice = _pick(data, "excess_choice", "excess_parameters", "excessValue", default="")
    if isinstance(excess_choice, list):
        excess_choice = excess_choice[0] if excess_choice else ""

    return {
        "quote_number": quote_number,
        "quote_date": today.isoformat(),
        "valid_until": (today + timedelta(days=30)).isoformat(),
        "insurer": "Old Mutual Life Assurance Company Uganda Limited",
        "product": "Motor Private Insurance",
        "subtitle": "Motor Vehicle Insurance Quotation",
        "client": {
            "full_name": full_name,
            "email": str(_pick(data, "email", default="—")),
            "mobile": str(_pick(data, "phone_number", "mobile", default="—")),
        },
        "vehicle": {
            "vehicle_make": str(_pick(data, "vehicle_make", "vehicleMake", default="—")),
            "year_of_manufacture": str(_pick(data, "year_of_manufacture", "yearOfManufacture", default="—")),
            "cover_type": str(_pick(data, "cover_type", "coverType", default="Comprehensive")).title(),
            "sum_insured": _fmt_ugx(float(_pick(data, "vehicle_value", "vehicle_value_ugx", "vehicleValueUgx", "carValue", default=0) or 0)),
            "cover_start_date": start_date.isoformat(),
            "cover_end_date": end_date.isoformat(),
            "rare_model": str(_pick(data, "rare_model", "isRareModel", default="No")).title(),
            "valuation_done": str(_pick(data, "valuation_done", "hasUndergoneValuation", default="No")).title(),
            "car_alarm_installed": str(_pick(data, "car_alarm_installed", default="No")).title(),
            "tracking_system_installed": str(_pick(data, "tracking_system_installed", default="No")).title(),
            "usage_region": str(_pick(data, "car_usage_region", "regionBounds", default="Within Uganda")),
        },
        "pricing": pricing,
        "selected_additional_benefits": [benefit_labels.get(item, item.replace("_", " ").title()) for item in selected_benefits],
        "selected_excess": str(excess_choice or "Not selected"),
        "underwriting": underwriting,
        "disclaimer": (
            "This quotation is valid for 30 days from the quote date. Premium rates are indicative and "
            "subject to final underwriting approval. Old Mutual Uganda is regulated by the Insurance "
            "Regulatory Authority of Uganda (IRA). Cover commences only upon receipt of full premium payment."
        ),
    }


_GREEN = colors.HexColor("#006835") if colors else None
_LIGHT_GREEN = colors.HexColor("#e8f5e9") if colors else None
_MID = colors.HexColor("#555555") if colors else None
_DARK = colors.HexColor("#1a1a1a") if colors else None
_LIGHT = colors.HexColor("#f7f7f7") if colors else None
_WHITE = colors.white if colors else None
_LINE = colors.HexColor("#cccccc") if colors else None
_PAGE_W, _PAGE_H = A4
_MARGIN = 16 * mm
_COL_W = _PAGE_W - 2 * _MARGIN


def _pdf_styles() -> Dict[str, ParagraphStyle]:
    if not REPORTLAB_AVAILABLE:  # pragma: no cover - environment-dependent
        return {}
    base = getSampleStyleSheet()
    return {
        "header_title": ParagraphStyle(
            "mp_hdr_title", parent=base["Normal"], fontSize=20, leading=24, textColor=_WHITE, fontName="Helvetica-Bold", alignment=TA_LEFT
        ),
        "header_sub": ParagraphStyle(
            "mp_hdr_sub",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#ccffcc"),
            fontName="Helvetica",
            alignment=TA_LEFT,
        ),
        "header_right_label": ParagraphStyle(
            "mp_hdr_rl",
            parent=base["Normal"],
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#aaddaa"),
            fontName="Helvetica",
            alignment=TA_RIGHT,
        ),
        "header_right_value": ParagraphStyle(
            "mp_hdr_rv",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=_WHITE,
            fontName="Helvetica-Bold",
            alignment=TA_RIGHT,
        ),
        "section_bar": ParagraphStyle(
            "mp_sec_bar", parent=base["Normal"], fontSize=9, leading=12, textColor=_WHITE, fontName="Helvetica-Bold", alignment=TA_LEFT
        ),
        "label": ParagraphStyle("mp_lbl", parent=base["Normal"], fontSize=8, leading=11, textColor=_MID, fontName="Helvetica"),
        "value": ParagraphStyle(
            "mp_val", parent=base["Normal"], fontSize=8.5, leading=11, textColor=_DARK, fontName="Helvetica-Bold"
        ),
        "amount": ParagraphStyle(
            "mp_amt", parent=base["Normal"], fontSize=8.5, leading=11, textColor=_DARK, fontName="Helvetica", alignment=TA_RIGHT
        ),
        "amount_total": ParagraphStyle(
            "mp_amt_tot", parent=base["Normal"], fontSize=11, leading=14, textColor=_GREEN, fontName="Helvetica-Bold", alignment=TA_RIGHT
        ),
        "body": ParagraphStyle("mp_body", parent=base["Normal"], fontSize=8, leading=11, textColor=_DARK, fontName="Helvetica"),
        "risk": ParagraphStyle(
            "mp_risk",
            parent=base["Normal"],
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#2e7d32"),
            fontName="Helvetica-Bold",
        ),
        "disclaimer": ParagraphStyle(
            "mp_disc", parent=base["Normal"], fontSize=6.5, leading=9, textColor=_MID, fontName="Helvetica-Oblique"
        ),
        "footer": ParagraphStyle(
            "mp_footer", parent=base["Normal"], fontSize=7, leading=9, textColor=_MID, fontName="Helvetica", alignment=TA_CENTER
        ),
    }


def _sp(height: float = 3) -> Spacer:
    return Spacer(1, height * mm)


def _section_bar(title: str, styles: Dict[str, ParagraphStyle]) -> Table:
    table = Table([[Paragraph(title, styles["section_bar"])]], colWidths=[_COL_W])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _GREEN),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    return table


def _kv_4col(rows: List[tuple[str, str]], styles: Dict[str, ParagraphStyle]) -> Table:
    width = _COL_W / 4
    table_rows = []
    for index in range(0, len(rows), 2):
        left = rows[index]
        right = rows[index + 1] if index + 1 < len(rows) else ("", "")
        table_rows.append([
            Paragraph(left[0], styles["label"]),
            Paragraph(left[1], styles["value"]),
            Paragraph(right[0], styles["label"]),
            Paragraph(right[1], styles["value"]),
        ])
    table = Table(table_rows, colWidths=[width, width, width, width])
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, _LINE),
        ("LINEAFTER", (1, 0), (1, -1), 0.3, _LINE),
    ]
    for idx in range(0, len(table_rows), 2):
        style.append(("BACKGROUND", (0, idx), (-1, idx), _LIGHT))
    table.setStyle(TableStyle(style))
    return table


def _pricing_table(pricing: Dict[str, Any], styles: Dict[str, ParagraphStyle]) -> Table:
    rows: List[List[Any]] = []

    def add_row(label: str, amount: float, *, total: bool = False, indent: bool = False) -> None:
        prefix = "    " if indent else ""
        label_style = styles["value"] if total else styles["label"]
        amount_style = styles["amount_total"] if total else styles["amount"]
        rows.append([Paragraph(prefix + label, label_style), Paragraph(_fmt_ugx(amount), amount_style)])

    add_row("Base Premium", pricing.get("base_premium", 0))
    if pricing.get("region_fee"):
        add_row("Usage region loading", pricing.get("region_fee", 0), indent=True)
    if pricing.get("pvt_fee"):
        add_row("Political Violence & Terrorism", pricing.get("pvt_fee", 0), indent=True)
    if pricing.get("alternative_accommodation"):
        add_row("Alternative Accommodation", pricing.get("alternative_accommodation", 0), indent=True)
    if pricing.get("car_hire"):
        add_row("Car Hire", pricing.get("car_hire", 0), indent=True)
    if pricing.get("alarm_discount"):
        add_row("Car alarm discount", pricing.get("alarm_discount", 0), indent=True)
    if pricing.get("tracker_discount"):
        add_row("Tracking system discount", pricing.get("tracker_discount", 0), indent=True)
    if pricing.get("excess_discount"):
        add_row("Excess discount", pricing.get("excess_discount", 0), indent=True)
    add_row("Subtotal", pricing.get("subtotal", 0))
    add_row("Training Levy (0.5%)", pricing.get("training_levy", 0))
    add_row("Sticker Fee", pricing.get("sticker_fee", 0))
    add_row("VAT (18%)", pricing.get("vat", 0))
    add_row("Stamp Duty", pricing.get("stamp_duty", 0))
    rows.append([HRFlowable(width="100%", thickness=1, color=_GREEN), HRFlowable(width="100%", thickness=1, color=_GREEN)])
    add_row("TOTAL ANNUAL PREMIUM", pricing.get("total", 0), total=True)

    table = Table(rows, colWidths=[_COL_W * 0.65, _COL_W * 0.35])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("LINEBELOW", (0, 0), (-1, -3), 0.3, _LINE),
        ("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), _LIGHT_GREEN),
    ]))
    return table


def _header_table(quotation: Dict[str, Any], styles: Dict[str, ParagraphStyle]) -> Table:
    logo = _logo_flowable()
    left = []
    if logo is not None:
        left.extend([logo, _sp(1)])
    left.extend(
        [
            Paragraph(quotation.get("insurer", "Old Mutual Life Assurance Company Uganda Limited"), styles["header_sub"]),
            _sp(2),
            Paragraph(quotation.get("product", "Motor Private Insurance"), styles["header_title"]),
            _sp(1),
            Paragraph(quotation.get("subtitle", "Motor Vehicle Insurance Quotation"), styles["header_sub"]),
        ]
    )
    right = [
        Paragraph("Quote Number", styles["header_right_label"]),
        Paragraph(quotation.get("quote_number", "—"), styles["header_right_value"]),
        _sp(1.5),
        Paragraph("Quote Date", styles["header_right_label"]),
        Paragraph(quotation.get("quote_date", "—"), styles["header_right_value"]),
        _sp(1.5),
        Paragraph("Valid Until", styles["header_right_label"]),
        Paragraph(quotation.get("valid_until", "—"), styles["header_right_value"]),
    ]
    table = Table([[left, right]], colWidths=[_COL_W * 0.62, _COL_W * 0.38])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _GREEN),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 7 * mm),
        ("RIGHTPADDING", (1, 0), (1, -1), 6 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 6 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6 * mm),
    ]))
    return table


def generate_motor_private_quote_pdf(quotation: Dict[str, Any]) -> bytes:
    if not REPORTLAB_AVAILABLE:  # pragma: no cover - environment-dependent
        return str(quotation).encode("utf-8")

    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=_MARGIN, rightMargin=_MARGIN, topMargin=_MARGIN, bottomMargin=_MARGIN)
    styles = _pdf_styles()
    client = quotation.get("client", {})
    vehicle = quotation.get("vehicle", {})
    underwriting = quotation.get("underwriting", {})
    decision_label = {
        "accept": "ACCEPTED",
        "refer": "REFERRED",
        "decline": "DECLINED",
    }.get(str(underwriting.get("decision", "accept")).lower(), "ACCEPTED")
    underwriting_notes = [str(item) for item in underwriting.get("reasons", []) if str(item).strip()]
    risk_factors = [str(item) for item in underwriting.get("risk_factors", []) if str(item).strip()]

    story: List[Any] = [
        _header_table(quotation, styles),
        _sp(4),
        Paragraph(f"Underwriting Decision: {decision_label}", styles["risk"]),
        _sp(3),
        _section_bar("CLIENT DETAILS", styles),
        _kv_4col([
            ("Full Name", str(client.get("full_name", "—"))),
            ("Email Address", str(client.get("email", "—"))),
            ("Mobile Number", str(client.get("mobile", "—"))),
            ("", ""),
        ], styles),
        _sp(3),
        _section_bar("VEHICLE & COVER DETAILS", styles),
        _kv_4col([
            ("Vehicle Make", str(vehicle.get("vehicle_make", "—"))),
            ("Year of Manufacture", str(vehicle.get("year_of_manufacture", "—"))),
            ("Cover Type", str(vehicle.get("cover_type", "—"))),
            ("Sum Insured", str(vehicle.get("sum_insured", "—"))),
            ("Cover Start Date", str(vehicle.get("cover_start_date", "—"))),
            ("Cover End Date", str(vehicle.get("cover_end_date", "—"))),
            ("Rare Model", str(vehicle.get("rare_model", "—"))),
            ("Valuation Done", str(vehicle.get("valuation_done", "—"))),
            ("Car Alarm Installed", str(vehicle.get("car_alarm_installed", "—"))),
            ("Tracking System", str(vehicle.get("tracking_system_installed", "—"))),
            ("Usage Region", str(vehicle.get("usage_region", "—"))),
            ("Selected Excess", str(quotation.get("selected_excess", "—"))),
        ], styles),
        _sp(3),
        _section_bar("PREMIUM BREAKDOWN", styles),
        _pricing_table(quotation.get("pricing", {}), styles),
        _sp(3),
    ]

    if underwriting_notes or risk_factors:
        story.extend([
            _section_bar("UNDERWRITING NOTES", styles),
            _sp(2),
        ])
        for note in underwriting_notes:
            story.append(Paragraph(f"• {note}", styles["body"]))
            story.append(_sp(1))
        for factor in risk_factors:
            story.append(Paragraph(f"• Risk factor: {factor}", styles["body"]))
            story.append(_sp(1))
        story.append(_sp(2))

    benefits = quotation.get("selected_additional_benefits", [])
    if benefits:
        story.extend([
            _section_bar("SELECTED ADDITIONAL BENEFITS", styles),
            _sp(2),
        ])
        for item in benefits:
            story.append(Paragraph(f"• {item}", styles["body"]))
            story.append(_sp(1))

    story.extend([
        _sp(2),
        HRFlowable(width="100%", thickness=1, color=_GREEN),
        _sp(1),
        Paragraph(quotation.get("disclaimer", ""), styles["disclaimer"]),
        _sp(2),
        Paragraph(
            "Old Mutual Life Assurance Company Uganda Limited is licensed and regulated by the Insurance Regulatory "
            "Authority of Uganda (IRA). This is a computer-generated document.",
            styles["footer"],
        ),
    ])
    document.build(story)
    return buffer.getvalue()
