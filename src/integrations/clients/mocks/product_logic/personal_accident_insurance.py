"""Single-file Personal Accident local underwriting, premium, quotation, and PDF logic."""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    REPORTLAB_AVAILABLE = True
except ImportError:  # pragma: no cover - environment-dependent
    REPORTLAB_AVAILABLE = False
    colors = None
    TA_CENTER = TA_LEFT = TA_RIGHT = 0
    A4 = (595.27, 841.89)
    ParagraphStyle = dict  # type: ignore[assignment]
    getSampleStyleSheet = None  # type: ignore[assignment]
    mm = 1
    HRFlowable = Image = Paragraph = SimpleDocTemplate = Spacer = Table = TableStyle = object  # type: ignore[assignment]

_BASE_RATE = 0.0015
_ALLOWED_COVER_LIMITS = [5_000_000, 10_000_000, 20_000_000]
_MINIMUM_ANNUAL_PREMIUM = 50_000
_AGE_MODIFIERS: List[Tuple[int, int, float]] = [
    (18, 24, 1.10),
    (25, 45, 1.00),
    (46, 55, 1.10),
    (56, 60, 1.20),
    (61, 65, 1.35),
]
_RISKY_ACTIVITY_LOADING = 0.25
_RISKY_CATEGORIES: Dict[str, str] = {
    "manufacture_wire_works": "Industrial",
    "mining": "Industrial",
    "explosives": "Hazardous",
    "construction_heights": "Hazardous",
    "diving": "Extreme",
    "racing": "Extreme",
    "other_risky": "Other",
}
_DISABILITY_LOADING = 0.15
_BENEFITS_SCHEDULE: Dict[int, Dict[str, Any]] = {
    5_000_000: {
        "Death Benefit": "UGX 5,000,000",
        "Permanent Total Disability": "UGX 5,000,000",
        "Permanent Partial Disability": "Up to UGX 2,500,000",
        "Temporary Total Disability": "UGX 30,000 / week (max 52 weeks)",
        "Medical Expenses": "UGX 500,000",
        "Hospital Cash": "UGX 15,000 / day (max 30 days)",
    },
    10_000_000: {
        "Death Benefit": "UGX 10,000,000",
        "Permanent Total Disability": "UGX 10,000,000",
        "Permanent Partial Disability": "Up to UGX 5,000,000",
        "Temporary Total Disability": "UGX 60,000 / week (max 52 weeks)",
        "Medical Expenses": "UGX 1,000,000",
        "Hospital Cash": "UGX 30,000 / day (max 30 days)",
    },
    20_000_000: {
        "Death Benefit": "UGX 20,000,000",
        "Permanent Total Disability": "UGX 20,000,000",
        "Permanent Partial Disability": "Up to UGX 10,000,000",
        "Temporary Total Disability": "UGX 120,000 / week (max 52 weeks)",
        "Medical Expenses": "UGX 2,000,000",
        "Hospital Cash": "UGX 60,000 / day (max 30 days)",
        "Funeral Expenses": "UGX 1,000,000",
    },
}
_TRAINING_LEVY_RATE = 0.010
_STAMP_DUTY = 15_000


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


def _fmt(amount: float) -> str:
    return f"UGX {int(round(amount)):,}"


def _normalise(value: Any, default: str = "") -> str:
    return str(value or default).strip().lower()


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
    source = flow_data.get("data") if isinstance(flow_data.get("data"), dict) else flow_data
    if not isinstance(source, dict):
        source = {}

    merged: Dict[str, Any] = {}
    for key in (
        "quick_quote",
        "personal_details",
        "next_of_kin",
        "physical_disability",
        "risky_activities",
        "previous_pa_policy",
    ):
        nested = source.get(key) or {}
        if isinstance(nested, dict):
            merged.update(nested)
    merged.update(source)
    return merged


def _age_from_dob(dob_str: Any) -> Optional[int]:
    if not dob_str:
        return None
    try:
        dob = dob_str if isinstance(dob_str, date) else date.fromisoformat(str(dob_str)[:10])
        today = date.today()
        return today.year - dob.year - (1 if (today.month, today.day) < (dob.month, dob.day) else 0)
    except (ValueError, TypeError):
        return None


