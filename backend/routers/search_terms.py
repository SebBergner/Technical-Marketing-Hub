"""Admin -> Search terms (services/search_terms.py; Liwei, 2026-11-13).

Anyone with View Admin sees the groups and can try a query; Maintain content
adds, changes and removes them. Every change is in the Admin log
(category "Search terms").
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.access import Perm
from backend.admin_auth import require_perm
from backend.services import search_terms as st

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/search-terms", tags=["admin"])
VIEW_ADMIN = Depends(require_perm(Perm.VIEW_ADMIN))
MAINTAIN = require_perm(Perm.MAINTAIN)


class GroupIn(BaseModel):
    terms: list[str] = Field(max_length=st.MAX_TERMS * 2)
    note: str | None = Field(default=None, max_length=st.MAX_NOTE * 2)


@router.get("", dependencies=[VIEW_ADMIN])
def list_groups():
    data = st.load()
    return {"groups": data["groups"], "saved": data["saved"],
            "changed_at": data.get("changed_at"), "changed_by": data.get("changed_by"),
            "limits": {"terms": st.MAX_TERMS, "length": st.MAX_LEN}}


@router.get("/try", dependencies=[VIEW_ADMIN])
def try_query(q: str = ""):
    """What a search for `q` also looks for."""
    return {"query": q, "also": list(st.variants(q[:200]))[1:]}


@router.post("")
def add_group(body: GroupIn, actor: str = Depends(MAINTAIN)):
    try:
        group = st.add(body.terms, body.note, actor)
    except st.TermsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    log.info("search terms added by %s: %s", actor, " = ".join(group["terms"]))
    return group


@router.put("/{group_id}")
def change_group(group_id: str, body: GroupIn, actor: str = Depends(MAINTAIN)):
    try:
        return st.update(group_id, body.terms, body.note, actor)
    except st.TermsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail="No such group; it may have been removed.")


@router.delete("/{group_id}")
def remove_group(group_id: str, actor: str = Depends(MAINTAIN)):
    try:
        st.remove(group_id, actor)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such group; it may have been removed.")
    return {"removed": group_id}
