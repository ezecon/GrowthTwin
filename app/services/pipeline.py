"""Orchestrates the loop: extract -> ask (<= N rounds) -> decide -> evidence -> narrative -> validate."""
import hashlib
import json
import uuid
from datetime import datetime, timezone

from ..core.config import get_settings
from ..core.store import get_store
from . import compare, decision, llm, prompt_builder, rag, report, slot_manager, validator
from .extractor import extract

DATA_VERSION = "v2"  # bump when CSV data/rules change, invalidates report cache


def new_state(owner: str) -> dict:
    return {"owner": owner, "slots": {}, "asked": [], "round": 0, "status": "collecting",
            "report": None, "review_status": "none", "review_note": None,
            "created_at": datetime.now(timezone.utc).isoformat()}


def _cache_key(slots: dict) -> str:
    payload = json.dumps({k: [v["value"], v["source"]] for k, v in sorted(slots.items())}, ensure_ascii=False)
    return hashlib.sha256(f"{DATA_VERSION}|{payload}".encode()).hexdigest()


async def _build_report(slots: dict) -> dict:
    cfg = get_settings()
    conf = slot_manager.confidence(slots)
    dec = decision.decide(slots, conf, cfg)

    evidence: list[dict] = []
    focus = dec["target"] or dec["best"]
    if focus:
        reasons = " ".join(focus["reasons_bn"][:2])
        evidence = await rag.retrieve(f"{focus['name_bn']} চাষ {reasons}", crop_id=focus["crop_id"])

    cmp = compare.compare(slots, dec, conf, cfg)
    facts = report.facts(slots, dec, evidence, cmp)
    narrative, source = None, "template"
    if llm.available():
        text = await llm.chat(prompt_builder.build_messages(facts))
        ok, _why = validator.validate(text or "", facts, dec["best"]["name_bn"] if dec["best"] else None)
        if ok:
            narrative, source = text, "llm"
    if narrative is None:
        narrative = report.template_narrative(slots, dec, evidence, cmp)

    return {
        "summary": {"headline_bn": report.headline(dec), "rating": (dec["target"] or dec["best"] or {}).get("rating", "no"),
                    "confidence": conf, "review_recommended": dec["review_recommended"]},
        "inputs": report.inputs_view(slots),
        "target": dec["target"], "alternatives": dec["alternatives"], "comparison": cmp, "evidence": evidence,
        "narrative_bn": narrative, "narrative_source": source,
    }


async def analyze(session_id: str | None, prompt: str | None, answers: dict | None,
                  sensors: dict | None, owner: str, state: dict | None) -> tuple[str, dict, dict | None, list | None]:
    """Returns (session_id, state, report|None, questions|None)."""
    cfg, store = get_settings(), get_store()
    sid = session_id or uuid.uuid4().hex
    state = state or new_state(owner)

    if state["status"] == "done" and not (prompt or answers or sensors):
        return sid, state, state["report"], None

    if prompt:  # a fresh prompt always starts a fresh analysis
        state = new_state(owner)
        for k, v in (await extract(prompt)).items():
            slot_manager.set_slot(state["slots"], k, v, "user")
    for k, v in (answers or {}).items():
        if k in slot_manager.SLOT_LABEL_BN:
            slot_manager.set_slot(state["slots"], k, v, "user")
            if k not in state["asked"]:
                state["asked"].append(k)
    for k, v in (sensors or {}).items():
        if k in slot_manager.SLOT_LABEL_BN:
            slot_manager.set_slot(state["slots"], k, v, "sensor")

    missing = slot_manager.missing_required(state["slots"], state["asked"])
    if missing and state["round"] < cfg.max_followup_rounds:
        ask = missing[: cfg.max_questions_per_round]
        state["round"] += 1
        state["asked"] += ask
        state["status"] = "need_info"
        return sid, state, None, slot_manager.build_questions(ask)

    final = slot_manager.apply_defaults(state["slots"])
    key = _cache_key(final)
    cached = await store.get_cached(key)
    rep = cached or await _build_report(final)
    if not cached:
        await store.put_cached(key, rep)
    rep = {**rep, "cached": bool(cached)}
    state.update(slots=final, status="done", report=rep)
    return sid, state, rep, None