def _age_modifier(age: Optional[int]) -> Tuple[float, str]:
    if age is None:
        return 1.0, ""
    for min_age, max_age, modifier in _AGE_MODIFIERS:
        if min_age <= age <= max_age:
            if modifier == 1.0:
                return modifier, ""
            if modifier > 1.0:
                return modifier, f"Age loading ({age} yrs, {int((modifier - 1) * 100)}%)"
            return modifier, f"Age discount ({age} yrs, {int((1 - modifier) * 100)}%)"
    return 1.35, f"Age loading ({age} yrs, 35%)"


def underwrite(data: Dict[str, Any]) -> Dict[str, Any]:
    flat = _flatten(data)
    reasons: List[str] = []
    risk_factors: List[str] = []
    score = 0

    age = _age_from_dob(_pull(flat, "dob"))
    if age is not None:
        if age < 18:
            reasons.append("Applicant must be at least 18 years old.")
            score += 50
        elif age > 65:
            reasons.append("Applicant exceeds maximum entry age of 65 years.")
            score += 50
        elif age > 60:
            risk_factors.append(f"Applicant age {age} - senior loading applied.")
            score += 15
        elif age > 55:
            risk_factors.append(f"Applicant age {age} - moderate age loading applied.")
            score += 8

    cover_limit = int(_pull(flat, "cover_limit_ugx", "coverLimitAmountUgx", "sum_assured", default=0) or 0)
    if cover_limit not in _ALLOWED_COVER_LIMITS and cover_limit != 0:
        reasons.append(f"Cover limit UGX {cover_limit:,} is not a permitted tier.")
        score += 20

    disability = _pull(flat, "free_from_disability")
    if str(disability).lower() in {"false", "no", "0"}:
        risk_factors.append("Physical disability declared - refer for specialist review.")
        score += 20

    selected_activities = _pull(flat, "selected", "risky_activities", default=[])
    if isinstance(selected_activities, dict):
        selected_activities = selected_activities.get("selected", [])
    if isinstance(selected_activities, str):
        selected_activities = [item.strip() for item in selected_activities.split(",") if item.strip()]
    if isinstance(selected_activities, list) and selected_activities:
        categories = {_RISKY_CATEGORIES.get(item, "Other") for item in selected_activities}
        if "Hazardous" in categories or "Extreme" in categories:
            risk_factors.append(f"Risky activities declared: {', '.join(selected_activities)} - loading applied.")
            score += 10
        elif "Industrial" in categories:
            risk_factors.append("Industrial activities declared - loading applied.")
            score += 5

    had_previous = _pull(flat, "had_policy")
    if str(had_previous).lower() in {"true", "yes", "1"}:
        risk_factors.append("Previous PA policy declared - noted for underwriting.")

    if score >= 50 or reasons:
        decision = "refer" if score < 70 else "decline"
    else:
        decision = "accept"

    return {
        "decision": decision,
        "reasons": reasons,
        "risk_factors": risk_factors,
        "risk_score": score,
    }


