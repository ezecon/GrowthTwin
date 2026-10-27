"""SolarFlow AI planning endpoint. Advisory only; it never directly operates a pump."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from ..core.auth import User, current_user
from ..services.solarflow_ai import SolarFlowInput, recommend

router = APIRouter(prefix="/solarflow", tags=["solarflow-ai"])

class PlanIn(BaseModel):
    soil_moisture_pct: float = Field(24, ge=0, le=100)
    target_moisture_pct: float = Field(35, ge=1, le=100)
    area_m2: float = Field(100, gt=0, le=100000)
    root_zone_available_mm: float = Field(60, gt=0, le=300)
    daily_crop_water_mm: float = Field(4, ge=0, le=30)
    forecast_rain_mm: float = Field(8, ge=0, le=500)
    rain_probability: float = Field(.6, ge=0, le=1)
    solar_power_w: float = Field(80, ge=0, le=100000)
    pump_power_w: float = Field(60, gt=0, le=100000)
    battery_capacity_wh: float = Field(240, gt=0, le=1000000)
    battery_pct: float = Field(42, ge=0, le=100)
    battery_reserve_pct: float = Field(25, ge=0, le=95)
    tank_water_l: float = Field(500, ge=0, le=10000000)
    pump_flow_l_min: float = Field(5, gt=0, le=100000)
    horizon_hours: float = Field(6, ge=1, le=24)

@router.post("/plan")
async def plan(body: PlanIn, user: User = Depends(current_user)):
    # Auth is intentionally consistent with the rest of GrowthTwin; no actuator command is issued.
    result = recommend(SolarFlowInput(**body.model_dump()))
    result["advisory_only"] = True
    result["user_role"] = user.role
    return result
