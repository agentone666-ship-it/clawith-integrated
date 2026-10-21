"""Authenticated recruitment transport; the HR service owns all dossier mutations."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.recruitment import (
    Catalog,
    ContinueInterview,
    RecruitmentOut,
    Review,
    Revision,
    SaveResume,
    StartInterview,
    Talk,
)
from app.services import recruitment as hr
from app.services import recruitment_interviews as interviews

router = APIRouter(prefix="/recruitment", tags=["recruitment"])
Caller = Annotated[User, Depends(get_current_user)]
Database = Annotated[AsyncSession, Depends(get_db)]


@router.get("/catalog", response_model=Catalog)
async def catalog(user: Caller, db: Database):
    return await hr.catalog(db, user)


@router.get("", response_model=list[RecruitmentOut])
async def list_dossiers(user: Caller, db: Database, offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
    return await hr.list_dossiers(db, user, offset, limit)


@router.post("", response_model=RecruitmentOut, status_code=201)
async def create(user: Caller, db: Database):
    return await hr.create_dossier(db, user)


@router.get("/{dossier_id}", response_model=RecruitmentOut)
async def get(dossier_id: uuid.UUID, user: Caller, db: Database):
    return await hr.get_dossier(db, user, dossier_id)


@router.post("/{dossier_id}/talk", response_model=RecruitmentOut)
async def talk(dossier_id: uuid.UUID, data: Talk, user: Caller, db: Database):
    return await hr.talk(db, user, dossier_id, data)


@router.put("/{dossier_id}/resume", response_model=RecruitmentOut)
async def save_resume(dossier_id: uuid.UUID, data: SaveResume, user: Caller, db: Database):
    return await hr.save_resume(db, user, dossier_id, data.revision, data.resume)


@router.post("/{dossier_id}/hire", response_model=RecruitmentOut)
async def hire(dossier_id: uuid.UUID, data: Revision, user: Caller, db: Database):
    return await hr.hire(db, user, dossier_id, data.revision)


@router.post("/{dossier_id}/interviews", response_model=RecruitmentOut)
async def start(dossier_id: uuid.UUID, data: StartInterview, user: Caller, db: Database):
    return await interviews.start(db, user, dossier_id, data)


@router.get("/{dossier_id}/interviews/{interview_id}")
async def detail(dossier_id: uuid.UUID, interview_id: uuid.UUID, user: Caller, db: Database):
    return await interviews.detail(db, user, dossier_id, interview_id)


@router.post("/{dossier_id}/interviews/{interview_id}/review", response_model=RecruitmentOut)
async def review(dossier_id: uuid.UUID, interview_id: uuid.UUID, data: Review, user: Caller, db: Database):
    return await interviews.review(db, user, dossier_id, interview_id, data)


@router.post("/{dossier_id}/interviews/{interview_id}/continue", response_model=RecruitmentOut)
async def continue_interview(dossier_id: uuid.UUID, interview_id: uuid.UUID, data: ContinueInterview, user: Caller, db: Database):
    return await interviews.continue_interview(db, user, dossier_id, interview_id, data)


@router.post("/{dossier_id}/interviews/{interview_id}/cancel", response_model=RecruitmentOut)
async def cancel(dossier_id: uuid.UUID, interview_id: uuid.UUID, data: Revision, user: Caller, db: Database):
    return await interviews.cancel(db, user, dossier_id, interview_id, data.revision)