def calculate_premium(data: Dict[str, Any], sum_assured: Optional[int] = None) -> Dict[str, Any]:
    flat = _flatten(data)
    cover_limit = int(
        sum_assured
        or _pull(flat, "cover_limit_ugx", "coverLimitAmountUgx", "sum_assured", default=10_000_000)
        or 10_000_000
    )
    age = _age_from_dob(_pull(flat, "dob"))
    disability_free = _normalise(_pull(flat, "free_from_disability", default="yes"))
    selected_acts = _pull(flat, "selected", "risky_activities", default=[])
    if isinstance(selected_acts, dict):
        selected_acts = selected_acts.get("selected", [])
    if isinstance(selected_acts, str):
        selected_acts = [item.strip() for item in selected_acts.split(",") if item.strip()]
    if not isinstance(selected_acts, list):
        selected_acts = []

    base_premium = max(cover_limit * _BASE_RATE, _MINIMUM_ANNUAL_PREMIUM)

    modifier, age_label = _age_modifier(age)
    age_adjusted = base_premium * modifier
    age_delta = age_adjusted - base_premium

    loadings: Dict[str, float] = {}
    discounts: Dict[str, float] = {}
    if age_delta > 0 and age_label:
        loadings[age_label] = age_delta
    elif age_delta < 0 and age_label:
        discounts[age_label] = abs(age_delta)

    net_after_age = age_adjusted

    if disability_free not in {"yes", "true", "1"}:
        disability_loading = net_after_age * _DISABILITY_LOADING
        loadings["Physical disability loading"] = disability_loading
        net_after_age += disability_loading

    if selected_acts:
        categories = {_RISKY_CATEGORIES.get(item, "Other") for item in selected_acts}
        risky_loading = net_after_age * _RISKY_ACTIVITY_LOADING * len(categories)
        loadings[f"Risky activity loading ({', '.join(sorted(categories))})"] = risky_loading
        net_after_age += risky_loading

    total_loadings = sum(loadings.values())
    total_discounts = sum(discounts.values())
    net_premium = net_after_age
    training_levy = net_premium * _TRAINING_LEVY_RATE
    stamp_duty = float(_STAMP_DUTY)
    annual = net_premium + training_levy + stamp_duty
    monthly = annual / 12
    benefits = _BENEFITS_SCHEDULE.get(cover_limit, _BENEFITS_SCHEDULE[10_000_000])

    return {
        "cover_limit": cover_limit,
        "base_premium": round(base_premium, 2),
        "loadings": {key: round(value, 2) for key, value in loadings.items()},
        "total_loadings": round(total_loadings, 2),
        "discounts": {key: round(value, 2) for key, value in discounts.items()},
        "total_discounts": round(total_discounts, 2),
        "net_premium": round(net_premium, 2),
        "training_levy": round(training_levy, 2),
        "stamp_duty": round(stamp_duty, 2),
        "annual": round(annual, 2),
        "monthly": round(monthly, 2),
        "total": round(annual, 2),
        "benefits": benefits,
        "breakdown": {
            "base_premium": round(base_premium, 2),
            "loadings": {key: round(value, 2) for key, value in loadings.items()},
            "discounts": {key: round(value, 2) for key, value in discounts.items()},
            "training_levy": round(training_levy, 2),
            "stamp_duty": round(stamp_duty, 2),
            "annual_total": round(annual, 2),
            "monthly_total": round(monthly, 2),
        },
        "formatted": {
            "cover_limit": _fmt(cover_limit),
            "base_premium": _fmt(base_premium),
            "total_loadings": _fmt(total_loadings),
            "total_discounts": _fmt(total_discounts),
            "net_premium": _fmt(net_premium),
            "training_levy": _fmt(training_levy),
            "stamp_duty": _fmt(stamp_duty),
            "annual": _fmt(annual),
            "monthly": _fmt(monthly),
        },
        "underwriting": underwrite(data),
    }


