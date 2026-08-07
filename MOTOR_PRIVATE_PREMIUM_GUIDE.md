# Motor Private Premium Calculation Integration

## Overview

The Motor Private premium calculation now uses the **Zoho Deluge formula**, providing accurate, real-world pricing with support for:
- Regional fees (Within Uganda, Within/Outside East Africa)
- Security discounts (car alarm, tracking system)
- Add-on benefits (alternative accommodation, car hire, political violence)
- Excess options (10%, 15%, 25%)
- Proper tax & duty calculations

## API Endpoint

### Calculate Quote

**URL:** `POST /api/v1/motor-private/calculate-quote`

**Request:**
```json
{
  "user_id": "0700111222",
  "data": {
    "vehicle_value_ugx": 50000000,
    "car_usage_region": "Within Uganda",
    "first_time_registration": "Yes",
    "car_alarm_installed": "No",
    "tracking_system_installed": "Yes",
    "selected_benefits": ["political_violence", "alternative_accommodation"],
    "excess_choice": ["excess_1"],
    "cover_start_date": "2026-05-01",
    "year_of_manufacture": 2024,
    "first_name": "John",
    "surname": "Doe",
    "email": "john@example.com",
    "vehicle_make": "Toyota",
    "vehicle_model": "Camry"
  }
}
```

**Response:**
```json
{
  "success": true,
  "premium_breakdown": {
    "base_premium": 2000000,
    "alarm_discount": 0,
    "tracker_discount": -300000,
    "pvt_fee": 5000,
    "region_fee": 0,
    "with_ea_fee": 0,
    "outside_ea_fee": 0,
    "alternative_accommodation": 33000,
    "car_hire": 0,
    "excess_discount": -200000,
    "subtotal": 1538000,
    "training_levy": 7690,
    "sticker_fee": 6000,
    "vat": 278832,
    "stamp_duty": 35000,
    "total": 1865522,
    "premium": 1865522,
    "premiumString": "1865522",
    "message": "Click below to download your quote:\nNOT AVAILABLE",
    "downloadUrl": "NOT AVAILABLE"
  },
  "total_premium": 1865522,
  "message": "Click below to download your quote:\nNOT AVAILABLE",
  "downloadUrl": "NOT AVAILABLE"
}
```

## Field Mapping

### Required Fields

| Frontend Field | Backend Field | Type | Valid Values |
|---|---|---|---|
| Vehicle Value | `vehicle_value_ugx` | float | 10,000,000 - 100,000,000 UGX |
| Region | `car_usage_region` | string | "Within Uganda", "Within East Africa", "Outside East Africa" |
| First Registration | `first_time_registration` | string | "Yes", "No" |
| Car Alarm | `car_alarm_installed` | string | "Yes", "No" |
| Tracking System | `tracking_system_installed` | string | "Yes", "No" |
| Excess | `excess_choice` | list | ["excess_1"], ["excess_2"], ["excess_3"] |
| Year | `year_of_manufacture` | int | 1980 - 2026 |
| Region Code | `car_usage_region` | string | (mapped to region_bounds 1, 2, 3) |

### Optional Fields

| Field | Type | Purpose |
|---|---|---|
| `selected_benefits` | list | ["political_violence"], ["alternative_accommodation"], ["car_hire"] |
| `cover_start_date` | string | ISO date format (e.g., "2026-05-01") |
| Customer info | string | first_name, surname, email, vehicle_make, vehicle_model |

## Premium Breakdown

### Formula Components

1. **Base Premium** = Vehicle Value × 0.04 (4%)

2. **Discounts Applied:**
   - Car Alarm: -5% of base
   - Tracking System: -15% of base
   - Excess: -10% to -25% of base (based on selection)

3. **Regional Fees (added to base):**
   - Within East Africa: +20% of base
   - Outside East Africa: +30% of base
   - Within Uganda: No regional fee

4. **Add-ons (optional):**
   - Alternative Accommodation: 300,000 × 0.1 + levy (0.5%) + VAT (18%)
   - Car Hire: 100,000 × 0.1 + levy (0.5%) + VAT (18%)
   - Political Violence: 0.25% of base

5. **Subtotal** = Base + All Adjustments

6. **Taxes & Fees:**
   - Training Levy: 0.5% of subtotal
   - Sticker Fee: 6,000 UGX (fixed)
   - VAT: 18% of (subtotal + training levy + sticker fee)
   - Stamp Duty: 35,000 UGX (fixed)

7. **Total Premium** = Stamp Duty + Subtotal + Training Levy + VAT + Sticker Fee

## Integration with React Frontend

```javascript
// Example fetch call from frontend
const response = await fetch("/api/v1/motor-private/calculate-quote", {
  method: "POST",
  headers: { 
    "Content-Type": "application/json",
    "Authorization": "Bearer YOUR_API_KEY"
  },
  body: JSON.stringify({
    user_id: customerPhone,
    data: formData
  })
});

const result = await response.json();

if (result.success) {
  console.log("Premium Calculated:", result.total_premium);
  console.log("Breakdown:", result.premium_breakdown);
  console.log("Download URL:", result.downloadUrl);
}
```

## Python Integration

```python
from src.integrations.clients.real_http.motor_private_calculator import calculate_motor_private_premium

session_data = {
    "vehicle_value_ugx": 50_000_000,
    "car_usage_region": "Within Uganda",
    "first_time_registration": "Yes",
    "car_alarm_installed": "No",
    "tracking_system_installed": "Yes",
    "selected_benefits": ["political_violence"],
    "excess_choice": ["excess_1"],
    # ... other fields
}

result = calculate_motor_private_premium(session_data)
total = result["total"]
breakdown = result
```

## Testing

Run the premium calculation tests:
```bash
pytest tests/test_motor_private_premium_calculation.py -v
```

17 test cases covering:
- Basic premium calculation
- Alarm discount (5%)
- Tracker discount (15%)
- Regional fee variations
- Excess discount options (10%, 15%, 25%)
- Add-on benefits (accommodation, car hire, PVT)
- Combined benefits
- VAT and tax calculations
- Min/max vehicle value enforcement

## API Compatibility

The calculator integrates seamlessly with:
- Motor Private guided flow (`/chat/start-guided`)
- Motor Private full form (`/forms/motor-private/full`)
- Premium service (`premium_service.calculate()`)

The `calculate_motor_private_premium()` function is called automatically when:
1. User submits Motor Private form data
2. Premium breakdown is displayed in step 4
3. Quote is created before payment

## Notes

- **Backward Compatibility**: Returns both `premium` and `total` fields
- **Graceful Failure**: PDF generation is optional; quote calculates even if API is unavailable
- **Request Library**: Conditionally imports `requests` only when needed
- **Validation**: Frontend validation at `/flow/validate-field` happens before premium calculation
- **Zero Minimum**: Non-negative subtotal enforced (no negative premiums)

## Future Enhancements

- [ ] Direct integration with Zoho CRM for real-time rates
- [ ] A/B testing framework for premium adjustments
- [ ] Loyalty discounts
- [ ] Bulk policy discounts
- [ ] Seasonal pricing adjustments
