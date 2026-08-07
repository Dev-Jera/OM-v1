"""Local Serenicare underwriting, premium, quotation, and PDF logic."""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta
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


SERENICARE_PLANS: List[Dict[str, Any]] = [
    {
        "id": "essential",
        "label": "Essential",
        "description": "Reliable coverage with fundamental limits, offering value and security.",
        "annual_base_premium": 480_000,
        "benefits": {
            "Inpatient limit per family": "UGX 15,000,000",
            "Outpatient limit per person": "UGX 1,500,000",
            "Maternity cover per family": "UGX 1,500,000",
            "Optical limit per person": "UGX 200,000",
            "Dental limit per person": "UGX 150,000",
            "Last Expense": "UGX 1,000,000",
        },
    },
    {
        "id": "classic",
        "label": "Classic",
        "description": "A balanced choice, delivering broader coverage with standout benefits.",
        "annual_base_premium": 960_000,
        "benefits": {
            "Inpatient limit per family": "UGX 30,000,000",
            "Outpatient limit per person": "UGX 2,000,000",
            "Maternity cover per family": "UGX 2,500,000",
            "Optical limit per person": "UGX 300,000",
            "Dental limit per person": "UGX 200,000",
            "Last Expense": "UGX 2,000,000",
            "Emergency Evacuation": "Included",
        },
    },
    {
        "id": "comprehensive",
        "label": "Comprehensive",
        "description": "Expansive coverage with high limits for extensive health security.",
        "annual_base_premium": 1_800_000,
        "benefits": {
            "Inpatient limit per family": "UGX 60,000,000",
            "Outpatient limit per person": "UGX 3,000,000",
            "Maternity cover per family": "UGX 3,000,000",
            "Optical limit per person": "UGX 350,000",
            "Dental limit per person": "UGX 300,000",
            "Last Expense": "UGX 3,000,000",
            "Emergency Evacuation": "Included",
            "International Cover": "East Africa",
        },
    },
    {
        "id": "premium",
        "label": "Premium",
        "description": "Ultimate health protection for those demanding the best healthcare.",
        "annual_base_premium": 3_600_000,
        "benefits": {
            "Inpatient limit per family": "UGX 100,000,000",
            "Outpatient limit per person": "UGX 5,000,000",
            "Maternity cover per family": "UGX 4,000,000",
            "Optical limit per person": "UGX 400,000",
            "Dental limit per person": "UGX 400,000",
            "Last Expense": "UGX 5,000,000",
            "Emergency Evacuation": "Included",
            "International Cover": "Worldwide (excl. USA/Canada)",
            "Wellness Check": "Annual - included",
        },
    },
]
_PLAN_BY_ID = {plan["id"]: plan for plan in SERENICARE_PLANS}
OPTIONAL_BENEFITS: List[Dict[str, Any]] = [
    {"id": "outpatient", "label": "Outpatient", "premium": 180_000},
    {"id": "maternity", "label": "Maternity Cover", "premium": 240_000},
    {"id": "dental", "label": "Dental Cover", "premium": 96_000},
    {"id": "optical", "label": "Optical Cover", "premium": 72_000},
    {"id": "covid19", "label": "COVID-19 Cover", "premium": 60_000},
]
_BENEFIT_BY_ID = {benefit["id"]: benefit for benefit in OPTIONAL_BENEFITS}
_AGE_LOADINGS: List[Tuple[int, int, float]] = [
    (0, 17, 0.50),
    (18, 35, 1.00),
    (36, 50, 1.15),
    (51, 60, 1.30),
    (61, 70, 1.50),
    (71, 99, 1.75),
]
_MEDICAL_CONDITION_LOADING = 0.20
_CHILD_FLAT_RATE = 0.50
_TRAINING_LEVY_RATE = 0.010
_STAMP_DUTY = 15_000


def _fmt(amount: float) -> str:
    return f"UGX {int(round(amount)):,}"


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
    for key in ("about_you", "plan_option", "cover_personalization", "medical_conditions", "optional_benefits"):
        source = flow_data.get(key)
        if isinstance(source, dict):
            merged.update(source)
        elif isinstance(source, list):
            merged[key] = source
    merged.update(flow_data)
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


def _member_loading(age: Optional[int]) -> Tuple[float, str]:
    if age is None:
        return 1.0, "Unknown age"
    for min_age, max_age, rate in _AGE_LOADINGS:
        if min_age <= age <= max_age:
            if rate == 1.0:
                return rate, f"Age {age} (standard rate)"
            if rate > 1.0:
                return rate, f"Age {age} loading ({int((rate - 1) * 100)}%)"
            return rate, f"Age {age} discount ({int((1 - rate) * 100)}%)"
    return 1.75, f"Age {age} (+75% loading)"