def build_quotation(flow_data: Dict[str, Any], quote_id: Optional[str] = None) -> Dict[str, Any]:
    flat = _flatten(flow_data)
    cover_limit = int(_pull(flat, "cover_limit_ugx", "coverLimitAmountUgx", "sum_assured", default=10_000_000) or 10_000_000)
    pricing = calculate_premium(flat, cover_limit)

    first = _text(_pull(flat, "first_name", "firstName", default=""), default="")
    middle = _text(_pull(flat, "middle_name", "middleName", default=""), default="")
    surname = _text(_pull(flat, "surname", "last_name", "lastName", default=""), default="")
    full_name = " ".join(filter(None, [first, middle, surname])) or "-"

    today = date.today()
    start_raw = _pull(flat, "policy_start_date", "policyStartDate", default=str(today + timedelta(days=1)))
    try:
        policy_start = date.fromisoformat(str(start_raw)[:10])
        policy_end = date(policy_start.year + 1, policy_start.month, policy_start.day).isoformat()
    except (ValueError, TypeError):
        policy_end = "-"

    valid_until = (today + timedelta(days=30)).isoformat()
    quotation_id = quote_id or f"OMU-PA-{today.strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"

    nok = flow_data.get("next_of_kin") or {}
    nok_name = " ".join(
        filter(
            None,
            [
                _text(nok.get("nok_first_name"), default=""),
                _text(nok.get("nok_middle_name"), default=""),
                _text(nok.get("nok_last_name"), default=""),
            ],
        )
    ) or "-"

    risky = flow_data.get("risky_activities") or {}
    selected_acts = risky.get("selected") or []
    acts_display = ", ".join(selected_acts) if selected_acts else "None declared"

    return {
        "quote_number": quotation_id,
        "quote_date": today.isoformat(),
        "valid_until": valid_until,
        "insurer": "Old Mutual Life Assurance Company Uganda Limited",
        "product": "Personal Accident Insurance",
        "client": {
            "full_name": full_name,
            "email": _text(_pull(flat, "email", default="-")),
            "mobile": _text(_pull(flat, "mobile", "mobile_number", "phone_number", default="-")),
            "dob": _text(_pull(flat, "dob", default="-")),
            "gender": _text(_pull(flat, "gender", default="-")).title(),
            "occupation": _text(_pull(flat, "occupation", default="-")),
            "nationality": _text(_pull(flat, "nationality", default="-")),
            "national_id": _text(_pull(flat, "national_id_number", "national_id", "nin", default="-")),
            "tin": _text(_pull(flat, "tax_identification_number", "tin", "tin_number", default="-")),
            "country_of_residence": _text(_pull(flat, "country_of_residence", default="-")),
            "physical_address": _text(_pull(flat, "physical_address", "address", default="-")),
        },
        "cover": {
            "cover_limit": pricing["formatted"]["cover_limit"],
            "policy_start_date": str(start_raw),
            "policy_end_date": policy_end,
            "annual_premium": pricing["formatted"]["annual"],
            "monthly_premium": pricing["formatted"]["monthly"],
        },
        "next_of_kin": {
            "name": nok_name,
            "relationship": _text(nok.get("nok_relationship"), default="-"),
            "phone": _text(nok.get("nok_phone_number"), default="-"),
            "address": _text(nok.get("nok_address"), default="-"),
        },
        "underwriting_info": {
            "previous_pa_policy": _text(_pull(flat, "had_policy", default="No")).title(),
            "free_from_disability": _text(_pull(flat, "free_from_disability", default="Yes")).title(),
            "risky_activities": acts_display,
        },
        "pricing": pricing,
        "benefits": pricing["benefits"],
        "underwriting": pricing["underwriting"],
        "disclaimer": (
            "This quotation is valid for 30 days from the quote date. "
            "Premium rates are indicative and subject to final underwriting approval. "
            "Benefits are subject to policy terms and conditions. "
            "Old Mutual Uganda is regulated by the Insurance Regulatory Authority of Uganda (IRA). "
            "Cover commences only upon receipt of full premium payment."
        ),
    }


def build_personal_accident_underwriting(payload: Dict[str, Any], quote_id: str) -> Dict[str, Any]:
    flat = _flatten(payload)
    pricing = calculate_premium(flat)
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
        "premium": pricing["total"],
        "currency": "UGX",
        "decision_status": decision,
        "requirements": requirements,
        "product_mock": "personal_accident",
        "sum_assured": pricing["cover_limit"],
        "breakdown": pricing["breakdown"],
    }


def build_personal_accident_premium(payload: Dict[str, Any]) -> Dict[str, Any]:
    return calculate_premium(payload)


def build_personal_accident_quote(payload: Dict[str, Any], underwriting: Dict[str, Any]) -> Dict[str, Any]:
    quotation = build_quotation(payload, underwriting.get("quote_id"))
    pricing = quotation["pricing"]
    return {
        "quote_id": underwriting.get("quote_id") or quotation["quote_number"],
        "premium": pricing["total"],
        "amount": pricing["total"],
        "payable_amount": pricing["total"],
        "currency": "UGX",
        "status": "QUOTED",
        "product_mock": "personal_accident",
        "billing_frequency": "annual",
        "breakdown": pricing["breakdown"],
        "quotation": quotation,
    }


