from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class SourceProfile:
    source: str
    dominant_types: tuple[str, ...]
    automation_suitability: str
    search_strength: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["dominant_types"] = list(self.dominant_types)
        return data


_SOURCE_PROFILES: dict[str, SourceProfile] = {
    "linkedin": SourceProfile(
        source="linkedin",
        dominant_types=("job", "internship"),
        automation_suitability="medium",
        search_strength="broad professional roles",
        notes="Best for standard professional jobs and some internships. Good discovery source, mixed direct-apply reliability.",
    ),
    "naukri": SourceProfile(
        source="naukri",
        dominant_types=("job",),
        automation_suitability="high",
        search_strength="India-focused direct job board",
        notes="Strong default for standard jobs in India. Usually the best fit for direct application workflows.",
    ),
    "indeed": SourceProfile(
        source="indeed",
        dominant_types=("job", "internship"),
        automation_suitability="medium",
        search_strength="broad aggregator",
        notes="Good breadth but mixed quality. Useful for discovery, with variable apply flow quality depending on the upstream site.",
    ),
    "shine": SourceProfile(
        source="shine",
        dominant_types=("job",),
        automation_suitability="medium",
        search_strength="standard jobs with variable relevance",
        notes="Suitable for normal jobs, but quality can vary by query and location.",
    ),
    "internshala": SourceProfile(
        source="internshala",
        dominant_types=("internship", "job"),
        automation_suitability="low",
        search_strength="internships and fresher roles",
        notes="Skews toward internships and entry-level opportunities rather than experienced professional jobs.",
    ),
    "unstop": SourceProfile(
        source="unstop",
        dominant_types=("hackathon", "challenge", "internship"),
        automation_suitability="low",
        search_strength="hackathons, challenges, campus opportunities",
        notes="Not a standard default job board. Better treated as an opportunity source for hackathons, challenges, and student programs.",
    ),
}

_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "hackathon": (
        "hackathon",
        "ideathon",
        "buildathon",
        "challenge",
        "coding contest",
        "competition",
    ),
    "challenge": (
        "challenge",
        "contest",
        "competition",
        "championship",
        "case study",
    ),
    "internship": (
        "intern",
        "internship",
        "trainee",
        "apprentice",
        "fresher",
        "campus",
    ),
}


def get_source_profile(source: str) -> SourceProfile:
    key = (source or "").strip().lower()
    return _SOURCE_PROFILES.get(
        key,
        SourceProfile(
            source=key or "unknown",
            dominant_types=("job",),
            automation_suitability="unknown",
            search_strength="unknown",
            notes="No source profile has been recorded yet.",
        ),
    )


def list_source_profiles() -> list[dict[str, Any]]:
    return [profile.to_dict() for profile in _SOURCE_PROFILES.values()]


def classify_opportunity(job: Mapping[str, Any]) -> dict[str, Any]:
    source = str(job.get("site") or job.get("source") or "").strip().lower()
    title = str(job.get("title") or "").strip()
    description = str(job.get("full_description") or job.get("description") or "").strip()
    combined = f"{title}\n{description}".lower()

    scores = {"job": 1.0, "internship": 0.0, "hackathon": 0.0, "challenge": 0.0}
    signals: list[str] = []

    profile = get_source_profile(source)
    for index, kind in enumerate(profile.dominant_types):
        scores[kind] = scores.get(kind, 0.0) + max(0.2, 0.8 - (index * 0.15))
        signals.append(f"source:{source}->{kind}")

    for kind, keywords in _TYPE_KEYWORDS.items():
        matches = [keyword for keyword in keywords if keyword in combined]
        if matches:
            scores[kind] = scores.get(kind, 0.0) + len(matches) * 1.5
            signals.extend(f"keyword:{keyword}" for keyword in matches[:4])

    if re.search(r"\b(sde[\s-]?intern|intern software|software intern)\b", combined):
        scores["internship"] += 2.0
    if re.search(r"\b(hack|challenge|campus)\b", combined) and source == "unstop":
        scores["hackathon"] += 1.5
        scores["challenge"] += 1.0

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_type, top_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    confidence = 0.55 if top_score <= 1.2 else min(0.98, 0.55 + ((top_score - runner_up) * 0.15))

    if top_type == "challenge" and scores["hackathon"] >= top_score - 0.4:
        top_type = "hackathon"

    return {
        "opportunity_type": top_type,
        "confidence": round(confidence, 2),
        "signals": signals[:6],
        "source_profile": profile.to_dict(),
    }
