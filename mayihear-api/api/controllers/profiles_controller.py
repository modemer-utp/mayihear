import uuid
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from infrastructure.database import (
    create_profile, update_profile, delete_profile, get_profile_by_id, list_profiles
)

router = APIRouter(prefix="/profiles", tags=["profiles"])


class ProfileData(BaseModel):
    id: Optional[str] = None
    name: str
    track: Optional[str] = None
    context_for_insights: Optional[str] = None
    acta_template: Optional[str] = None


@router.get("")
def get_all_profiles():
    return list_profiles()


@router.get("/export")
def export_profiles():
    return list_profiles()


@router.post("/import")
def import_profiles(profiles: List[ProfileData]):
    for p in profiles:
        if not p.id:
            p.id = str(uuid.uuid4())[:8]
        existing = get_profile_by_id(p.id)
        if existing:
            update_profile(p.id, p.name, p.track or '', p.context_for_insights or '', p.acta_template or '')
        else:
            create_profile(p.id, p.name, p.track or '', p.context_for_insights or '', p.acta_template or '')
    return {"ok": True, "imported": len(profiles)}


@router.post("")
def upsert_profile(data: ProfileData):
    if data.id:
        update_profile(data.id, data.name, data.track or '', data.context_for_insights or '', data.acta_template or '')
        return {"ok": True, "id": data.id}
    profile_id = str(uuid.uuid4())[:8]
    create_profile(profile_id, data.name, data.track or '', data.context_for_insights or '', data.acta_template or '')
    return {"ok": True, "id": profile_id}


@router.delete("/{profile_id}")
def remove_profile(profile_id: str):
    delete_profile(profile_id)
    return {"ok": True}
