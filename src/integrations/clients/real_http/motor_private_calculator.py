"""Motor Private Premium Calculator - Zoho Deluge Formula Implementation.

This module implements the exact premium calculation logic from Zoho Deluge,
handling all discounts, add-ons, taxes, and fees for Motor Private policies.
"""

from __future__ import annotations

from typing import Any, Dict


def calculate_motor_private_premium(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate Motor Private premium using Zoho Deluge formula.

    Args:
        session_data (dict): Form data containing:
            - vehicle_value_ugx or carValue: Vehicle value in UGX
            - car_usage_region or regionBounds: "Within Uganda", "Within East Africa", "Outside East Africa"
            - first_time_registration or firstApplication: "Yes"/"No" or boolean
            - car_alarm_installed or alarmDiscountRate: "Yes"/"No"
            - tracking_system_installed or trackerDiscountRate: "Yes"/"No"
            - selected_benefits or additional_benefits: List of benefit IDs
            - cover_start_date or coverStartDate: ISO date string
            - year_of_manufacture or yearOfManufacture: Year as int/string
            - first_name, surname, email: Customer details
            - vehicle_make, vehicle_model: Vehicle info

    Returns:
        dict: Premium breakdown with:
            - base_premium: Base premium before taxes
            - alarm_discount: Discount for car alarm (-5%)
            - tracker_discount: Discount for tracking system (-15%)
            - pvt_fee: Political violence & terrorism fee (if selected)
            - region_fee: Within/Outside East Africa fee
            - alternative_accommodation: Price if selected
            - car_hire: Price if selected
            - excess_discount: Discount based on excess selection
            - subtotal: Sum before taxes/duties
            - training_levy: 0.5% of base
            - sticker_fee: UGX 6,000
            - vat: 18% of subtotal + levy + sticker
            - stamp_duty: UGX 35,000
            - total: Final payable amount
            - message: Download message with API response
            - downloadUrl: PDF quote download URL
            - premium: Total (alias for backward compatibility)
            - premiumString: Total as string
    """

    # --------------------------
    # Extract & Normalize Inputs
    # --------------------------
    car_value = float(session_data.get("vehicle_value_ugx") or session_data.get("carValue") or 0)
    region = session_data.get("car_usage_region") or session_data.get("regionBounds") or "Within Uganda"

    first_app_val = session_data.get("first_time_registration") or session_data.get("firstApplication") or "no"
    first_app = str(first_app_val).lower() in ("yes", "true", 1, True)

    alarm_val = session_data.get("car_alarm_installed") or session_data.get("alarmDiscountRate") or "no"
    has_alarm = str(alarm_val).lower() in ("yes", "true", 1, True)

    tracker_val = session_data.get("tracking_system_installed") or session_data.get("trackerDiscountRate") or "no"
    has_tracker = str(tracker_val).lower() in ("yes", "true", 1, True)

    # Benefits / add-ons
    selected_benefits = session_data.get("selected_benefits") or session_data.get("additional_benefits") or []
    if isinstance(selected_benefits, str):
        selected_benefits = [b.strip() for b in selected_benefits.split(",") if b.strip()]
    selected_benefits_lower = [str(b).lower() for b in selected_benefits]

    has_pvt = "political_violence" in selected_benefits_lower
    has_alt_acc = "alternative_accommodation" in selected_benefits_lower
    has_car_hire = "car_hire" in selected_benefits_lower

    # Excess selection
    excess_choice = session_data.get("excess_choice") or session_data.get("excessValue") or "excess_1"
    if isinstance(excess_choice, list):
        excess_choice = excess_choice[0] if excess_choice else "excess_1"
    excess_choice = str(excess_choice).lower()

    # Customer & vehicle details
    full_name = session_data.get("full_name") or session_data.get("fullName") or ""
    first_name = session_data.get("first_name") or session_data.get("firstName") or full_name.split()[0] if full_name else ""
    surname = session_data.get("surname") or session_data.get("lastName") or " ".join(full_name.split()[1:]) if full_name else ""
    email = session_data.get("email") or ""

    vehicle_make = session_data.get("vehicle_make") or session_data.get("vehicleMake") or ""
    vehicle_model = session_data.get("vehicle_model") or session_data.get("vehicleModel") or ""

    # --------------------------
    # Premium Calculation Constants
    # --------------------------
    premium_factor = 0.04
    base_premium_itl = 0.005  # International Training Levy
    base_vat_rate = 0.18
    sticker_fee = 6_000
    stamp_duty_rate = 35_000

    # Add-on constants
    alternative_accommodation_amount = 300_000
    alternative_accommodation_rate = 0.1
    alternative_training_levy = 0.005
    alternative_accommodation_vat = 0.18

    car_hire_amount = 100_000
    car_hire_rate = 0.1
    car_hire_levy = 0.005
    car_hire_vat = 0.18

    # Regional fees
    with_ea_fee_rate = 0.2
    outside_ea_fee_rate = 0.3

    # --------------------------
    # Region Mapping
    # --------------------------
    if "outside" in region.lower() or "outside east africa" in region.lower():
        region_bounds = 3
    elif "east africa" in region.lower() or "within east africa" in region.lower():
        region_bounds = 2
    else:
        region_bounds = 1  # Within Uganda

    # --------------------------
    # Base Premium Calculation
    # --------------------------
    base_premium = car_value * premium_factor

    # Political Violence & Terrorism (0.25% of base premium, displayed as fee here)
    pvt_fee = base_premium * 0.0025 if has_pvt else 0

    # Excess Discount
    excess_discount = 0
    if "excess_1" in excess_choice or "10%" in str(excess_choice):
        excess_discount = base_premium * -0.10
    elif "excess_2" in excess_choice or "15%" in str(excess_choice):
        excess_discount = base_premium * -0.15
    elif "excess_3" in excess_choice or "25%" in str(excess_choice):
        excess_discount = base_premium * -0.25

    # Region-based fees
    with_ea_fee = base_premium * with_ea_fee_rate if region_bounds == 2 else 0
    outside_ea_fee = base_premium * outside_ea_fee_rate if region_bounds == 3 else 0

    # Discounts for security features
    alarm_discount = base_premium * -0.05 if has_alarm else 0
    tracker_discount = base_premium * -0.15 if has_tracker else 0

    # --------------------------
    # Add-on Pricing
    # --------------------------
    alternative_accommodation_price = 0
    if has_alt_acc:
        base_alt_acc = alternative_accommodation_amount * alternative_accommodation_rate
        training_fee = base_alt_acc * alternative_training_levy
        vat_imposed = (base_alt_acc + training_fee) * alternative_accommodation_vat
        alternative_accommodation_price = base_alt_acc + training_fee + vat_imposed

    car_hire_price = 0
    if has_car_hire:
        base_car_hire = car_hire_amount * car_hire_rate
        training_fee = base_car_hire * car_hire_levy
        vat_imposed = (base_car_hire + training_fee) * car_hire_vat
        car_hire_price = base_car_hire + training_fee + vat_imposed

    # --------------------------
    # Final Premium Calculation
    # --------------------------
    # Subtotal: base + all adjustments + add-ons
    subtotal = (
        base_premium
        + alarm_discount
        + tracker_discount
        + pvt_fee
        + with_ea_fee
        + outside_ea_fee
        + alternative_accommodation_price
        + car_hire_price
        + excess_discount
    )

    # Ensure non-negative subtotal
    subtotal = max(0, subtotal)

    # Training levy (0.5% of subtotal)
    training_levy = subtotal * base_premium_itl

    # VAT (18% of subtotal + training levy + sticker fee)
    vat_amount = (subtotal + training_levy + sticker_fee) * base_vat_rate

    # Total premium
    total_premium = stamp_duty_rate + subtotal + training_levy + vat_amount + sticker_fee

    # Ensure non-negative
    total_premium = max(0, total_premium)

    # --------------------------
    # Prepare payload for Underwriting API
    # --------------------------
    api_payload = {
        "premium": round(total_premium),
        "withinEAFee": round(with_ea_fee),
        "outsideEAFee": round(outside_ea_fee),
        "excessDiscount": round(excess_discount),
        "sumInsured": round(car_value),
        "threeYearsWithLicense": first_app,
        "fullname": f"{first_name} {surname}".strip(),
        "make": vehicle_make,
        "model": vehicle_model,
        "email": email,
        "roadsideAssistance": True,
        "courtesyCar": False,
        "medicalExpenses": True,
        "personalAccident": True,
        "politicalViolence": has_pvt,
        "carAlarm": has_alarm,
        "trackingSystem": has_tracker,
        "alternativeAccommodation": has_alt_acc,
        "carHire": has_car_hire,
    }

    # --------------------------
    # Call Underwriting API (optional - can fail gracefully)
    # --------------------------
    download_url = "NOT AVAILABLE"
    try:
        import requests
        url = "https://bot.uapoldmutual.com/whatsapp/qa/ug/zoho/motor/generateQuoteDoc"
        headers = {"Content-Type": "application/json"}
        response = requests.post(url, json=api_payload, headers=headers, timeout=10)
        response.raise_for_status()
        resp_json = response.json()
        download_url = resp_json.get("fileUrl", "NOT AVAILABLE")
    except (ImportError, Exception):
        # Graceful failure - calculation still succeeds, just no PDF link
        download_url = "NOT AVAILABLE"

    if download_url != "NOT AVAILABLE":
        message = f"Click below to download your quote:\n{download_url}"
    else:
        message = "Quote calculation complete. PDF generation unavailable."

    # --------------------------
    # Return structured breakdown
    # --------------------------
    return {
        "base_premium": round(base_premium),
        "alarm_discount": round(alarm_discount),
        "tracker_discount": round(tracker_discount),
        "pvt_fee": round(pvt_fee),
        "region_fee": round(with_ea_fee + outside_ea_fee),
        "with_ea_fee": round(with_ea_fee),
        "outside_ea_fee": round(outside_ea_fee),
        "alternative_accommodation": round(alternative_accommodation_price),
        "car_hire": round(car_hire_price),
        "excess_discount": round(excess_discount),
        "subtotal": round(subtotal),
        "training_levy": round(training_levy),
        "sticker_fee": sticker_fee,
        "vat": round(vat_amount),
        "stamp_duty": stamp_duty_rate,
        "total": round(total_premium),
        # Aliases for backward compatibility
        "premium": round(total_premium),
        "premiumString": str(round(total_premium)),
        "message": message,
        "downloadUrl": download_url,
    }
