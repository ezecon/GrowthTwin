"""Model registry: crop id -> image classifier. Optional and ADVISORY ONLY.

Supported model files:
- app/models/<crop_id>/model.pth (PyTorch ViT-B/16 checkpoint)
- app/models/<crop_id>/model.onnx + labels.json (ONNX)

predict() always returns no_model, unknown, or ok. Model failures must never
break the daily loop. A .pth checkpoint must contain model_state_dict and
class_names as produced by the user's ViT-B/16 training script.
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
    return (
        b[:3] == b"\\xff\\xd8\\xff"
        or b[:8] == b"\\x89PNG\\r\\n\\x1a\\n"
        or (b[:4] == b"RIFF" and b[8:12] == b"WEBP")
    )


def _load_onnx(crop_id: str, folder: Path):
    import io
    import numpy as np
    import onnxruntime as ort
    from PIL import Image

    meta = json.loads((folder / "labels.json").read_text(encoding="utf-8"))
    labels, bn_map = meta["labels"], meta.get("labels_bn", {})
    healthy_label = meta.get("healthy_label", "healthy")
    size = int(meta.get("input_size", 224))
    sess = ort.InferenceSession(
        str(folder / "model.onnx"), providers=["CPUExecutionProvider"]
    )
    inp = sess.get_inputs()[0].name
    mean = np.array([0.485, 0.456, 0.406], dtype="float32")
    std = np.array([0.229, 0.224, 0.225], dtype="float32")

    def fn(image: bytes):
        img = Image.open(io.BytesIO(image)).convert("RGB").resize((size, size))
        x = ((np.asarray(img, dtype="float32") / 255.0 - mean) / std)
        x = x.transpose(2, 0, 1)[None]
        logits = sess.run(None, {inp: x})[0][0]
        e = np.exp(logits - logits.max())
        p = e / e.sum()
        i = int(p.argmax())
        label = labels[i]
        return label, bn_map.get(label, label), float(p[i]), label.lower() == healthy_label.lower()

    return fn


def _load_pth(crop_id: str, folder: Path):
    """Load a checkpoint saved by the supplied torchvision ViT-B/16 training code."""
    import io
    import torch
    from PIL import Image
    from torch import nn
    from torchvision import models, transforms

    checkpoint = torch.load(
        folder / "model.pth",
        map_location="cpu",
        weights_only=True,
    )
    if not isinstance(checkpoint, dict) or "model_state_dict" not in checkpoint:
        raise ValueError("Expected checkpoint with 'model_state_dict'")

    class_names = checkpoint.get("class_names")
    if not isinstance(class_names, (list, tuple)) or not class_names:
        raise ValueError("Checkpoint is missing a valid 'class_names' list")

    num_classes = int(checkpoint.get("num_classes", len(class_names)))
    if num_classes != len(class_names):
        raise ValueError("num_classes does not match class_names length")

    model = models.vit_b_16(weights=None)
    model.heads.head = nn.Linear(model.heads.head.in_features, num_classes)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    size = int(checkpoint.get("image_size", 224))
    mean = checkpoint.get("mean", [0.485, 0.456, 0.406])
    std = checkpoint.get("std", [0.229, 0.224, 0.225])
    transform = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(size),
        transforms.ToTensor(),
        transforms.Normalize(mean=mean, std=std),
    ])

    meta_path = folder / "labels.json"
    meta = (
        json.loads(meta_path.read_text(encoding="utf-8"))
        if meta_path.exists() else {}
    )
    bn_map = meta.get("labels_bn", {})
    healthy_label = str(meta.get("healthy_label", "healthy")).strip().lower()

    def fn(image: bytes):
        img = Image.open(io.BytesIO(image)).convert("RGB")
        x = transform(img).unsqueeze(0)
        with torch.inference_mode():
            logits = model(x)
            probabilities = torch.softmax(logits, dim=1)[0]

        idx = int(probabilities.argmax().item())
        label = str(class_names[idx])
        score = float(probabilities[idx].item())
        # Exact match by default; configure healthy_label in labels.json if needed.
        is_healthy = label.strip().lower() == healthy_label
        return label, bn_map.get(label, label), score, is_healthy

    return fn


def load_models() -> list[str]:
    """Scan app/models/<crop_id> once; a broken model only skips its crop."""
    global _LOADED
    if _LOADED:
        return list(_REGISTRY)

    # Mark loaded after scanning so a missing models directory can be retried.
    if not MODELS_DIR.exists():
        return list(_REGISTRY)

    for folder in MODELS_DIR.iterdir():
        if not folder.is_dir():
            continue
        try:
            pth_path = folder / "model.pth"
            onnx_path = folder / "model.onnx"
            labels_path = folder / "labels.json"

            # Prefer .pth when both formats exist in the same crop folder.
            if pth_path.is_file():
                _REGISTRY[folder.name] = _load_pth(folder.name, folder)
            elif onnx_path.is_file() and labels_path.is_file():
                _REGISTRY[folder.name] = _load_onnx(folder.name, folder)
        except Exception as e:  # noqa: BLE001
            log.warning("disease model %s not loaded: %s", folder.name, e)

    _LOADED = True
    return list(_REGISTRY)


def available(crop_id: str) -> bool:
    load_models()
    return crop_id in _REGISTRY


def predict(crop_id: str, image: bytes) -> dict:
    load_models()
    fn = _REGISTRY.get(crop_id)
    if fn is None:
        return {"status": "no_model"}

    # Keep malformed/oversized uploads from reaching model inference.
    if not isinstance(image, (bytes, bytearray)) or not image:
        return {"status": "unknown", "score": None}
    if len(image) > MAX_IMAGE_BYTES or not looks_like_image(image):
        return {"status": "unknown", "score": None}

    s = get_settings()
    try:
        label, label_bn, score, healthy = fn(bytes(image))
        score = float(score)
        if not 0.0 <= score <= 1.0:
            raise ValueError("Model score must be between 0 and 1")
    except Exception as e:  # noqa: BLE001
        log.warning("disease predict failed for %s: %s", crop_id, e)
        return {"status": "unknown", "score": None}

    if score < s.disease_min_score:
        return {"status": "unknown", "score": round(score, 3)}

    return {
        "status": "ok",
        "label": label,
        "label_bn": label_bn,
        "score": round(score, 3),
        "healthy": bool(healthy),
        "needs_review": (not healthy) and score < s.disease_review_score,
    }
