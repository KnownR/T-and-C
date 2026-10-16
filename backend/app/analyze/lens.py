"""Lens configuration loader and dynamic rubric builder.

Rule: The rubric is built entirely from the YAML lens file — no rubric hardcoded in Python.
"""

from pathlib import Path
from typing import Any
import yaml

LENSES_DIR = Path(__file__).resolve().parent.parent / "lenses"


def load_lens(lens_id: str = "tos") -> dict[str, Any]:
    """Load a lens configuration YAML file by ID (e.g. 'tos')."""
    lens_path = LENSES_DIR / f"{lens_id}.yaml"
    if not lens_path.exists():
        raise FileNotFoundError(f"Lens file not found at {lens_path}")

    with open(lens_path, "r", encoding="utf-8") as f:
        lens_data = yaml.safe_load(f)

    if not isinstance(lens_data, dict):
        raise ValueError(f"Invalid lens YAML format in {lens_path}")

    if "categories" not in lens_data or not isinstance(lens_data["categories"], list):
        raise ValueError(f"Lens YAML {lens_path} must specify a 'categories' list.")

    return lens_data


def build_rubric_prompt(lens_data: dict[str, Any]) -> str:
    """Dynamically construct the rubric description from the loaded YAML lens.

    No rubric categories or questions are hardcoded in Python.
    """
    categories = lens_data.get("categories", [])
    lens_name = lens_data.get("name", lens_data.get("id", "Analysis Lens"))
    lens_desc = lens_data.get("description", "")

    lines = [
        f"### Lens: {lens_name}",
        lens_desc,
        "",
        "Evaluate the document against the following predefined categories:",
        "",
    ]

    for cat in categories:
        cat_id = cat.get("id", "")
        name = cat.get("name", cat_id)
        default_sev = cat.get("default_severity", "yellow")
        question = cat.get("question", "")

        lines.append(f"- **Category `{cat_id}`** ({name}):")
        lines.append(f"  - Evaluation Question: {question}")
        lines.append(f"  - Default Severity: {default_sev}")
        lines.append("")

    return "\n".join(lines).strip()