if REPORTLAB_AVAILABLE:
    _GREEN = colors.HexColor("#006835")
    _LIGHT_GREEN = colors.HexColor("#e8f5e9")
    _DARK = colors.HexColor("#1a1a1a")
    _MID = colors.HexColor("#555555")
    _LIGHT = colors.HexColor("#f7f7f7")
    _WHITE = colors.white
    _LINE = colors.HexColor("#cccccc")
else:  # pragma: no cover - environment-dependent
    _GREEN = _LIGHT_GREEN = _DARK = _MID = _LIGHT = _WHITE = _LINE = None
_PAGE_W, _PAGE_H = A4
_MARGIN = 16 * mm
_COL_W = _PAGE_W - 2 * _MARGIN


def _pdf_styles() -> Dict[str, ParagraphStyle]:
    if not REPORTLAB_AVAILABLE:  # pragma: no cover - environment-dependent
        return {}
    base = getSampleStyleSheet()
    return {
        "header_title": ParagraphStyle(
            "hdr_title",
            parent=base["Normal"],
            fontSize=20,
            leading=24,
            textColor=_WHITE,
            fontName="Helvetica-Bold",
            alignment=TA_LEFT,
        ),
        "header_sub": ParagraphStyle(
            "hdr_sub",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#ccffcc"),
            fontName="Helvetica",
            alignment=TA_LEFT,
        ),
        "header_right_label": ParagraphStyle(
            "hdr_rl",
            parent=base["Normal"],
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#aaddaa"),
            fontName="Helvetica",
            alignment=TA_RIGHT,
        ),
        "header_right_value": ParagraphStyle(
            "hdr_rv",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=_WHITE,
            fontName="Helvetica-Bold",
            alignment=TA_RIGHT,
        ),
        "section_bar": ParagraphStyle(
            "sec_bar",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=_WHITE,
            fontName="Helvetica-Bold",
            alignment=TA_LEFT,
        ),
        "label": ParagraphStyle("lbl", parent=base["Normal"], fontSize=8, leading=11, textColor=_MID, fontName="Helvetica"),
        "value": ParagraphStyle("val", parent=base["Normal"], fontSize=8.5, leading=11, textColor=_DARK, fontName="Helvetica-Bold"),
        "amount": ParagraphStyle("amt", parent=base["Normal"], fontSize=8.5, leading=11, textColor=_DARK, fontName="Helvetica", alignment=TA_RIGHT),
        "amount_total": ParagraphStyle(
            "amt_tot",
            parent=base["Normal"],
            fontSize=11,
            leading=14,
            textColor=_GREEN,
            fontName="Helvetica-Bold",
            alignment=TA_RIGHT,
        ),
        "benefit_label": ParagraphStyle("ben_lbl", parent=base["Normal"], fontSize=8, leading=11, textColor=_MID, fontName="Helvetica"),
        "benefit_value": ParagraphStyle("ben_val", parent=base["Normal"], fontSize=8, leading=11, textColor=_DARK, fontName="Helvetica-Bold"),
        "body": ParagraphStyle("body", parent=base["Normal"], fontSize=8, leading=11, textColor=_DARK, fontName="Helvetica"),
        "disclaimer": ParagraphStyle(
            "disc",
            parent=base["Normal"],
            fontSize=6.5,
            leading=9,
            textColor=_MID,
            fontName="Helvetica-Oblique",
        ),
        "footer": ParagraphStyle("ftr", parent=base["Normal"], fontSize=7, leading=9, textColor=_MID, fontName="Helvetica", alignment=TA_CENTER),
        "risk_accept": ParagraphStyle(
            "risk_ok",
            parent=base["Normal"],
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#2e7d32"),
            fontName="Helvetica-Bold",
        ),
        "risk_refer": ParagraphStyle(
            "risk_ref",
            parent=base["Normal"],
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#e65100"),
            fontName="Helvetica-Bold",
        ),
        "risk_decline": ParagraphStyle(
            "risk_dec",
            parent=base["Normal"],
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#b71c1c"),
            fontName="Helvetica-Bold",
        ),
    }


