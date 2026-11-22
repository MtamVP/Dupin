"""Vietnamese & multilingual text normalization utilities for OSINT matching."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Common Vietnamese location and university abbreviations for entity resolution
VN_ABBREVIATIONS: dict[str, str] = {
    "tphcm": "thanh pho ho chi minh",
    "tp hcm": "thanh pho ho chi minh",
    "tp.hcm": "thanh pho ho chi minh",
    "hcm": "ho chi minh",
    "hcmc": "ho chi minh",
    "sai gon": "ho chi minh",
    "saigon": "ho chi minh",
    "hn": "ha noi",
    "dh": "dai hoc",
    "dhbk": "dai hoc bach khoa",
    "hust": "dai hoc bach khoa ha noi",
    "hcmut": "dai hoc bach khoa thanh pho ho chi minh",
    "uit": "dai hoc cong nghe thong tin",
    "ptit": "hoc vien cong nghe buu chinh vien thong",
    "fpt": "dai hoc fpt",
    "neu": "dai hoc kinh te quoc dan",
    "ueh": "dai hoc kinh te thanh pho ho chi minh",
    "ussh": "dai hoc khoa hoc xa hoi va nhan van",
    "hcmussh": "dai hoc khoa hoc xa hoi va nhan van",
    "hcmus": "dai hoc khoa hoc tu nhien",
    "hcmute": "dai hoc su pham ky thuat",
    "uel": "dai hoc kinh te luat",
    "ump": "dai hoc y duoc thanh pho ho chi minh",
    "ftu": "dai hoc ngoai thuong",
    "uet": "dai hoc cong nghe",
    "vnu": "dai hoc quoc gia",
    "thpt": "trung hoc pho thong",
    "thcs": "trung hoc co so",
}


def strip_vietnamese_accents(text: str) -> str:
    """Remove Vietnamese diacritics and convert đ/Đ to d/D."""
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", stripped)


def normalize_text(text: str) -> str:
    """Lowercase, strip accents, remove punctuation, and collapse whitespace."""
    no_accents = strip_vietnamese_accents(text).lower()
    cleaned = re.sub(r"[^\w\s]", " ", no_accents)
    return re.sub(r"\s+", " ", cleaned).strip()


def phonetic_vietnamese_key(text: str) -> str:
    """Produce a phonetic/typo-tolerant key for Vietnamese names (i/y, tr/ch, s/x, gi/r/d)."""
    norm = normalize_text(text)
    if not norm:
        return ""
    tokens: list[str] = []
    for tok in norm.split():
        # Common Vietnamese initial consonant confusions
        if tok.startswith("tr"):
            tok = "ch" + tok[2:]
        elif tok.startswith("gi"):
            tok = "d" + tok[2:]
        elif tok.startswith("r"):
            tok = "d" + tok[1:]
        elif tok.startswith("s"):
            tok = "x" + tok[1:]
        # Standardize i/y vowel interchangeability (e.g. Qui/Quy, Thuy/Thui, My/Mi)
        tok = tok.replace("y", "i")
        tokens.append(tok)
    return " ".join(tokens)


def normalize_org_or_location(text: str) -> str:
    """Normalize text and expand common Vietnamese location/school abbreviations."""
    norm = normalize_text(text)
    if norm.startswith("truong "):
        norm = norm[len("truong ") :].strip()
    if norm in VN_ABBREVIATIONS:
        return VN_ABBREVIATIONS[norm]
    tokens = norm.split()
    expanded = [VN_ABBREVIATIONS.get(tok, tok) for tok in tokens]
    return " ".join(expanded)


def generate_name_variants(full_name: str) -> list[str]:
    """Generate realistic OSINT name and handle variants from a Vietnamese or English name."""
    raw = re.sub(r"\s+", " ", full_name).strip()
    if not raw:
        return []

    no_accent = strip_vietnamese_accents(raw)
    lower_no_accent = normalize_text(raw)
    tokens = lower_no_accent.split()

    variants: list[str] = [raw, no_accent, lower_no_accent]

    if len(tokens) >= 2:
        joined = "".join(tokens)
        dotted = ".".join(tokens)
        underscored = "_".join(tokens)
        first_last = f"{tokens[-1]} {tokens[0]}"
        given_middle = " ".join(tokens[1:])
        initials = "".join(t[0] for t in tokens)
        variants.extend([joined, dotted, underscored, first_last, given_middle, initials])

    seen: set[str] = set()
    unique: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            unique.append(v)
    return unique


def jaro_winkler_similarity(s1: str, s2: str, prefix_weight: float = 0.1) -> float:
    """Compute Jaro-Winkler similarity in [0.0, 1.0] (gold standard for name/handle matching)."""
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    transpositions = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    jaro = (
        (matches / len1)
        + (matches / len2)
        + ((matches - transpositions / 2.0) / matches)
    ) / 3.0

    # Winkler prefix bonus (up to 4 chars)
    prefix = 0
    for c1, c2 in zip(s1[:4], s2[:4]):
        if c1 == c2:
            prefix += 1
        else:
            break

    return round(min(1.0, jaro + prefix * prefix_weight * (1.0 - jaro)), 4)


def string_similarity(a: str, b: str) -> float:
    """Compute normalized similarity in [0.0, 1.0] combining Jaro-Winkler, token & phonetic match."""
    na = normalize_text(a)
    nb = normalize_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0

    jw = jaro_winkler_similarity(na, nb)
    seq_ratio = SequenceMatcher(None, na, nb).ratio()
    tokens_a = set(na.split())
    tokens_b = set(nb.split())
    jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)

    phonetic_bonus = 0.08 if phonetic_vietnamese_key(na) == phonetic_vietnamese_key(nb) else 0.0
    combined = 0.45 * jw + 0.25 * seq_ratio + 0.30 * jaccard + phonetic_bonus
    return round(min(1.0, combined), 4)
