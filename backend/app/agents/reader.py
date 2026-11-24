"""Reader Agent: Neuro-Symbolic Vietnamese/English Entity & Relation Extractor."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.connectors.web_fetcher import extract_rule_based_claims
from app.core.fingerprints import compute_stylometry_profile, gravatar_md5
from app.core.llm_provider import BaseLLMProvider
from app.core.normalizer import normalize_text
from app.core.schemas import FeatureCategory, FeatureClaim, NodeType


class ExtractedTriple(BaseModel):
    """A semantic relationship extracted from unstructured text with verbatim quote."""

    subject_label: str
    subject_type: NodeType = "Person"
    relation: str
    object_label: str
    object_type: NodeType
    confidence: float = Field(0.75, ge=0.0, le=1.0)
    evidence_quote: str
    source_url: str = ""
    time_range: Optional[tuple[str, str]] = None


class ExtractionResult(BaseModel):
    """Output of ReaderAgent containing 8D claims and graph relationship triples."""

    subject_label: str
    claims: list[FeatureClaim] = Field(default_factory=list)
    triples: list[ExtractedTriple] = Field(default_factory=list)


# Vietnamese & English contextual relation patterns
EDU_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:học tại|sinh viên(?:\s+trường)?|cựu học sinh(?:\s+trường)?|tốt nghiệp(?:\s+trường)?|graduated from|student at|studied at)\s+"
        r"((?:(?:Trường\s+)?(?:ĐH|Đại học|THPT|THCS|Học viện|University|Institute|College)\s+[A-ZÀ-Ỹ0-9][A-Za-zÀ-ỹ0-9\s.\-]{1,42})|(?:HCMUT|HUST|UIT|PTIT|UEH|NEU|FPT|VNU|ĐHBK)\b)",
        re.IGNORECASE,
    ),
]

WORK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:làm việc tại|công tác tại|kỹ sư tại|intern tại|works at|engineer at|developer at)\s+"
        r"([A-ZÀ-Ỹ][A-Za-zÀ-ỹ0-9\s.&\-]{1,35})",
        re.IGNORECASE,
    ),
]

LOCATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:quê ở|quê tại|sinh ra tại|sống tại|đến từ|lives in|based in|from)\s+"
        r"([A-ZÀ-Ỹ][A-Za-zÀ-ỹ\s.\-]{2,30})",
        re.IGNORECASE,
    ),
]

NEGATIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:không phải ở|chưa từng sống tại|không học tại|not from|never lived in)\s+"
        r"([A-ZÀ-Ỹ][A-Za-zÀ-ỹ\s.\-]{2,30})",
        re.IGNORECASE,
    ),
]

DOB_FULL_RE = re.compile(
    r"(?:sinh ngày|ngày sinh|dob|birthday)[:\s]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.](?:19[7-9]\d|20[0-2]\d))",
    re.IGNORECASE,
)

MAJOR_RE = re.compile(
    r"(?:chuyên ngành|ngành|khoa)\s+([A-ZÀ-Ỹa-zà-ỹ][A-Za-zÀ-ỹ0-9\s\-]{2,40})",
    re.IGNORECASE,
)

VN_PHONE_RE = re.compile(r"\b(?:\+84|0)(?:3|5|7|8|9)\d{8}\b")

NICKNAME_PAREN_RE = re.compile(
    r"\b([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,3})\s*\(([A-Za-zÀ-ỹ0-9_.\-\s]{2,22})\)"
)


STOP_WORKPLACES: set[str] = {
    "đây",
    "đó",
    "này",
    "kia",
    "nhà",
    "trường",
    "bệnh viện",
    "công ty",
    "việt nam",
}


def _clean_extracted_entity(raw: str) -> str:
    # Stop at common clause delimiters or conjunctions
    stopped = re.split(
        r"\s*(?:,|;|\.|và hiện|hiện là|từ năm|năm\s+\d{4}|with|where|and\s+is)\b",
        raw,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    cleaned = stopped.strip(" .,;-()")
    return "" if cleaned.lower() in STOP_WORKPLACES else cleaned


_GENERIC_BYSTANDER_EMAIL_PREFIXES: tuple[str, ...] = (
    "admin",
    "info",
    "contact",
    "support",
    "help",
    "office",
    "ctsv",
    "daotao",
    "pdt",
    "tuyensinh",
    "vanphong",
    "khoa",
    "bgh",
    "hsv",
    "doanthanhnien",
    "webmaster",
    "noreply",
    "no-reply",
    "hr",
    "media",
    "pr",
)


def is_email_plausible_for_subject(email: str, subject_label: str, context_text: str = "") -> bool:
    """Verify whether a page-extracted email plausibly belongs to `subject_label` rather than a faculty/admin bystander."""
    em = (email or "").strip().lower()
    if "@" not in em:
        return False
    local = em.split("@", 1)[0]
    local_alpha = re.sub(r"[^a-z0-9]", "", local)
    if not local_alpha:
        return False
    if any(local == p or local.startswith(f"{p}.") or local.startswith(f"{p}_") for p in _GENERIC_BYSTANDER_EMAIL_PREFIXES):
        return False

    norm_subj = normalize_text(subject_label)
    tokens = [re.sub(r"[^a-z0-9]", "", t) for t in norm_subj.split() if re.sub(r"[^a-z0-9]", "", t)]
    if not tokens:
        return True

    # 1. Pure or dominant student ID email (e.g. 25521646@gm.uit.edu.vn or 31251020299@st.ueh.edu.vn)
    digits_in_local = "".join(ch for ch in local_alpha if ch.isdigit())
    if len(digits_in_local) >= 6:
        # If context mentions another student ID right next to this email, or if digits match known text
        return True

    # 2. Check Vietnamese name token & abbreviation patterns for subject_label
    # Example: "võ phúc minh tâm" -> tokens=["vo", "phuc", "minh", "tam"]
    # Common VN academic/corporate handles:
    # - given_name + initials: "tamvpm", "tamvp"
    # - initials + given_name: "vpmtam"
    # - given_name + middle/family: "minhtam", "tamvo", "vophucminhtam"
    given = tokens[-1]
    family = tokens[0]
    initials_all = "".join(t[0] for t in tokens)
    initials_prefix = "".join(t[0] for t in tokens[:-1])
    joined_all = "".join(tokens)

    plausible_markers = {
        given,
        f"{given}{initials_prefix}",
        f"{initials_prefix}{given}",
        f"{given}{family}",
        f"{family}{given}",
        joined_all,
        initials_all,
    }
    if len(tokens) >= 2:
        plausible_markers.add(f"{tokens[-2]}{given}")
        plausible_markers.add(f"{given}{tokens[-2]}")

    # If the email local part contains the subject's given name (length >= 3) or matches abbreviation patterns -> plausible!
    if len(given) >= 3 and given in local_alpha:
        return True
    if any(m and len(m) >= 4 and m in local_alpha for m in plausible_markers):
        return True

    # Otherwise (e.g., "binhnt@uit.edu.vn" when subject is "võ phúc minh tâm"), it belongs to another person on the page!
    return False


class ReaderAgent:
    """Extracts 8D claims and relationship triples using neuro-symbolic rules + optional LLM."""

    def __init__(self, llm: Optional[BaseLLMProvider] = None) -> None:
        self.llm = llm

    async def extract(
        self,
        text: str,
        subject_label: str,
        source_url: str = "manual://reader-agent",
    ) -> ExtractionResult:
        raw_claims, outbound = extract_rule_based_claims(text, source_url)
        claims: list[FeatureClaim] = []
        for rc in raw_claims:
            if rc.key == "email" and source_url != "user://prompt":
                if not is_email_plausible_for_subject(str(rc.value), subject_label, text):
                    continue
            claims.append(rc)
        triples: list[ExtractedTriple] = []

        # Check if subject_label (or unaccented form) is explicitly mentioned in text
        norm_subj = normalize_text(subject_label)
        if norm_subj and norm_subj in normalize_text(text):
            claims.append(
                FeatureClaim(
                    category=FeatureCategory.IDENTITY,
                    key="full_name",
                    value=subject_label,
                    confidence=0.85,
                    source_url=source_url,
                    evidence_quote=text[:140],
                )
            )

        # Enrich email claims with deterministic Gravatar MD5 technical artifact
        for c in list(claims):
            if c.key == "email":
                g_hash = gravatar_md5(str(c.value))
                if g_hash:
                    claims.append(
                        FeatureClaim(
                            category=FeatureCategory.TECHNICAL_ARTIFACT,
                            key="gravatar_md5",
                            value=g_hash,
                            confidence=0.95,
                            source_url=source_url,
                            evidence_quote=f"Gravatar MD5 for {c.value}",
                        )
                    )

        # Convert social URLs into Alias/TechnicalArtifact triples
        for url in outbound:
            handle = url.rstrip("/").split("/")[-1]
            triples.append(
                ExtractedTriple(
                    subject_label=subject_label,
                    relation="OWNS_ACCOUNT",
                    object_label=handle,
                    object_type="Alias",
                    confidence=0.88,
                    evidence_quote=url,
                    source_url=source_url,
                )
            )

        # Infer academic institution from authoritative `.edu.vn` source URLs when the target is mentioned in the document
        if norm_subj and norm_subj in normalize_text(text) and ".edu.vn" in source_url.lower():
            from app.core.graph_store import GraphStore

            url_low = source_url.lower()
            for dom, canon_org in GraphStore._KNOWN_DOMAIN_ORG_MAP.items():
                if dom in url_low:
                    claims.append(
                        FeatureClaim(
                            category=FeatureCategory.EDUCATION_CAREER,
                            key="school_or_org",
                            value=canon_org,
                            confidence=0.90,
                            source_url=source_url,
                            evidence_quote=text[:140],
                        )
                    )
                    triples.append(
                        ExtractedTriple(
                            subject_label=subject_label,
                            relation="STUDIED_OR_WORKED_AT",
                            object_label=canon_org,
                            object_type="Org",
                            confidence=0.90,
                            evidence_quote=text[:140],
                            source_url=source_url,
                        )
                    )
                    break

        # Split text into sentence windows so every extracted triple carries an exact quote
        sentences = [s.strip() for s in re.split(r"(?<=[.!?;\n])\s+", text) if s.strip()]
        for sent in sentences:
            for pat in EDU_PATTERNS:
                for m in pat.finditer(sent):
                    school = _clean_extracted_entity(m.group(1))
                    if len(school) >= 3:
                        claims.append(
                            FeatureClaim(
                                category=FeatureCategory.EDUCATION_CAREER,
                                key="school",
                                value=school,
                                confidence=0.82,
                                source_url=source_url,
                                evidence_quote=sent,
                            )
                        )
                        triples.append(
                            ExtractedTriple(
                                subject_label=subject_label,
                                relation="STUDIED_AT",
                                object_label=school,
                                object_type="Org",
                                confidence=0.82,
                                evidence_quote=sent,
                                source_url=source_url,
                            )
                        )

            for pat in WORK_PATTERNS:
                for m in pat.finditer(sent):
                    org = _clean_extracted_entity(m.group(1))
                    if len(org) >= 2:
                        claims.append(
                            FeatureClaim(
                                category=FeatureCategory.EDUCATION_CAREER,
                                key="workplace",
                                value=org,
                                confidence=0.80,
                                source_url=source_url,
                                evidence_quote=sent,
                            )
                        )
                        triples.append(
                            ExtractedTriple(
                                subject_label=subject_label,
                                relation="WORKS_AT",
                                object_label=org,
                                object_type="Org",
                                confidence=0.80,
                                evidence_quote=sent,
                                source_url=source_url,
                            )
                        )

            for pat in LOCATION_PATTERNS:
                for m in pat.finditer(sent):
                    loc = _clean_extracted_entity(m.group(1))
                    if len(loc) >= 2:
                        claims.append(
                            FeatureClaim(
                                category=FeatureCategory.SPATIOTEMPORAL,
                                key="location",
                                value=loc,
                                confidence=0.78,
                                source_url=source_url,
                                evidence_quote=sent,
                            )
                        )
                        triples.append(
                            ExtractedTriple(
                                subject_label=subject_label,
                                relation="LOCATED_IN",
                                object_label=loc,
                                object_type="Location",
                                confidence=0.78,
                                evidence_quote=sent,
                                source_url=source_url,
                            )
                        )

            for pat in NEGATIVE_PATTERNS:
                for m in pat.finditer(sent):
                    neg_val = _clean_extracted_entity(m.group(1))
                    if len(neg_val) >= 2:
                        claims.append(
                            FeatureClaim(
                                category=FeatureCategory.NEGATIVE_CONSTRAINT,
                                key="excluded_location_or_org",
                                value=neg_val,
                                polarity="NEGATIVE",
                                confidence=0.85,
                                source_url=source_url,
                                evidence_quote=sent,
                            )
                        )

            for m in DOB_FULL_RE.finditer(sent):
                dob = m.group(1).strip()
                claims.append(
                    FeatureClaim(
                        category=FeatureCategory.SPATIOTEMPORAL,
                        key="birth_date",
                        value=dob,
                        confidence=0.90,
                        source_url=source_url,
                        evidence_quote=sent,
                    )
                )

            for m in MAJOR_RE.finditer(sent):
                major = _clean_extracted_entity(m.group(1))
                if len(major) >= 3:
                    claims.append(
                        FeatureClaim(
                            category=FeatureCategory.EDUCATION_CAREER,
                            key="major_department",
                            value=major,
                            confidence=0.80,
                            source_url=source_url,
                            evidence_quote=sent,
                        )
                    )
                    triples.append(
                        ExtractedTriple(
                            subject_label=subject_label,
                            relation="SPECIALIZES_IN",
                            object_label=major,
                            object_type="Topic",
                            confidence=0.80,
                            evidence_quote=sent,
                            source_url=source_url,
                        )
                    )

            for phone in sorted(set(VN_PHONE_RE.findall(sent))):
                claims.append(
                    FeatureClaim(
                        category=FeatureCategory.TECHNICAL_ARTIFACT,
                        key="public_phone",
                        value=phone,
                        confidence=0.90,
                        source_url=source_url,
                        evidence_quote=sent,
                    )
                )

            for m in NICKNAME_PAREN_RE.finditer(sent):
                nick = m.group(2).strip()
                if not re.search(r"sinh năm|sn\s*\d{4}|\b(?:19|20)\d{2}\b", nick, re.IGNORECASE):
                    claims.append(
                        FeatureClaim(
                            category=FeatureCategory.IDENTITY,
                            key="nickname",
                            value=nick,
                            confidence=0.82,
                            source_url=source_url,
                            evidence_quote=sent,
                        )
                    )
                    triples.append(
                        ExtractedTriple(
                            subject_label=subject_label,
                            relation="ALSO_KNOWN_AS",
                            object_label=nick,
                            object_type="Alias",
                            confidence=0.82,
                            evidence_quote=sent,
                            source_url=source_url,
                        )
                    )

        # Attach Stylometry signature if text is sufficiently rich (>= 12 words)
        style_prof = compute_stylometry_profile(text)
        if style_prof.get("word_count", 0) >= 12:
            claims.append(
                FeatureClaim(
                    category=FeatureCategory.STYLOMETRY_BEHAVIOR,
                    key="stylometry_vector",
                    value=style_prof["feature_vector"],
                    confidence=0.70,
                    source_url=source_url,
                    evidence_quote=text[:160],
                )
            )

        # Optional LLM deep extraction enrichment when an active provider is injected
        if self.llm is not None:
            await self._enrich_with_llm(text, subject_label, source_url, claims, triples)

        return ExtractionResult(subject_label=subject_label, claims=claims, triples=triples)

    async def _enrich_with_llm(
        self,
        text: str,
        subject_label: str,
        source_url: str,
        claims: list[FeatureClaim],
        triples: list[ExtractedTriple],
    ) -> None:
        prompt = (
            f"Extract factual OSINT triples about '{subject_label}' from the text below.\n"
            "Return ONLY a JSON array of objects with keys: "
            "relation (STUDIED_AT|WORKS_AT|LOCATED_IN|KNOWS|INTERESTED_IN), "
            "object_label, object_type (Org|Location|Person|Topic), evidence_quote (exact substring).\n"
            f"Text:\n{text}"
        )
        try:
            raw = await self.llm.generate(prompt, temperature=0.1)
            start, end = raw.find("["), raw.rfind("]")
            if start != -1 and end != -1:
                items: list[dict[str, Any]] = json.loads(raw[start : end + 1])
                for item in items:
                    triples.append(
                        ExtractedTriple(
                            subject_label=subject_label,
                            relation=str(item.get("relation", "MENTIONED_WITH")),
                            object_label=str(item.get("object_label", "")),
                            object_type=item.get("object_type", "Topic"),
                            confidence=0.75,
                            evidence_quote=str(item.get("evidence_quote", "")),
                            source_url=source_url,
                        )
                    )
        except Exception:
            # Fail gracefully to deterministic neuro-symbolic output if local Ollama is offline
            return