def _sp(height: float = 3) -> Spacer:
    if not REPORTLAB_AVAILABLE:  # pragma: no cover - environment-dependent
        return height  # type: ignore[return-value]
    return Spacer(1, height * mm)


def _hr(color: colors.Color = _LINE, thickness: float = 0.5) -> HRFlowable:
    if not REPORTLAB_AVAILABLE:  # pragma: no cover - environment-dependent
        return thickness  # type: ignore[return-value]
    return HRFlowable(width="100%", thickness=thickness, color=color, spaceAfter=2)


def _section_bar(title: str, styles: Dict[str, ParagraphStyle]) -> Table:
    if not REPORTLAB_AVAILABLE:  # pragma: no cover - environment-dependent
        return title  # type: ignore[return-value]
    table = Table([[Paragraph(title, styles["section_bar"])]], colWidths=[_COL_W])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _GREEN),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
            ]
        )
    )
    return table


def _kv_4col(rows: List[Tuple[str, str]], styles: Dict[str, ParagraphStyle]) -> Table:
    if not REPORTLAB_AVAILABLE:  # pragma: no cover - environment-dependent
        return rows  # type: ignore[return-value]
    width = _COL_W / 4
    data = []
    for index in range(0, len(rows), 2):
        left = rows[index]
        right = rows[index + 1] if index + 1 < len(rows) else ("", "")
        data.append(
            [
                Paragraph(left[0], styles["label"]),
                Paragraph(left[1], styles["value"]),
                Paragraph(right[0], styles["label"]),
                Paragraph(right[1], styles["value"]),
            ]
        )
    table = Table(data, colWidths=[width, width, width, width])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ]
        )
    )
    return table


def _kv_table(rows: List[Tuple[str, str]], styles: Dict[str, ParagraphStyle]) -> Table:
    if not REPORTLAB_AVAILABLE:  # pragma: no cover - environment-dependent
        return rows  # type: ignore[return-value]
    table = Table(
        [[Paragraph(label, styles["label"]), Paragraph(value, styles["value"])] for label, value in rows],
        colWidths=[_COL_W * 0.38, _COL_W * 0.62],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ]
        )
    )
    return table


def _pricing_table(pricing: Dict[str, Any], styles: Dict[str, ParagraphStyle]) -> Table:
    if not REPORTLAB_AVAILABLE:  # pragma: no cover - environment-dependent
        return pricing  # type: ignore[return-value]
    rows = [[Paragraph("Base Annual Premium", styles["label"]), Paragraph(_fmt(pricing["base_premium"]), styles["amount"])]]
    for key, value in pricing["loadings"].items():
        rows.append([Paragraph(f"+ {key}", styles["label"]), Paragraph(_fmt(value), styles["amount"])])
    for key, value in pricing["discounts"].items():
        rows.append([Paragraph(f"- {key}", styles["label"]), Paragraph(_fmt(value), styles["amount"])])
    rows.extend(
        [
            [Paragraph("Net Premium", styles["label"]), Paragraph(_fmt(pricing["net_premium"]), styles["amount"])],
            [Paragraph("+ Training Levy (1%)", styles["label"]), Paragraph(_fmt(pricing["training_levy"]), styles["amount"])],
            [Paragraph("+ Stamp Duty", styles["label"]), Paragraph(_fmt(pricing["stamp_duty"]), styles["amount"])],
            [Paragraph("TOTAL ANNUAL PREMIUM", styles["value"]), Paragraph(_fmt(pricing["annual"]), styles["amount_total"])],
            [Paragraph("Monthly Premium", styles["label"]), Paragraph(_fmt(pricing["monthly"]), styles["amount"])],
        ]
    )
    table = Table(rows, colWidths=[_COL_W * 0.65, _COL_W * 0.35])
    table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 3 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm)]))
    return table


