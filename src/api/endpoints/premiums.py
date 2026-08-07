"""Premium calculation endpoints (policy selected: mock vs real)."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.integrations.policy.premium import premium_service

api = APIRouter()
premiums_api = api


class PremiumCalculateRequest(BaseModel):
    product_key: str = Field(..., description="Product identifier, e.g. personal_accident")
    data: Dict[str, Any] = Field(default_factory=dict, description="Premium calculation payload")


@api.post("/calculate", tags=["Premiums"])
async def calculate_premium(request: PremiumCalculateRequest):
    try:
        return await premium_service.calculate(request.product_key, request.data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
