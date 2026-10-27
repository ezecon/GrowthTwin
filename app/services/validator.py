"""Reject LLM narratives that invent money figures or ignore the recommended crop."""
import re

from .lexicon import to_ascii_digits

NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _allowed_numbers(facts: dict) -> list[float]:
    nums: list[float] = []

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            nums.append(float(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            for m in NUM_RE.findall(to_ascii_digits(x)):
                try:
                    nums.append(float(m.replace(",", "")))
                except ValueError:
                    pass

    walk(facts)
    nums += [abs(n) for n in nums]
    return nums


def validate(text: str, facts: dict, best_name: str | None) -> tuple[bool, str]:
    if not text or len(text) < 40:
        return False, "empty"
    allowed = _allowed_numbers(facts)
    for m in NUM_RE.findall(to_ascii_digits(text)):
        try:
            n = float(m.replace(",", ""))
        except ValueError:
            continue
        if n >= 100 and not any(abs(n - a) <= max(1.0, 0.01 * a) for a in allowed):
            return False, f"unsupported number {n:g}"
    if best_name and best_name not in text:
        return False, "recommended crop not mentioned"
    return True, "ok"