def _benefits_table(benefits: Dict[str, str], styles: Dict[str, ParagraphStyle]) -> Table:
    if not REPORTLAB_AVAILABLE:  # pragma: no cover - environment-dependent
        return benefits  # type: ignore[return-value]
    table = Table(
        [[Paragraph(label, styles["benefit_label"]), Paragraph(value, styles["benefit_value"])] for label, value in benefits.items()],
        colWidths=[_COL_W * 0.45, _COL_W * 0.55],
    )
    table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 3 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm)]))
    return table


def _header_table(quotation: Dict[str, Any], styles: Dict[str, ParagraphStyle]) -> Table:
    if not REPORTLAB_AVAILABLE:  # pragma: no cover - environment-dependent
        return quotation  # type: ignore[return-value]
    logo = _logo_flowable()
    left = []
    if logo is not None:
        left.extend([logo, _sp(1)])
    left.extend(
        [
            Paragraph(quotation.get("insurer", "Old Mutual Life Assurance Company Uganda Limited"), styles["header_sub"]),
            _sp(2),
            Paragraph(quotation.get("product", "Personal Accident Insurance"), styles["header_title"]),
            _sp(1),
            Paragraph("Personal Accident Insurance Quotation", styles["header_sub"]),
        ]
    )
    right = [
        Paragraph("Quote Number", styles["header_right_label"]),
        Paragraph(quotation.get("quote_number", "-"), styles["header_right_value"]),
        _sp(1.5),
        Paragraph("Quote Date", styles["header_right_label"]),
        Paragraph(quotation.get("quote_date", "-"), styles["header_right_value"]),
        _sp(1.5),
        Paragraph("Valid Until", styles["header_right_label"]),
        Paragraph(quotation.get("valid_until", "-"), styles["header_right_value"]),
    ]
    table = Table([[left, right]], colWidths=[_COL_W * 0.62, _COL_W * 0.38])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _GREEN),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, -1), 7 * mm),
                ("RIGHTPADDING", (1, 0), (1, -1), 6 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 6 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6 * mm),
            ]
        )
    )
    return table


