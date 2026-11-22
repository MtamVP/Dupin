"""Bayesian Log-Odds Belief Updating with Source Diversity Damping for OSINT claims."""

from __future__ import annotations

import math
from urllib.parse import urlparse

from app.core.schemas import FeatureClaim

EPSILON = 1e-4


def _clamp_prob(p: float) -> float:
    return max(EPSILON, min(1.0 - EPSILON, p))


def prob_to_log_odds(p: float) -> float:
    p_c = _clamp_prob(p)
    return math.log(p_c / (1.0 - p_c))


def log_odds_to_prob(lo: float) -> float:
    # Clamp log-odds to avoid overflow
    lo_c = max(-12.0, min(12.0, lo))
    return 1.0 / (1.0 + math.exp(-lo_c))


def extract_source_domain(url: str) -> str:
    """Extract normalized domain from URL to prevent echo-chamber confidence inflation."""
    if not url:
        return "unknown"
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or parsed.path).lower().strip()
        if host.startswith("www."):
            host = host[4:]
        return host or "unknown"
    except Exception:
        return "unknown"


def compute_bayesian_confidence(
    prior: float,
    claims: list[FeatureClaim],
) -> float:
    """Update entity confidence via Log-Odds Bayes rule with domain-repetition damping.

    - Multiple independent domains reinforce belief strongly.
    - Repeated claims from the SAME domain are damped by 1 / sqrt(k) (anti-echo-chamber).
    - NEGATIVE polarity claims subtract log-odds evidence.
    """
    if not claims:
        return round(_clamp_prob(prior), 4)

    log_odds = prob_to_log_odds(prior)
    domain_counts: dict[str, int] = {}

    for claim in claims:
        domain = extract_source_domain(claim.source_url)
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        k = domain_counts[domain]
        # Diminishing returns for repeated evidence from the same host
        diversity_weight = 1.0 / math.sqrt(k)

        # Map claim confidence [0, 1] into evidence strength above neutral (0.5)
        # Even low-confidence claims contribute a small positive/negative nudge
        effective_p = 0.5 + 0.45 * _clamp_prob(claim.confidence)
        delta = prob_to_log_odds(effective_p) * 0.35 * diversity_weight

        if claim.polarity == "NEGATIVE":
            log_odds -= delta * 1.25  # Negative constraints penalize more sharply
        else:
            log_odds += delta

    return round(log_odds_to_prob(log_odds), 4)