def _get_plan(plan_data: Any) -> Dict[str, Any]:
    if isinstance(plan_data, str):
        return _PLAN_BY_ID.get(plan_data, SERENICARE_PLANS[0])
    if isinstance(plan_data, dict):
        plan_id = plan_data.get("id", "")
        fallback = plan_data if plan_data.get("annual_base_premium") else SERENICARE_PLANS[0]
        return _PLAN_BY_ID.get(plan_id, fallback)
    return SERENICARE_PLANS[0]


def underwrite(data: Dict[str, Any]) -> Dict[str, Any]:
    flat = _flatten(data)
    reasons: List[str] = []
    risk_factors: List[str] = []
    score = 0
    age = _age_from_dob(_pull(flat, "date_of_birth"))
    if age is not None:
        if age < 18:
            reasons.append("Main member must be at least 18 years old.")
            score += 40
        elif age > 70:
            risk_factors.append(f"Main member age {age} - high age loading applied.")
            score += 20
        elif age > 60:
            risk_factors.append(f"Main member age {age} - senior loading applied.")
            score += 10
    if str(_pull(flat, "has_condition", default=False)).lower() in {"true", "yes", "1"}:
        risk_factors.append("Pre-existing medical condition declared - 20% loading applied; specialist review recommended.")
        score += 25
    if str(_pull(flat, "include_spouse", default=False)).lower() in {"true", "yes", "1"}:
        risk_factors.append("Spouse included - age loading applied separately.")
    if str(_pull(flat, "include_children", default=False)).lower() in {"true", "yes", "1"}:
        risk_factors.append("Children included - child rate applied.")
    decision = "refer" if score >= 25 else "accept"
    if reasons and score >= 40:
        decision = "decline"
    return {"decision": decision, "reasons": reasons, "risk_factors": risk_factors, "risk_score": score}


