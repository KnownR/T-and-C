"""Loader for the hand-labelled Terms of Service Golden Set.

Provides 14 real-world, anonymized ToS clauses covering all 8 rubric categories:
- Mandatory Arbitration (2 cases)
- Unilateral Change of Terms (2 cases)
- Discretionary Content Removal (1 case)
- Jurisdiction Selection (2 cases)
- Choice of Governing Law (1 case)
- Limitation of Liability (2 cases)
- Unilateral Termination (2 cases)
- Contract Formed by Usage (2 cases)
- Clean / Fair control clauses (3 cases, zero unfair terms) to measure False Positives.
"""

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden" / "golden_set.json"


class GoldenSample(BaseModel):
    """A hand-labelled golden set sample."""

    sample_id: int
    name: str
    categories: list[str] = Field(default_factory=list)
    text: str
    notes: Optional[str] = None


def load_golden_set(limit: Optional[int] = None) -> list[GoldenSample]:
    """Load the hand-labelled golden set benchmark."""
    if not GOLDEN_SET_PATH.exists():
        raise FileNotFoundError(f"Golden set file not found at {GOLDEN_SET_PATH}")

    with open(GOLDEN_SET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    samples = [
        GoldenSample(
            sample_id=item["id"],
            name=item["name"],
            categories=item.get("categories", []),
            text=item["text"].strip(),
            notes=item.get("notes"),
        )
        for item in data
    ]

    if limit is not None and limit > 0:
        samples = samples[:limit]

    return samples
