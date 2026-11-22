"""Public GitHub connector extracting 8D claims and Behavioral Temporal Fingerprints."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any, Optional

import httpx

from app.connectors.base import BaseConnector, CollectedDocument
from app.core.schemas import FeatureCategory, FeatureClaim


def analyze_active_hours_utc(timestamps: list[str]) -> dict[str, Any]:
    """Compute active hour histogram and infer likely UTC timezone offset from public activity."""
    hours: list[int] = []
    for ts in timestamps:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            hours.append(dt.hour)
        except ValueError:
            continue

    if not hours:
        return {}

    counts = Counter(hours)
    peak_utc_hour, _ = counts.most_common(1)[0]
    # Assume typical peak coding activity around 14:00 - 22:00 local time (midpoint ~16:00)
    estimated_offset = ((16 - peak_utc_hour + 12) % 24) - 12
    sign = "+" if estimated_offset >= 0 else ""
    return {
        "sample_size": len(hours),
        "peak_utc_hour": peak_utc_hour,
        "hour_histogram_utc": dict(sorted(counts.items())),
        "inferred_local_tz_approx": f"UTC{sign}{estimated_offset}",
    }


class GitHubPublicConnector(BaseConnector):
    """Fetches public GitHub user profiles, searches by real name, and analyzes activity timestamps."""

    API_BASE = "https://api.github.com"

    async def search_users_by_name(
        self,
        full_name: str,
        limit: int = 3,
        client: Optional[httpx.AsyncClient] = None,
    ) -> list[str]:
        """Search public GitHub usernames matching a real name (no exact handle required)."""
        from urllib.parse import quote_plus

        q = quote_plus(full_name.strip())
        url = f"{self.API_BASE}/search/users?q={q}&per_page={limit}"
        try:
            body, status, _ = await self.cached_get(url, client=client)
            if status != 200:
                return []
            items = json.loads(body).get("items", [])
            return [str(it["login"]) for it in items if it.get("login")]
        except Exception:
            return []

    async def collect(
        self,
        target: str,
        client: Optional[httpx.AsyncClient] = None,
        **kwargs: Any,
    ) -> CollectedDocument:
        username = target.strip().lstrip("@")
        profile_url = f"{self.API_BASE}/users/{username}"
        html_url = f"https://github.com/{username}"

        body, status, cached = await self.cached_get(profile_url, client=client)
        if status == 404:
            return CollectedDocument(
                source_type="github",
                url=html_url,
                title=f"GitHub: {username} (Not Found)",
                is_soft_404=True,
                cached=cached,
            )

        data = json.loads(body)
        claims: list[FeatureClaim] = []

        if data.get("name"):
            claims.append(
                FeatureClaim(
                    category=FeatureCategory.IDENTITY,
                    key="full_name",
                    value=data["name"],
                    confidence=0.85,
                    source_url=html_url,
                    evidence_quote=f"GitHub profile name: {data['name']}",
                )
            )
        if data.get("company"):
            claims.append(
                FeatureClaim(
                    category=FeatureCategory.EDUCATION_CAREER,
                    key="organization",
                    value=data["company"].lstrip("@").strip(),
                    confidence=0.8,
                    source_url=html_url,
                    evidence_quote=f"GitHub company field: {data['company']}",
                )
            )
        if data.get("location"):
            claims.append(
                FeatureClaim(
                    category=FeatureCategory.SPATIOTEMPORAL,
                    key="location",
                    value=data["location"],
                    confidence=0.75,
                    source_url=html_url,
                    evidence_quote=f"GitHub location field: {data['location']}",
                )
            )
        if data.get("email"):
            claims.append(
                FeatureClaim(
                    category=FeatureCategory.TECHNICAL_ARTIFACT,
                    key="email",
                    value=data["email"],
                    confidence=0.95,
                    source_url=html_url,
                    evidence_quote=f"GitHub public email: {data['email']}",
                )
            )

        outbound: list[str] = []
        if data.get("blog"):
             outbound.append(str(data["blog"]))
        if data.get("twitter_username"):
            outbound.append(f"https://x.com/{data['twitter_username']}")

        # Fetch public repos for programming language & topic skills
        repos_url = f"{self.API_BASE}/users/{username}/repos?per_page=20&sort=updated"
        repos_body, repos_status, _ = await self.cached_get(repos_url, client=client)
        languages: Counter[str] = Counter()
        repo_timestamps: list[str] = []
        if repos_status == 200:
            for repo in json.loads(repos_body):
                if repo.get("language"):
                    languages[repo["language"]] += 1
                if repo.get("pushed_at"):
                    repo_timestamps.append(repo["pushed_at"])

        if languages:
            top_langs = [lang for lang, _ in languages.most_common(5)]
            claims.append(
                FeatureClaim(
                    category=FeatureCategory.INTERESTS_SKILLS,
                    key="programming_languages",
                    value=top_langs,
                    confidence=0.9,
                    source_url=html_url,
                    evidence_quote=f"Top repository languages: {', '.join(top_langs)}",
                )
            )

        temporal_sig = analyze_active_hours_utc(repo_timestamps)
        if temporal_sig:
            claims.append(
                FeatureClaim(
                    category=FeatureCategory.STYLOMETRY_BEHAVIOR,
                    key="temporal_activity_signature",
                    value=temporal_sig,
                    confidence=0.7,
                    source_url=html_url,
                    evidence_quote=f"Peak public push hour UTC: {temporal_sig['peak_utc_hour']}",
                )
            )

        bio = data.get("bio") or ""
        return CollectedDocument(
            source_type="github",
            url=html_url,
            title=f"GitHub Profile: {data.get('login', username)}",
            content=bio,
            claims=claims,
            outbound_links=outbound,
            metadata={"public_repos": data.get("public_repos", 0), "temporal": temporal_sig},
            cached=cached,
        )
