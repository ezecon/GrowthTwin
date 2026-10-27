from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import User, current_user
from ..core.store import get_store
from ..core.twin_store import get_twin_store
from ..data import crops, name_bn
from ..services import pipeline

router = APIRouter(prefix="/advisor", tags=["advisor"])


class AnalyzeRequest(BaseModel):
    session_id: str | None = Field(None, max_length=64)
    prompt: str | None = Field(None, max_length=1500)
    answers: dict[str, Any] | None = None
    sensors: dict[str, Any] | None = None  # e.g. {"ph": 6.1} from the IoT device


class AnalyzeResponse(BaseModel):
    session_id: str
    status: Literal["need_info", "done"]
    round: int
    questions: list[dict] | None = None
    report: dict | None = None


def _check_owner(state: dict, user: User):
    if state and state["owner"] != user.id and user.role not in ("expert", "admin"):
        raise HTTPException(403, "Not your session")


async def _with_own_yields(rep: dict | None, user_id: str) -> dict | None:
    """Section 2 -> Section 1: attach THIS farmer's real harvest yields for the crops in the report.
    Done per request (never inside the shared report cache, which is not per-user)."""
    if not rep:
        return rep
    ids = [x for x in ((rep.get("target") or {}).get("crop_id"), (rep.get("comparison") or {}).get("current", {}).get("crop_id")) if x]
    if not ids:
        return rep
    by: dict[str, list[float]] = {}
    for r in await get_twin_store().list_harvests(user_id):
        if r.get("outcome", "harvested") != "harvested":
            continue
        by.setdefault(r["crop_id"], []).append(float(r["yield_kg_per_decimal"]))
    cs, out = crops(), []
    for cid in dict.fromkeys(ids):
        v = by.get(cid)
        if v and cid in cs:
            c = cs[cid]
            out.append({"crop_id": cid, "name_bn": name_bn(cid), "harvests": len(v),
                        "avg": round(sum(v) / len(v), 1), "best": round(max(v), 1), "worst": round(min(v), 1),
                        "table_bad": c.y[0], "table_base": c.y[1], "table_good": c.y[2]})
    return {**rep, "own_yields": out}


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest, user: User = Depends(current_user)):
    if not (req.prompt or req.answers or req.sensors or req.session_id):
        raise HTTPException(422, "prompt or answers required")
    store = get_store()
    state = await store.get_session(req.session_id) if req.session_id else None
    if req.session_id and state is None and not req.prompt:
        raise HTTPException(404, "Unknown session; send a prompt to start")
    _check_owner(state, user)
    sid, state, rep, questions = await pipeline.analyze(
        req.session_id, req.prompt, req.answers, req.sensors, user.id, state
    )
    await store.save_session(sid, state)
    return AnalyzeResponse(session_id=sid, status="done" if rep else "need_info",
                           round=state["round"], questions=questions, report=await _with_own_yields(rep, state["owner"]))


@router.get("/report/{sid}")
async def get_report(sid: str, user: User = Depends(current_user)):
    state = await get_store().get_session(sid)
    if not state or not state.get("report"):
        raise HTTPException(404, "No report")
    _check_owner(state, user)
    return {"session_id": sid, "report": await _with_own_yields(state["report"], state["owner"]), "review_status": state["review_status"],
            "review_note": state.get("review_note")}


@router.post("/report/{sid}/request-review")
async def request_review(sid: str, user: User = Depends(current_user)):
    store = get_store()
    state = await store.get_session(sid)
    if not state or not state.get("report"):
        raise HTTPException(404, "No report")
    _check_owner(state, user)
    state["review_status"] = "pending"
    await store.save_session(sid, state)
    return {"session_id": sid, "review_status": "pending"}
