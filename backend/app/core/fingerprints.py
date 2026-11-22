"""Behavioral, Stylometric, Handle-Anatomy, and Cryptographic OSINT Fingerprinting."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any

from app.core.normalizer import normalize_text

COMMON_EN_TECH_WORDS: frozenset[str] = frozenset(
    {
        "dev",
        "code",
        "ai",
        "ml",
        "sec",
        "cyber",
        "ctf",
        "cloud",
        "data",
        "backend",
        "frontend",
        "fullstack",
        "linux",
        "python",
        "rust",
        "react",
        "bug",
        "hack",
        "osint",
        "system",
        "network",
        "api",
        "web",
        "app",
    }
)

EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U00002600-\U000027BF"
    "]+",
    flags=re.UNICODE,
)


def gravatar_md5(email: str) -> str:
    """Compute standard Gravatar MD5 hash from an email address."""
    clean = email.strip().lower()
    if not clean:
        return ""
    return hashlib.md5(clean.encode("utf-8")).hexdigest()


def extract_handle_fingerprint(username: str) -> dict[str, Any]:
    """Decompose a username/handle into structural behavioral features.

    Captures naming habits across platforms (e.g. 'minhtuan_2002' vs 'tuanm_02'):
    - trailing/embedded 2-digit or 4-digit birth/class year hints ('02' -> 2002)
    - separator preference ('_', '.', '-', or none)
    - tech/role affixes ('dev', 'sec', 'official', 'vn')
    - alphabetic root tokens
    """
    raw = username.strip().lstrip("@").lower()
    if not raw:
        return {}

    separators = [sep for sep in ("_", ".", "-") if sep in raw]
    digits = re.findall(r"\d+", raw)
    inferred_years: list[int] = []
    for d in digits:
        if len(d) == 4 and (d.startswith("19") or d.startswith("20")):
            inferred_years.append(int(d))
        elif len(d) == 2:
            val = int(d)
            year = 2000 + val if val <= 30 else 1900 + val
            inferred_years.append(year)

    alpha_tokens = [t for t in re.split(r"[^a-z]+", raw) if t]
    affixes = [t for t in alpha_tokens if t in COMMON_EN_TECH_WORDS or t in ("vn", "official", "real")]
    core_alpha = "".join(t for t in alpha_tokens if t not in affixes)

    return {
        "raw": raw,
        "separators": separators,
        "digits": digits,
        "inferred_years": sorted(set(inferred_years)),
        "affixes": affixes,
        "core_alpha": core_alpha,
        "length": len(raw),
    }


def handle_pattern_similarity(handle_a: str, handle_b: str) -> float:
    """Score structural & behavioral similarity between two usernames in [0.0, 1.0]."""
    fp_a = extract_handle_fingerprint(handle_a)
    fp_b = extract_handle_fingerprint(handle_b)
    if not fp_a or not fp_b:
        return 0.0
    if fp_a["raw"] == fp_b["raw"]:
        return 1.0

    score = 0.0
    # 1. Shared inferred year (e.g. '2002' and '02')
    if fp_a["inferred_years"] and (set(fp_a["inferred_years"]) & set(fp_b["inferred_years"])):
        score += 0.35

    # 2. Core alphabetic character bigrams / subsequence overlap
    ca, cb = fp_a["core_alpha"], fp_b["core_alpha"]
    if ca and cb:
        if ca == cb or ca in cb or cb in ca:
            score += 0.40
        else:
            bigrams_a = {ca[i : i + 2] for i in range(max(1, len(ca) - 1))}
            bigrams_b = {cb[i : i + 2] for i in range(max(1, len(cb) - 1))}
            overlap = len(bigrams_a & bigrams_b) / max(1, len(bigrams_a | bigrams_b))
            score += 0.40 * overlap

    # 3. Shared separator habit or shared affix ('dev', 'sec', 'vn')
    if fp_a["separators"] and fp_a["separators"] == fp_b["separators"]:
        score += 0.10
    if fp_a["affixes"] and (set(fp_a["affixes"]) & set(fp_b["affixes"])):
        score += 0.15

    return round(min(1.0, score), 4)


def compute_stylometry_profile(text: str) -> dict[str, Any]:
    """Extract a stylometric writing fingerprint from unstructured text.

    Measures:
    - Lexical diversity (Type-Token Ratio)
    - Average word length & sentence length
    - Punctuation habits (exclamation, question, ellipsis, comma ratios)
    - Bilingual code-switching ratio (English tech jargon mixed into Vietnamese)
    - Emoji usage density
    - Top character 3-grams
    """
    clean = text.strip()
    if not clean:
        return {}

    sentences = [s.strip() for s in re.split(r"[.!?;\n]+", clean) if s.strip()]
    words = re.findall(r"\b\w+\b", clean.lower())
    total_words = max(1, len(words))
    total_chars = max(1, len(clean))

    unique_words = set(words)
    ttr = len(unique_words) / total_words
    avg_word_len = sum(len(w) for w in words) / total_words
    avg_sent_len = total_words / max(1, len(sentences))

    exclam_rate = clean.count("!") / total_chars
    quest_rate = clean.count("?") / total_chars
    ellipsis_rate = clean.count("...") / max(1, len(sentences))
    emoji_count = sum(len(m) for m in EMOJI_RE.findall(clean))
    emoji_rate = emoji_count / total_words

    en_mix_count = sum(1 for w in words if w in COMMON_EN_TECH_WORDS)
    code_switch_ratio = en_mix_count / total_words

    norm = normalize_text(clean).replace(" ", "_")
    trigrams = Counter(norm[i : i + 3] for i in range(max(0, len(norm) - 2)))

    features = [
        round(ttr, 4),
        round(min(1.0, avg_word_len / 10.0), 4),
        round(min(1.0, avg_sent_len / 30.0), 4),
        round(min(1.0, exclam_rate * 20.0), 4),
        round(min(1.0, quest_rate * 20.0), 4),
        round(min(1.0, ellipsis_rate), 4),
        round(min(1.0, emoji_rate * 5.0), 4),
        round(min(1.0, code_switch_ratio * 5.0), 4),
    ]

    return {
        "word_count": len(words),
        "type_token_ratio": round(ttr, 4),
        "avg_sentence_words": round(avg_sent_len, 2),
        "code_switch_ratio": round(code_switch_ratio, 4),
        "emoji_rate": round(emoji_rate, 4),
        "feature_vector": features,
        "top_trigrams": dict(trigrams.most_common(40)),
    }


def _cosine_dict(a: dict[str, int], b: dict[str, int]) -> float:
    if not a or not b:
        return 0.0
    shared = set(a.keys()) & set(b.keys())
    num = sum(a[k] * b[k] for k in shared)
    den_a = math.sqrt(sum(v * v for v in a.values()))
    den_b = math.sqrt(sum(v * v for v in b.values()))
    if den_a == 0 or den_b == 0:
        return 0.0
    return num / (den_a * den_b)


def _cosine_vec(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    num = sum(a * b for a, b in zip(v1, v2))
    den_a = math.sqrt(sum(a * a for a in v1))
    den_b = math.sqrt(sum(b * b for b in v2))
    if den_a == 0 or den_b == 0:
        return 0.0
    return num / (den_a * den_b)


def stylometry_similarity(text_a: str, text_b: str) -> dict[str, Any]:
    """Compare writing style between two public texts via stylometric vector + character 3-gram cosine."""
    prof_a = compute_stylometry_profile(text_a)
    prof_b = compute_stylometry_profile(text_b)
    if not prof_a or not prof_b:
        return {"overall_similarity": 0.0, "vector_cosine": 0.0, "trigram_cosine": 0.0}

    vec_sim = _cosine_vec(prof_a["feature_vector"], prof_b["feature_vector"])
    tri_sim = _cosine_dict(prof_a["top_trigrams"], prof_b["top_trigrams"])
    overall = round(0.70 * vec_sim + 0.30 * tri_sim, 4)

    return {
        "overall_similarity": overall,
        "vector_cosine": round(vec_sim, 4),
        "trigram_cosine": round(tri_sim, 4),
        "profile_a": {k: v for k, v in prof_a.items() if k != "top_trigrams"},
        "profile_b": {k: v for k, v in prof_b.items() if k != "top_trigrams"},
    }
