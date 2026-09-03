from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.analytics import RecoveryTotalsResponse, InterventionStatsResponse, BaselineComparisonResponse
from app.services import analytics_service

router = APIRouter()

@router.get("/recovery", response_model=RecoveryTotalsResponse)
def get_recovery_totals(
    start_date: Optional[datetime] = Query(None, description="Filter by case creation start date (ISO 8601)"),
    end_date: Optional[datetime] = Query(None, description="Filter by case creation end date (ISO 8601)"),
    case_type: Optional[str] = Query(None, description="Filter by case type"),
    db: Session = Depends(get_db),
):
    """
    Get aggregated ledger totals for recovered revenue and costs.
    """
    return analytics_service.get_recovery_totals(
        db=db,
        start_date=start_date,
        end_date=end_date,
        case_type=case_type,
    )

@router.get("/interventions", response_model=InterventionStatsResponse)
def get_intervention_stats(
    start_date: Optional[datetime] = Query(None, description="Filter by case creation start date (ISO 8601)"),
    end_date: Optional[datetime] = Query(None, description="Filter by case creation end date (ISO 8601)"),
    case_type: Optional[str] = Query(None, description="Filter by case type"),
    db: Session = Depends(get_db),
):
    """
    Get statistics grouped by intervention type.
    """
    return analytics_service.get_intervention_stats(
        db=db,
        start_date=start_date,
        end_date=end_date,
        case_type=case_type,
    )

@router.get("/baseline", response_model=BaselineComparisonResponse)
def get_baseline_comparison(
    seed: Optional[int] = Query(None, description="Optional seed to filter the simulation run"),
    db: Session = Depends(get_db),
):
    """
    Get the comparison metrics between the naive baseline strategy and the REVIVE agent strategy.
    """
    return analytics_service.get_baseline_comparison(db=db, seed=seed)
