"""Test Motor Private Premium Calculation - Zoho Deluge Formula."""

import pytest
from src.integrations.clients.real_http.motor_private_calculator import calculate_motor_private_premium


@pytest.fixture
def base_motor_data():
    """Base motor private form data."""
    return {
        "vehicle_value_ugx": 50_000_000,
        "car_usage_region": "Within Uganda",
        "first_time_registration": "Yes",
        "car_alarm_installed": "No",
        "tracking_system_installed": "No",
        "selected_benefits": [],
        "excess_choice": ["excess_1"],
        "cover_start_date": "2026-04-01",
        "year_of_manufacture": 2024,
        "first_name": "John",
        "surname": "Doe",
        "email": "john@example.com",
        "vehicle_make": "Toyota",
        "vehicle_model": "Camry",
    }


def test_basic_premium_calculation(base_motor_data):
    """Test basic premium calculation without add-ons."""
    result = calculate_motor_private_premium(base_motor_data)

    # Verify required keys
    assert "total" in result
    assert "base_premium" in result
    assert "training_levy" in result
    assert "vat" in result
    assert "stamp_duty" in result

    # Total should be positive
    assert result["total"] > 0

    # Stamp duty is fixed at 35,000
    assert result["stamp_duty"] == 35_000

    # Sticker fee is fixed at 6,000
    assert result["sticker_fee"] == 6_000


def test_alarm_discount_applied(base_motor_data):
    """Test that car alarm discount is applied correctly."""
    # Without alarm
    data_no_alarm = base_motor_data.copy()
    data_no_alarm["car_alarm_installed"] = "No"
    result_no_alarm = calculate_motor_private_premium(data_no_alarm)

    # With alarm
    data_with_alarm = base_motor_data.copy()
    data_with_alarm["car_alarm_installed"] = "Yes"
    result_with_alarm = calculate_motor_private_premium(data_with_alarm)

    # Premium with alarm should be lower (5% discount)
    assert result_with_alarm["total"] < result_no_alarm["total"]
    assert result_with_alarm["alarm_discount"] < 0


def test_tracker_discount_applied(base_motor_data):
    """Test that tracking system discount is applied correctly."""
    # Without tracker
    data_no_tracker = base_motor_data.copy()
    data_no_tracker["tracking_system_installed"] = "No"
    result_no_tracker = calculate_motor_private_premium(data_no_tracker)

    # With tracker
    data_with_tracker = base_motor_data.copy()
    data_with_tracker["tracking_system_installed"] = "Yes"
    result_with_tracker = calculate_motor_private_premium(data_with_tracker)

    # Premium with tracker should be lower (15% discount)
    assert result_with_tracker["total"] < result_no_tracker["total"]
    assert result_with_tracker["tracker_discount"] < 0


def test_regional_fees_within_east_africa(base_motor_data):
    """Test that regional fees are applied for Within East Africa."""
    data = base_motor_data.copy()
    data["car_usage_region"] = "Within East Africa"
    result = calculate_motor_private_premium(data)

    # Should have with_ea_fee (20% of base premium)
    assert result["with_ea_fee"] > 0
    assert result["outside_ea_fee"] == 0
    assert result["region_fee"] == result["with_ea_fee"]


def test_regional_fees_outside_east_africa(base_motor_data):
    """Test that regional fees are applied for Outside East Africa."""
    data = base_motor_data.copy()
    data["car_usage_region"] = "Outside East Africa"
    result = calculate_motor_private_premium(data)

    # Should have outside_ea_fee (30% of base premium)
    assert result["outside_ea_fee"] > 0
    assert result["with_ea_fee"] == 0
    assert result["region_fee"] == result["outside_ea_fee"]


def test_excess_discount_10_percent(base_motor_data):
    """Test 10% excess discount."""
    data = base_motor_data.copy()
    data["excess_choice"] = ["excess_1"]
    result = calculate_motor_private_premium(data)

    # 10% discount
    assert result["excess_discount"] < 0


def test_excess_discount_15_percent(base_motor_data):
    """Test 15% excess discount."""
    data = base_motor_data.copy()
    data["excess_choice"] = ["excess_2"]
    result = calculate_motor_private_premium(data)

    # Should be larger (more negative) discount than 10%
    data_10 = base_motor_data.copy()
    data_10["excess_choice"] = ["excess_1"]
    result_10 = calculate_motor_private_premium(data_10)

    assert result["excess_discount"] < result_10["excess_discount"]


def test_excess_discount_25_percent(base_motor_data):
    """Test 25% excess discount."""
    data = base_motor_data.copy()
    data["excess_choice"] = ["excess_3"]
    result = calculate_motor_private_premium(data)

    # Should be most generous discount
    data_15 = base_motor_data.copy()
    data_15["excess_choice"] = ["excess_2"]
    result_15 = calculate_motor_private_premium(data_15)

    assert result["excess_discount"] < result_15["excess_discount"]


