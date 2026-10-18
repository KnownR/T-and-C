"""Dataset loader for LexGLUE / UNFAIR-ToS benchmark.

Source: HuggingFace coastalcph/lex_glue (config: unfair_tos)
Reference: Lippi et al., "CLAUDETTE: an automated detector of potentially unfair
clauses in online terms of service", Artificial Intelligence and Law, 2019.

Benchmark Category Mapping:
The UNFAIR-ToS benchmark defines 8 categories of unfair contract terms.
These map 1-to-1 to the 8 categories configured in backend/app/lenses/tos.yaml:

LexGLUE Label ID | LexGLUE Feature Name         | tos.yaml Lens Category ID
-----------------|------------------------------|--------------------------
0                | Limitation of liability      | limitation_of_liability
1                | Unilateral termination       | unilateral_termination
2                | Unilateral change            | unilateral_change
3                | Content removal              | content_removal
4                | Contract by using            | contract_by_using
5                | Choice of law                | choice_of_law
6                | Jurisdiction                 | jurisdiction
7                | Arbitration                  | arbitration

Note: An empty list of labels (`labels == []`) denotes a fair / neutral clause (negative sample).
Sentences may also occasionally be multi-labeled (e.g. [2, 3]).
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Explicit mapping from LexGLUE UNFAIR-ToS integer labels to tos.yaml lens category IDs
LEXGLUE_LABEL_MAP: dict[int, str] = {
    0: "limitation_of_liability",
    1: "unilateral_termination",
    2: "unilateral_change",
    3: "content_removal",
    4: "contract_by_using",
    5: "choice_of_law",
    6: "jurisdiction",
    7: "arbitration",
}

# Reverse mapping from lens category ID to LexGLUE integer label
CATEGORY_TO_LABEL_MAP: dict[str, int] = {v: k for k, v in LEXGLUE_LABEL_MAP.items()}

# Human-readable display names for benchmark reporting
CATEGORY_NAMES: dict[str, str] = {
    "arbitration": "Mandatory Arbitration",
    "unilateral_change": "Unilateral Change",
    "content_removal": "Content Removal",
    "jurisdiction": "Jurisdiction Selection",
    "choice_of_law": "Choice of Law",
    "limitation_of_liability": "Limitation of Liability",
    "unilateral_termination": "Unilateral Termination",
    "contract_by_using": "Contract Formed by Usage",
}

ALL_CATEGORIES: list[str] = [
    "limitation_of_liability",
    "unilateral_termination",
    "unilateral_change",
    "content_removal",
    "contract_by_using",
    "choice_of_law",
    "jurisdiction",
    "arbitration",
]


class UnfairTosSample(BaseModel):
    """A sentence-level sample from the UNFAIR-ToS benchmark."""

    sample_id: int
    text: str
    labels: list[int] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)


def map_labels_to_categories(labels: list[int]) -> list[str]:
    """Map raw LexGLUE label integers to tos.yaml category IDs."""
    categories: list[str] = []
    for lbl in labels:
        if lbl in LEXGLUE_LABEL_MAP:
            cat = LEXGLUE_LABEL_MAP[lbl]
            if cat not in categories:
                categories.append(cat)
        else:
            logger.warning(f"Unknown label ID {lbl} encountered in dataset.")
    return sorted(categories)


def get_default_data_dir() -> Path:
    """Return the default path to the local data cache directory."""
    return Path(__file__).resolve().parent.parent / "data"


def fetch_from_hf_datasets_server(
    split: str = "test",
    max_retries: int = 5,
    backoff_factor: float = 1.5,
) -> list[dict]:
    """Fetch split rows from HuggingFace datasets-server API with retries and exponential backoff."""
    import requests

    all_rows: list[dict] = []
    offset = 0
    limit = 100

    logger.info(f"Downloading UNFAIR-ToS '{split}' split from HuggingFace...")
    while True:
        url = (
            f"https://datasets-server.huggingface.co/rows"
            f"?dataset=coastalcph/lex_glue&config=unfair_tos&split={split}"
            f"&offset={offset}&limit={limit}"
        )
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200:
                    break
                logger.warning(
                    f"HTTP {resp.status_code} fetching offset {offset} (attempt {attempt + 1}/{max_retries})"
                )
            except Exception as exc:
                logger.warning(
                    f"Request error at offset {offset} (attempt {attempt + 1}/{max_retries}): {exc}"
                )
            time.sleep(backoff_factor * (attempt + 1))
        else:
            raise RuntimeError(
                f"Failed to fetch UNFAIR-ToS split '{split}' from HuggingFace at offset {offset} after {max_retries} attempts."
            )

        data = resp.json()
        rows = data.get("rows", [])
        if not rows:
            break

        for item in rows:
            row_data = item.get("row", {})
            all_rows.append(
                {
                    "row_idx": item.get("row_idx", len(all_rows)),
                    "text": row_data.get("text", "").strip(),
                    "labels": row_data.get("labels", []),
                }
            )

        offset += len(rows)
        if len(rows) < limit:
            break

    return all_rows


def load_unfair_tos(
    split: str = "test",
    limit: Optional[int] = None,
    cache_dir: Optional[Union[str, Path]] = None,
    allow_download: bool = True,
) -> list[UnfairTosSample]:
    """Load the UNFAIR-ToS dataset for evaluation.

    Args:
        split: Dataset split ('test', 'validation', 'train'). Default is 'test'.
        limit: Optional maximum number of samples to return.
        cache_dir: Custom directory for caching dataset files. Defaults to backend/evals/data.
        allow_download: If True, fetches from Hugging Face datasets-server if not cached locally.

    Returns:
        List of UnfairTosSample items with mapped categories.
    """
    data_dir = Path(cache_dir) if cache_dir else get_default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_file = data_dir / f"unfair_tos_{split}.json"

    raw_items: list[dict] = []

    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                raw_items = json.load(f)
        except Exception as exc:
            logger.warning(f"Failed to read cache file {cache_file}: {exc}")

    if not raw_items and allow_download:
        raw_items = fetch_from_hf_datasets_server(split=split)
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(raw_items, f, indent=2)
            logger.info(f"Cached {len(raw_items)} samples to {cache_file}")
        except Exception as exc:
            logger.warning(f"Could not write cache file {cache_file}: {exc}")

    if not raw_items:
        raise FileNotFoundError(
            f"UNFAIR-ToS dataset '{split}' split is not cached at {cache_file} and download was not completed."
        )

    if limit is not None and limit > 0:
        raw_items = raw_items[:limit]

    samples: list[UnfairTosSample] = []
    for idx, item in enumerate(raw_items):
        text = item.get("text", "").strip()
        labels = item.get("labels", [])
        sample_id = item.get("row_idx", idx)
        categories = map_labels_to_categories(labels)
        samples.append(
            UnfairTosSample(
                sample_id=sample_id,
                text=text,
                labels=labels,
                categories=categories,
            )
        )

    return samples
