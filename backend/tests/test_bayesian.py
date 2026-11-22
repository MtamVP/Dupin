"""Unit tests for Bayesian Log-Odds Belief Updating and Source Diversity Damping."""

from app.core.bayesian import compute_bayesian_confidence
from app.core.schemas import FeatureCategory, FeatureClaim


def test_independent_domains_score_higher_than_echo_chamber() -> None:
    same_domain_claims = [
        FeatureClaim(
            category=FeatureCategory.IDENTITY,
            key="school",
            value="HCMUT",
            confidence=0.8,
            source_url=f"https://sameblog.com/post-{i}",
        )
        for i in range(3)
    ]
    diverse_domain_claims = [
        FeatureClaim(
            category=FeatureCategory.IDENTITY,
            key="school",
            value="HCMUT",
            confidence=0.8,
            source_url=f"https://site-{i}.org/profile",
        )
        for i in range(3)
    ]

    echo_conf = compute_bayesian_confidence(0.5, same_domain_claims)
    diverse_conf = compute_bayesian_confidence(0.5, diverse_domain_claims)

    assert diverse_conf > echo_conf > 0.5


def test_negative_constraint_reduces_bayesian_confidence() -> None:
    neg = [
        FeatureClaim(
            category=FeatureCategory.NEGATIVE_CONSTRAINT,
            key="city",
            value="Ha Noi",
            polarity="NEGATIVE",
            confidence=0.9,
            source_url="https://official.edu.vn/record",
        )
    ]
    updated = compute_bayesian_confidence(0.75, neg)
    assert updated < 0.75
