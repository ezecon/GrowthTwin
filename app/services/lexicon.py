"""Bengali/English text helpers: digit normalisation and crop-alias lookup."""
import re

BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
WORD_NUM = {"এক": 1, "দুই": 2, "তিন": 3, "চার": 4, "পাঁচ": 5, "ছয়": 6, "সাত": 7, "আট": 8, "নয়": 9, "দশ": 10}

ALIASES = {
    "boro": ["বোরো ধান", "বোরো", "boro rice", "boro"],
    "aman": ["আমন ধান", "আমন", "aman"],
    "aus": ["আউশ ধান", "আউশ", "aus"],
    "rice": ["ধান", "চাল", "rice", "paddy"],
    "wheat": ["গম", "wheat"],
    "maize": ["ভুট্টা", "ভূট্টা", "maize", "corn"],
    "potato": ["আলু", "potato"],
    "tomato": ["টমেটো", "tomato"],
    "mustard": ["সরিষা", "mustard"],
    "lentil": ["মসুর ডাল", "মসুর", "মশুর", "lentil"],
    "jute": ["পাট", "jute"],
}
_FLAT = sorted(((a, cid) for cid, al in ALIASES.items() for a in al), key=lambda x: -len(x[0]))


def normalize(text: str) -> str:
    t = text.translate(BN_DIGITS)
    pat = "(" + "|".join(WORD_NUM) + r")\s+(?=বিঘা|শতাংশ|শতক|একর|বছর)"
    return re.sub(pat, lambda m: str(WORD_NUM[m.group(1)]) + " ", t)


def to_ascii_digits(text: str) -> str:
    return text.translate(BN_DIGITS)


def find_crops(text: str) -> list[str]:
    """Crop ids mentioned in text, in order of appearance (longest alias wins)."""
    t = text.lower()
    hits: list[tuple[int, str]] = []
    for alias, cid in _FLAT:
        a = alias.lower()
        start = 0
        while (i := t.find(a, start)) != -1:
            hits.append((i, cid))
            t = t[:i] + " " * len(a) + t[i + len(a):]
            start = i + len(a)
    hits.sort()
    seen, out = set(), []
    for _, cid in hits:
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def bn_num(n: float, decimals: int = 0) -> str:
    s = f"{n:,.{decimals}f}"
    return s.translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))