def generate_quote_pdf(quotation: Dict[str, Any]) -> bytes:
    if not REPORTLAB_AVAILABLE:  # pragma: no cover - environment-dependent
        client = quotation.get("client", {})
        cover = quotation.get("cover", {})
        nok = quotation.get("next_of_kin", {})
        fallback = (
            "%PDF-1.4\n"
            "% Personal Accident Quote Fallback\n"
            f"% Quote: {quotation.get('quote_number', '-')}\n"
            f"% Client: {client.get('full_name', '-')}\n"
            f"% Email: {client.get('email', '-')}\n"
            f"% Mobile: {client.get('mobile', '-')}\n"
            f"% National ID: {client.get('national_id', '-')}\n"
            f"% Policy Start: {cover.get('policy_start_date', '-')}\n"
            f"% NOK: {nok.get('name', '-')} / {nok.get('phone', '-')}\n"
            f"% Annual: {quotation.get('pricing', {}).get('annual', 0)}\n"
            + (" " * 700)
            + "\n%%EOF"
        )
        return fallback.encode("utf-8")

    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=_MARGIN, rightMargin=_MARGIN, topMargin=_MARGIN, bottomMargin=_MARGIN)
    styles = _pdf_styles()
    client = quotation.get("client", {})
    cover = quotation.get("cover", {})
    next_of_kin = quotation.get("next_of_kin", {})
    underwriting_info = quotation.get("underwriting_info", {})
    pricing = quotation.get("pricing", {})
    underwriting_result = quotation.get("underwriting", {})
    benefits = quotation.get("benefits", {})
    story = []

    story.append(_header_table(quotation, styles))
    story.append(_sp(4))

    decision = underwriting_result.get("decision", "accept")
    decision_style = {"accept": styles["risk_accept"], "refer": styles["risk_refer"], "decline": styles["risk_decline"]}.get(decision, styles["risk_accept"])
    decision_text = {
        "accept": "Underwriting Decision: ACCEPTED",
        "refer": "Underwriting Decision: REFERRED - Specialist review required",
        "decline": "Underwriting Decision: DECLINED",
    }.get(decision, "Underwriting Decision")
    story.append(Paragraph(decision_text, decision_style))
    story.append(_sp(3))

    story.append(_section_bar("CLIENT DETAILS", styles))
    story.append(
        _kv_4col(
            [
                ("Full Name", client.get("full_name", "-")),
                ("Date of Birth", client.get("dob", "-")),
                ("Gender", client.get("gender", "-")),
                ("Nationality", client.get("nationality", "-")),
                ("Occupation", client.get("occupation", "-")),
                ("National ID", client.get("national_id", "-")),
                ("TIN", client.get("tin", "-")),
                ("Country of Residence", client.get("country_of_residence", "-")),
                ("Email", client.get("email", "-")),
                ("Mobile", client.get("mobile", "-")),
                ("Physical Address", client.get("physical_address", "-")),
                ("", ""),
            ],
            styles,
        )
    )
    story.append(_sp(3))

    story.append(_section_bar("COVER DETAILS", styles))
    story.append(
        _kv_4col(
            [
                ("Cover Limit", cover.get("cover_limit", "-")),
                ("Annual Premium", cover.get("annual_premium", "-")),
                ("Monthly Premium", cover.get("monthly_premium", "-")),
                ("Policy Start Date", cover.get("policy_start_date", "-")),
                ("Policy End Date", cover.get("policy_end_date", "-")),
                ("", ""),
            ],
            styles,
        )
    )
    story.append(_sp(3))

    if benefits:
        story.append(_section_bar("BENEFITS SCHEDULE", styles))
        story.append(_benefits_table(benefits, styles))
        story.append(_sp(3))

    story.append(_section_bar("PREMIUM BREAKDOWN", styles))
    story.append(_pricing_table(pricing, styles))
    story.append(_sp(3))

    story.append(_section_bar("NEXT OF KIN / BENEFICIARY", styles))
    story.append(
        _kv_4col(
            [
                ("Full Name", next_of_kin.get("name", "-")),
                ("Relationship", next_of_kin.get("relationship", "-")),
                ("Phone", next_of_kin.get("phone", "-")),
                ("Address", next_of_kin.get("address", "-")),
            ],
            styles,
        )
    )
    story.append(_sp(3))

    story.append(_section_bar("UNDERWRITING DECLARATIONS", styles))
    story.append(
        _kv_table(
            [
                ("Previous PA Policy", underwriting_info.get("previous_pa_policy", "-")),
                ("Free from Disability", underwriting_info.get("free_from_disability", "-")),
                ("Risky Activities", underwriting_info.get("risky_activities", "None declared")),
            ],
            styles,
        )
    )
    story.append(_sp(4))
    story.append(_hr(_GREEN, 1))
    story.append(_sp(1))
    story.append(Paragraph(quotation.get("disclaimer", ""), styles["disclaimer"]))
    story.append(_sp(2))
    story.append(
        Paragraph(
            "Old Mutual Life Assurance Company Uganda Limited is licensed "
            "and regulated by the Insurance Regulatory Authority of Uganda "
            "(IRA). This is a computer-generated document.",
            styles["footer"],
        )
    )
    document.build(story)
    return buffer.getvalue()


class PersonalAccidentPremiumService:
    @staticmethod
    def calculate_sync(product_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = payload.get("data", payload)
        sum_assured = payload.get("sum_assured")
        return calculate_premium(data, sum_assured)

    @staticmethod
    def build_quotation_sync(flow_data: Dict[str, Any], quote_id: Optional[str] = None) -> Dict[str, Any]:
        return build_quotation(flow_data, quote_id)

    @staticmethod
    def generate_pdf_sync(flow_data: Dict[str, Any], quote_id: Optional[str] = None) -> bytes:
        return generate_quote_pdf(build_quotation(flow_data, quote_id))
