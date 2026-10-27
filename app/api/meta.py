from fastapi import APIRouter

from ..core.store import get_store
from ..data import SEASONS_BN, crops

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health():
    return {"ok": True, "store": get_store().kind}


@router.get("/meta/crops")
async def meta_crops():
    return [{"id": c.id, "name_bn": c.name_bn, "name_en": c.name_en,
             "seasons": [{"id": s, "name_bn": SEASONS_BN[s]} for s in c.seasons]} for c in crops().values()]
