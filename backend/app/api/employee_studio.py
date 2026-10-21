"""Authenticated transport for user-owned employee job drafts."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.employee_studio import (
    BlueprintOut,
    BlueprintSave,
    EmployeeSpecification,
    GenerateSpecification,
    StudioCatalog,
    StudioReadiness,
)
from app.services import employee_studio

router = APIRouter(prefix="/employee-studio", tags=["employee-studio"])
CurrentUser = Annotated[User, Depends(get_current_user)]
Database = Annotated[AsyncSession, Depends(get_db)]


@router.get("/catalog", response_model=StudioCatalog)
async def catalog(user: CurrentUser, db: Database):
    return await employee_studio.capability_catalog(db, user)


@router.get("/blueprints", response_model=list[BlueprintOut])
async def list_blueprints(
    user: CurrentUser,
    db: Database,
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
):
    return await employee_studio.list_blueprints(db, user, offset, limit)


@router.post("/generate", response_model=EmployeeSpecification)
async def generate(
    data: GenerateSpecification,
    user: CurrentUser,
    db: Database,
):
    return await employee_studio.generate_specification(db, user, data)


@router.post("/blueprints", response_model=BlueprintOut, status_code=201)
async def create_blueprint(
    data: BlueprintSave,
    user: CurrentUser,
    db: Database,
):
    return await employee_studio.save_blueprint(db, user, data)


@router.get("/blueprints/{blueprint_id}", response_model=BlueprintOut)
async def get_blueprint(
    blueprint_id: uuid.UUID,
    user: CurrentUser,
    db: Database,
):
    return await employee_studio.get_blueprint(db, user, blueprint_id)


@router.put("/blueprints/{blueprint_id}", response_model=BlueprintOut)
async def update_blueprint(
    blueprint_id: uuid.UUID,
    data: BlueprintSave,
    user: CurrentUser,
    db: Database,
):
    return await employee_studio.save_blueprint(db, user, data, blueprint_id)


@router.post("/blueprints/{blueprint_id}/check", response_model=StudioReadiness)
async def check_blueprint(
    blueprint_id: uuid.UUID,
    user: CurrentUser,
    db: Database,
):
    row = await employee_studio.get_blueprint(db, user, blueprint_id)
    return employee_studio.check_readiness(EmployeeSpecification.model_validate(row.specification))
