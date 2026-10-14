"""Model registry: crop id -> image classifier. Optional and ADVISORY ONLY.

predict() always returns one of:
  {"status": "no_model"}                                            no model for this crop
  {"status": "unknown", "score": s}                                 model not confident enough (< disease_min_score)
  {"status": "ok", "label", "label_bn", "score", "healthy", "needs_review"}
Any failure becomes "unknown"/"no_model": a broken model must never break the daily loop.
Plug in a model with register(crop_id, fn) where fn(image_bytes) -> (label, label_bn, score, healthy),
or drop an ONNX model in app/models/<crop_id>/ (see app/models/README.md).
"""
import json
import logging
from pathlib import Path
from typing import Callable

from ..core.config import get_settings

log = logging.getLogger("growthtwin.disease")
MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
MAX_IMAGE_BYTES = 2_000_000
_REGISTRY: dict[str, Callable[[bytes], tuple]] = {}
_LOADED = False


def register(crop_id: str, fn: Callable[[bytes], tuple]) -> None:
    _REGISTRY[crop_id] = fn


def unregister(crop_id: str) -> None:
    _REGISTRY.pop(crop_id, None)


def looks_like_image(b: bytes) -> bool:
    return b[:3] == b"\xff\xd8\xff" or b[:8] == b"\x89PNG\r\n\x1a\n" or (b[:4] == b"RIFF" and b[8:12] == b"WEBP")


def _load_onnx(crop_id: str, folder: Path):
    import numpy as np                      # lazy: only needed when a model folder exists
    import onnxruntime as ort
    from PIL import Image
    import io
    meta = json.loads((folder / "labels.json").read_text(encoding="utf-8"))
    labels, bn_map = meta["labels"], meta.get("labels_bn", {})
    healthy_label, size = meta.get("healthy_label", "healthy"), int(meta.get("input_size", 224))
    sess = ort.InferenceSession(str(folder / "model.onnx"), providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name
    mean, std = np.array([0.485, 0.456, 0.406], "float32"), np.array([0.229, 0.224, 0.225], "float32")

    def fn(image: bytes):
        img = Image.open(io.BytesIO(image)).convert("RGB").resize((size, size))
        x = ((np.asarray(img, "float32") / 255.0 - mean) / std).transpose(2, 0, 1)[None]
        logits = sess.run(None, {inp: x})[0][0]
        e = np.exp(logits - logits.max())
        p = e / e.sum()
        i = int(p.argmax())
        return labels[i], bn_map.get(labels[i]), float(p[i]), labels[i] == healthy_label

    return fn


def load_models() -> list[str]:
    """Scan app/models/<crop>/ once. Missing libs or bad files only skip that crop."""
    global _LOADED
    if _LOADED:
        return list(_REGISTRY)
    _LOADED = True
    if MODELS_DIR.exists():
        for folder in MODELS_DIR.iterdir():
            if folder.is_dir() and (folder / "model.onnx").exists() and (folder / "labels.json").exists():
                try:
                    _REGISTRY[folder.name] = _load_onnx(folder.name, folder)
                except Exception as e:      # noqa: BLE001
                    log.warning("disease model %s not loaded: %s", folder.name, e)
    return list(_REGISTRY)


def available(crop_id: str) -> bool:
    load_models()
    return crop_id in _REGISTRY


def predict(crop_id: str, image: bytes) -> dict:
    load_models()
    fn = _REGISTRY.get(crop_id)
    if fn is None:
        return {"status": "no_model"}
    s = get_settings()
    try:
        label, label_bn, score, healthy = fn(image)
    except Exception as e:                  # noqa: BLE001
        log.warning("disease predict failed for %s: %s", crop_id, e)
        return {"status": "unknown", "score": None}
    if score < s.disease_min_score:
        return {"status": "unknown", "score": round(score, 3)}
    return {"status": "ok", "label": label, "label_bn": label_bn, "score": round(score, 3), "healthy": bool(healthy),
            "needs_review": (not healthy) and score < s.disease_review_score}