def calculate_premium(data: Dict[str, Any], plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    flat = _flatten(data)
    plan = _get_plan(plan if plan is not None else _pull(flat, "plan_option", "plan", default={}))
    base = float(plan.get("annual_base_premium", 480_000))
    age = _age_from_dob(_pull(flat, "date_of_birth"))
    has_condition = str(_pull(flat, "has_condition", default=False)).lower() in {"true", "yes", "1"}
    include_spouse = str(_pull(flat, "include_spouse", default=False)).lower() in {"true", "yes", "1"}
    include_children = str(_pull(flat, "include_children", default=False)).lower() in {"true", "yes", "1"}
    add_another = str(_pull(flat, "add_another_main_member", default=False)).lower() in {"true", "yes", "1"}
    optional_raw = flat.get("optional_benefits") or data.get("optional_benefits") or []
    if isinstance(optional_raw, str):
        optional_raw = [item.strip() for item in optional_raw.split(",") if item.strip()]
    selected_benefits = optional_raw if isinstance(optional_raw, list) else []

    main_mod, _ = _member_loading(age)
    member_breakdown: Dict[str, float] = {"Main member": base * main_mod}
    if include_spouse:
        spouse_age = _age_from_dob(_pull(flat, "spouse_dob")) or age
        spouse_mod, _ = _member_loading(spouse_age)
        member_breakdown["Spouse / Partner"] = base * spouse_mod
    if include_children:
        child_count = int(_pull(flat, "child_count", default=1) or 1)
        member_breakdown[f"Children (x{child_count})"] = base * _CHILD_FLAT_RATE * child_count
    if add_another:
        member_breakdown["Additional main member"] = base

    benefit_breakdown = {
        item["label"]: float(item["premium"])
        for benefit_id in selected_benefits
        if (item := _BENEFIT_BY_ID.get(str(benefit_id).strip()))
    }
    total_members = sum(member_breakdown.values())
    total_benefits = sum(benefit_breakdown.values())
    loadings: Dict[str, float] = {}
    if has_condition:
        loadings["Pre-existing condition loading (20%)"] = (total_members + total_benefits) * _MEDICAL_CONDITION_LOADING
    total_loadings = sum(loadings.values())
    net_premium = total_members + total_benefits + total_loadings
    training_levy = net_premium * _TRAINING_LEVY_RATE
    stamp_duty = float(_STAMP_DUTY)
    annual = net_premium + training_levy + stamp_duty
    monthly = annual / 12
    return {
        "plan_id": plan.get("id", ""),
        "plan_label": plan.get("label", ""),
        "member_breakdown": {k: round(v, 2) for k, v in member_breakdown.items()},
        "total_members": round(total_members, 2),
        "benefit_breakdown": {k: round(v, 2) for k, v in benefit_breakdown.items()},
        "total_benefits": round(total_benefits, 2),
        "loadings": {k: round(v, 2) for k, v in loadings.items()},
        "total_loadings": round(total_loadings, 2),
        "net_premium": round(net_premium, 2),
        "training_levy": round(training_levy, 2),
        "stamp_duty": round(stamp_duty, 2),
        "annual": round(annual, 2),
        "monthly": round(monthly, 2),
        "total": round(annual, 2),
        "breakdown": {
            "member_breakdown": {k: round(v, 2) for k, v in member_breakdown.items()},
            "benefit_breakdown": {k: round(v, 2) for k, v in benefit_breakdown.items()},
            "loadings": {k: round(v, 2) for k, v in loadings.items()},
            "training_levy": round(training_levy, 2),
            "stamp_duty": round(stamp_duty, 2),
        },
        "formatted": {
            "total_members": _fmt(total_members),
            "total_benefits": _fmt(total_benefits),
            "total_loadings": _fmt(total_loadings),
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
    plan = _get_plan(_pull(flat, "plan_option", "plan", default={}))
    pricing = calculate_premium(flat, plan)
    name_parts = [
        _text(_pull(flat, "first_name", default=""), default=""),
        _text(_pull(flat, "middle_name", default=""), default=""),
        _text(_pull(flat, "surname", default=""), default=""),
    ]
    full_name = " ".join(filter(None, name_parts)) or "—"
    today = date.today()
    start_raw = _pull(flat, "policy_start_date", default=str(today + timedelta(days=1)))
    try:
        start_date = date.fromisoformat(str(start_raw)[:10])
        end_date = date(start_date.year + 1, start_date.month, start_date.day).isoformat()
    except (ValueError, TypeError):
        end_date = "—"
    members = ["Main member (you)"]
    if str(_pull(flat, "include_spouse", default=False)).lower() in {"true", "yes", "1"}:
        members.append("Spouse / Partner")
    if str(_pull(flat, "include_children", default=False)).lower() in {"true", "yes", "1"}:
        members.append(f"Children (x{int(_pull(flat, 'child_count', default=1) or 1)})")
    if str(_pull(flat, "add_another_main_member", default=False)).lower() in {"true", "yes", "1"}:
        members.append("Additional main member")
    optional_raw = flat.get("optional_benefits") or []
    if isinstance(optional_raw, str):
        optional_raw = [item.strip() for item in optional_raw.split(",") if item.strip()]
    optional_labels = [
        _BENEFIT_BY_ID[item]["label"]
        for item in (optional_raw if isinstance(optional_raw, list) else [])
        if item in _BENEFIT_BY_ID
    ] or ["None selected"]
    has_condition = str(_pull(flat, "has_condition", default=False)).lower() in {"true", "yes", "1"}
    return {
        "quote_number": quote_id or f"OMU-SC-{today.strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}",
        "quote_date": today.isoformat(),
        "valid_until": (today + timedelta(days=30)).isoformat(),
        "insurer": "Old Mutual Life Assurance Company Uganda Limited",
        "product": "Serenicare Health Insurance",
        "client": {
            "full_name": full_name,
            "email": _text(_pull(flat, "email", default="—"), default="—"),
            "mobile": _text(_pull(flat, "phone_number", "mobile", default="—"), default="—"),
            "dob": _text(_pull(flat, "date_of_birth", "dob", default="—"), default="—"),
        },
        "plan": {
            "id": plan.get("id", "—"),
            "label": plan.get("label", "—"),
            "description": plan.get("description", ""),
            "benefits": plan.get("benefits", {}),
        },
        "cover": {
            "members_covered": members,
            "policy_start_date": _text(start_raw, default="—"),
            "policy_end_date": end_date,
            "annual_premium": pricing["formatted"]["annual"],
            "monthly_premium": pricing["formatted"]["monthly"],
            "optional_benefits": optional_labels,
            "medical_conditions": "Yes - loading applied" if has_condition else "None declared",
        },
        "pricing": pricing,
        "underwriting": pricing["underwriting"],
        "disclaimer": (
            "This quotation is valid for 30 days from the quote date. Premium rates are indicative and subject to "
            "final underwriting approval. Benefits are subject to policy terms and conditions. Pre-existing "
            "conditions are subject to a waiting period as per policy terms. Old Mutual Uganda is regulated by the "
            "Insurance Regulatory Authority of Uganda (IRA). Cover commences only upon receipt of full premium payment."
        ),
    }


def build_serenicare_underwriting(payload: Dict[str, Any], quote_id: str) -> Dict[str, Any]:
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
        "product_mock": "serenicare",
        "plan_id": pricing.get("plan_id", ""),
        "breakdown": pricing["breakdown"],
    }


def build_serenicare_premium(payload: Dict[str, Any]) -> Dict[str, Any]:
    return calculate_premium(payload)


def build_serenicare_quote(payload: Dict[str, Any], underwriting: Dict[str, Any]) -> Dict[str, Any]:
    quotation = build_quotation(payload, underwriting.get("quote_id"))
    pricing = quotation["pricing"]
    return {
        "quote_id": underwriting.get("quote_id") or quotation["quote_number"],
        "premium": pricing["total"],
        "amount": pricing["total"],
        "payable_amount": pricing["total"],
        "currency": "UGX",
        "status": "QUOTED",
        "product_mock": "serenicare",
        "billing_frequency": "annual",
        "plan_id": pricing.get("plan_id", ""),
        "breakdown": pricing["breakdown"],
        "quotation": quotation,
    }


def generate_quote_pdf(quotation: Dict[str, Any]) -> bytes:
    if not REPORTLAB_AVAILABLE:  # pragma: no cover - environment-dependent
        client = quotation.get("client", {})
        cover = quotation.get("cover", {})
        underwriting = quotation.get("underwriting", {})
        decision_label = {
            "accept": "ACCEPTED",
            "refer": "REFERRED",
            "decline": "DECLINED",
        }.get(str(underwriting.get("decision", "accept")).lower(), "ACCEPTED")
        content = [
            "Serenicare Health Insurance Quotation",
            f"Quote Number: {quotation.get('quote_number', '-')}" ,
            f"Client: {client.get('full_name', '-')}" ,
            f"Email: {client.get('email', '-')}" ,
            f"Mobile: {client.get('mobile', '-')}" ,
            f"DOB: {client.get('dob', '-')}" ,
            f"Plan: {quotation.get('plan', {}).get('label', '-')}" ,
            f"Policy Start: {cover.get('policy_start_date', '-')}" ,
            f"Underwriting Decision: {decision_label}",
            f"Annual Premium: {quotation.get('cover', {}).get('annual_premium', '-')}" ,
        ]
        for note in underwriting.get("reasons", []):
            content.append(f"Underwriting Note: {note}")
        for factor in underwriting.get("risk_factors", []):
            content.append(f"Risk Factor: {factor}")
        return ("%PDF-1.4\n" + "\n".join(content) + "\n%%EOF").encode("utf-8")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    base = getSampleStyleSheet()
    green = colors.HexColor("#006835")
    light_green = colors.HexColor("#e8f5e9")
    light = colors.HexColor("#f7f7f7")
    line = colors.HexColor("#cccccc")
    dark = colors.HexColor("#1a1a1a")
    mid = colors.HexColor("#555555")
    page_width = A4[0] - 32 * mm

    header_title = ParagraphStyle(
        "sc_header_title", parent=base["Normal"], fontSize=20, leading=24, textColor=colors.white, fontName="Helvetica-Bold", alignment=TA_LEFT
    )
    header_sub = ParagraphStyle(
        "sc_header_sub",
        parent=base["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#ccffcc"),
        fontName="Helvetica",
        alignment=TA_LEFT,
    )
    header_right_label = ParagraphStyle(
        "sc_header_rl",
        parent=base["Normal"],
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#aaddaa"),
        fontName="Helvetica",
        alignment=TA_RIGHT,
    )
    header_right_value = ParagraphStyle(
        "sc_header_rv",
        parent=base["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.white,
        fontName="Helvetica-Bold",
        alignment=TA_RIGHT,
    )
    section_style = ParagraphStyle(
        "sc_section", parent=base["Normal"], fontSize=9, leading=12, textColor=colors.white, fontName="Helvetica-Bold"
    )
    label_style = ParagraphStyle("sc_label", parent=base["Normal"], fontSize=8, leading=11, textColor=mid, fontName="Helvetica")
    value_style = ParagraphStyle("sc_value", parent=base["Normal"], fontSize=8.5, leading=11, textColor=dark, fontName="Helvetica-Bold")
    amount_style = ParagraphStyle("sc_amount", parent=base["Normal"], fontSize=8.5, leading=11, textColor=dark, fontName="Helvetica", alignment=TA_RIGHT)
    amount_total_style = ParagraphStyle(
        "sc_amount_total",
        parent=base["Normal"],
        fontSize=11,
        leading=14,
        textColor=green,
        fontName="Helvetica-Bold",
        alignment=TA_RIGHT,
    )
    body_style = ParagraphStyle("sc_body", parent=base["Normal"], fontSize=8, leading=11, textColor=dark, fontName="Helvetica")
    disclaimer_style = ParagraphStyle("sc_disclaimer", parent=base["Normal"], fontSize=6.5, leading=9, textColor=mid, fontName="Helvetica-Oblique")
    footer_style = ParagraphStyle("sc_footer", parent=base["Normal"], fontSize=7, leading=9, textColor=mid, fontName="Helvetica", alignment=TA_CENTER)
    risk_style = ParagraphStyle("sc_risk", parent=base["Normal"], fontSize=8.5, leading=11, textColor=colors.HexColor("#2e7d32"), fontName="Helvetica-Bold")

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
        table = Table(rows, colWidths=[page_width * 0.5, page_width * 0.5])
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

        def add_row(label: str, amount: float, highlight: bool = False) -> None:
            rows.append([
                Paragraph(label, value_style if highlight else label_style),
                Paragraph(_fmt(amount), amount_total_style if highlight else amount_style),
            ])

        for label, amount in pricing.get("member_breakdown", {}).items():
            add_row(f"    {label}", amount)
        add_row("Total Member Premiums", pricing.get("total_members", 0))
        for label, amount in pricing.get("benefit_breakdown", {}).items():
            add_row(f"    + {label}", amount)
        if pricing.get("total_benefits"):
            add_row("Total Optional Benefits", pricing.get("total_benefits", 0))
        for label, amount in pricing.get("loadings", {}).items():
            add_row(f"    + {label}", amount)
        add_row("Net Premium", pricing.get("net_premium", 0))
        add_row("+ Training Levy (1%)", pricing.get("training_levy", 0))
        add_row("+ Stamp Duty", pricing.get("stamp_duty", 0))
        rows.append([HRFlowable(width="100%", thickness=1, color=green), HRFlowable(width="100%", thickness=1, color=green)])
        add_row("TOTAL ANNUAL PREMIUM", pricing.get("annual", 0), True)
        add_row("Monthly Premium (? 12)", pricing.get("monthly", 0))

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
            Paragraph(quotation.get("product", "Serenicare Health Insurance"), header_title),
            spacer(1),
            Paragraph("Health Insurance Quotation", header_sub),
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

    plan = quotation.get("plan", {})
    client = quotation.get("client", {})
    cover = quotation.get("cover", {})
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
        section_bar("SELECTED PLAN"),
        spacer(2),
        Paragraph(f"Serenicare {plan.get('label', '-')}" , value_style),
        spacer(1),
        Paragraph(plan.get("description", ""), body_style),
        spacer(2),
        benefits_table(plan.get("benefits", {})),
        spacer(3),
        section_bar("CLIENT DETAILS"),
        kv_4col([
            ("Full Name", str(client.get("full_name", "-"))),
            ("Date of Birth", str(client.get("dob", "-"))),
            ("Email", str(client.get("email", "-"))),
            ("Mobile", str(client.get("mobile", "-"))),
        ]),
        spacer(3),
        section_bar("COVER DETAILS"),
        kv_4col([
            ("Members Covered", ", ".join(cover.get("members_covered", ["-"]))),
            ("Medical Conditions", str(cover.get("medical_conditions", "-"))),
            ("Optional Benefits", ", ".join(cover.get("optional_benefits", ["None selected"]))),
            ("Policy Start Date", str(cover.get("policy_start_date", "-"))),
            ("Policy End Date", str(cover.get("policy_end_date", "-"))),
            ("Annual Premium", str(cover.get("annual_premium", "-"))),
            ("Monthly Premium", str(cover.get("monthly_premium", "-"))),
            ("", ""),
        ]),
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


class SerenicarePremuimService:
    @staticmethod
    def calculate_sync(product_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return calculate_premium(payload.get("data", payload), payload.get("plan"))

    @staticmethod
    def build_quotation_sync(flow_data: Dict[str, Any], quote_id: Optional[str] = None) -> Dict[str, Any]:
        return build_quotation(flow_data, quote_id)

    @staticmethod
    def generate_pdf_sync(flow_data: Dict[str, Any], quote_id: Optional[str] = None) -> bytes:
        return generate_quote_pdf(build_quotation(flow_data, quote_id))