def test_alternative_accommodation_benefit(base_motor_data):
    """Test alternative accommodation add-on."""
    # Without add-on
    data_no_addon = base_motor_data.copy()
    data_no_addon["selected_benefits"] = []
    result_no_addon = calculate_motor_private_premium(data_no_addon)

    # With add-on
    data_with_addon = base_motor_data.copy()
    data_with_addon["selected_benefits"] = ["alternative_accommodation"]
    result_with_addon = calculate_motor_private_premium(data_with_addon)

    # Should have alternative accommodation price
    assert result_with_addon["alternative_accommodation"] > 0
    assert result_with_addon["alternative_accommodation"] == 0 or result_with_addon["total"] > result_no_addon["total"]


def test_car_hire_benefit(base_motor_data):
    """Test car hire add-on."""
    # Without add-on
    data_no_addon = base_motor_data.copy()
    data_no_addon["selected_benefits"] = []
    result_no_addon = calculate_motor_private_premium(data_no_addon)

    # With add-on
    data_with_addon = base_motor_data.copy()
    data_with_addon["selected_benefits"] = ["car_hire"]
    result_with_addon = calculate_motor_private_premium(data_with_addon)

    # Should have car hire price
    assert result_with_addon["car_hire"] > 0
    assert result_with_addon["total"] > result_no_addon["total"]


def test_political_violence_benefit(base_motor_data):
    """Test political violence & terrorism add-on."""
    # Without add-on
    data_no_addon = base_motor_data.copy()
    data_no_addon["selected_benefits"] = []
    result_no_addon = calculate_motor_private_premium(data_no_addon)

    # With add-on
    data_with_addon = base_motor_data.copy()
    data_with_addon["selected_benefits"] = ["political_violence"]
    result_with_addon = calculate_motor_private_premium(data_with_addon)

    # PVT fee should be 0.25% of base premium
    assert result_with_addon["pvt_fee"] > 0
    assert result_with_addon["total"] > result_no_addon["total"]


def test_combined_benefits(base_motor_data):
    """Test multiple benefits combined."""
    data = base_motor_data.copy()
    data["selected_benefits"] = [
        "political_violence",
        "alternative_accommodation",
        "car_hire"
    ]
    data["car_alarm_installed"] = "Yes"
    data["tracking_system_installed"] = "Yes"
    data["car_usage_region"] = "Outside East Africa"

    result = calculate_motor_private_premium(data)

    # Verify all components are present
    assert result["pvt_fee"] > 0
    assert result["alternative_accommodation"] > 0
    assert result["car_hire"] > 0
    assert result["alarm_discount"] < 0
    assert result["tracker_discount"] < 0
    assert result["outside_ea_fee"] > 0
    assert result["total"] > 0


def test_minimum_value_enforcement(base_motor_data):
    """Test with minimum vehicle value (10M)."""
    data = base_motor_data.copy()
    data["vehicle_value_ugx"] = 10_000_000
    result = calculate_motor_private_premium(data)

    # Should calculate successfully
    assert result["total"] > 0
    assert result["base_premium"] == 10_000_000 * 0.04


def test_maximum_value_enforcement(base_motor_data):
    """Test with maximum vehicle value (100M)."""
    data = base_motor_data.copy()
    data["vehicle_value_ugx"] = 100_000_000
    result = calculate_motor_private_premium(data)

    # Should calculate successfully
    assert result["total"] > 0
    assert result["base_premium"] == 100_000_000 * 0.04


def test_return_format(base_motor_data):
    """Test that response has required aliases for compatibility."""
    result = calculate_motor_private_premium(base_motor_data)

    # Check for backward compatibility fields
    assert "premium" in result
    assert "premiumString" in result
    assert result["premium"] == result["total"]
    assert result["premiumString"] == str(result["total"])


def test_vat_calculation(base_motor_data):
    """Test VAT is 18% of subtotal + levy + sticker."""
    result = calculate_motor_private_premium(base_motor_data)

    # VAT should be 18% of (subtotal + training_levy + sticker_fee)
    expected_vat_base = result["subtotal"] + result["training_levy"] + result["sticker_fee"]
    expected_vat = expected_vat_base * 0.18

    # Allow small rounding differences
    assert abs(result["vat"] - expected_vat) < 1


def test_total_calculation(base_motor_data):
    """Test total = stamp_duty + subtotal + training_levy + vat + sticker_fee."""
    result = calculate_motor_private_premium(base_motor_data)

    expected_total = (
        result["stamp_duty"]
        + result["subtotal"]
        + result["training_levy"]
        + result["vat"]
        + result["sticker_fee"]
    )

    assert result["total"] == expected_total
