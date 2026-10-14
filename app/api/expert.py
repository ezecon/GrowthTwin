from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import User, require_role
from ..core.store import get_store

router = APIRouter(prefix="/expert", tags=["expert"])


class ReviewIn(BaseModel):
    verdict: Literal["agree", "adjust", "disagree"]
    note: str = Field("", max_length=2000)


@router.get("/queue")
async def queue(user: User = Depends(require_role("expert", "admin"))):
    rows = await get_store().review_queue()
    return [{"session_id": r["session_id"], "headline_bn": r["report"]["summary"]["headline_bn"],
             "confidence": r["report"]["summary"]["confidence"], "inputs": r["report"]["inputs"]}
            for r in rows if r.get("report")]


@router.post("/review/{sid}")
async def review(sid: str, body: ReviewIn, user: User = Depends(require_role("expert", "admin"))):
    store = get_store()
    state = await store.get_session(sid)
    if not state or not state.get("report"):
        raise HTTPException(404, "No report")
    state["review_status"] = "reviewed"
    state["review_note"] = {"verdict": body.verdict, "note": body.note, "by": user.id}
    await store.save_session(sid, state)
    return {"session_id": sid, "review_status": "reviewed"}
