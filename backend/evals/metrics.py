"""Evaluation metrics computation: precision, recall, F1, micro/macro averages, and grounding rates."""

from typing import Any, Iterable, Optional
from pydantic import BaseModel, Field

from backend.evals.datasets.unfair_tos import ALL_CATEGORIES, CATEGORY_NAMES


class CategoryMetric(BaseModel):
    category: str
    name: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    support: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0


class EvalMetricsReport(BaseModel):
    dataset: str = "unfair_tos"
    split: str = "test"
    model: str = "unknown"
    lens_id: str = "tos"
    lens_version: int = 1
    sample_count: int = 0
    positive_samples: int = 0
    negative_samples: int = 0
    per_category: dict[str, CategoryMetric] = Field(default_factory=dict)
    macro_precision: float = 0.0
    macro_recall: float = 0.0
    macro_f1: float = 0.0
    micro_precision: float = 0.0
    micro_recall: float = 0.0
    micro_f1: float = 0.0
    total_proposed: int = 0
    total_verified: int = 0
    total_rejected: int = 0
    grounding_rate: float = 1.0
    avg_latency_ms: float = 0.0

    def format_table(self) -> str:
        """Render a formatted ASCII table of the evaluation results."""
        lines = []
        lines.append(f"\n=========================================================================================")
        lines.append(f" Benchmark Evaluation Results: {self.dataset} ({self.split}) | Model: {self.model}")
        lines.append(f" Total Samples: {self.sample_count} (Unfair: {self.positive_samples}, Neutral: {self.negative_samples})")
        lines.append(f"=========================================================================================")
        header = f"{'Category':<32} | {'Support':>7} | {'Precision':>9} | {'Recall':>9} | {'F1-Score':>9} | {'TP':>4} | {'FP':>4} | {'FN':>4}"
        sep = "-" * len(header)
        lines.append(header)
        lines.append(sep)

        for cat_id in ALL_CATEGORIES:
            m = self.per_category.get(cat_id)
            if not m:
                continue
            cat_display = CATEGORY_NAMES.get(cat_id, cat_id)
            lines.append(
                f"{cat_display:<32} | {m.support:>7} | {m.precision:>8.1%} | {m.recall:>8.1%} | {m.f1:>8.1%} | {m.tp:>4} | {m.fp:>4} | {m.fn:>4}"
            )

        lines.append(sep)
        lines.append(
            f"{'Micro Average':<32} | {sum(m.support for m in self.per_category.values()):>7} | {self.micro_precision:>8.1%} | {self.micro_recall:>8.1%} | {self.micro_f1:>8.1%} |"
        )
        lines.append(
            f"{'Macro Average':<32} | {sum(m.support for m in self.per_category.values()):>7} | {self.macro_precision:>8.1%} | {self.macro_recall:>8.1%} | {self.macro_f1:>8.1%} |"
        )
        lines.append(f"=========================================================================================")
        lines.append(
            f" Grounding Metrics: Proposed: {self.total_proposed} | Verified: {self.total_verified} | Rejected: {self.total_rejected} | Grounding Rate: {self.grounding_rate * 100:.1f}%"
        )
        lines.append(f" Average Latency:   {self.avg_latency_ms:.1f} ms/sample")
        lines.append(f"=========================================================================================\n")
        return "\n".join(lines)


def compute_metrics(
    records: Iterable[Any],
    dataset: str = "unfair_tos",
    split: str = "test",
    model: str = "unknown",
    lens_id: str = "tos",
    lens_version: int = 1,
    categories: Optional[list[str]] = None,
) -> EvalMetricsReport:
    """Compute per-category precision, recall, F1 and micro/macro averages across evaluation runs.

    Args:
        records: Collection of records having fields or dict keys:
                 ground_truth (set/list/json string of category IDs),
                 predicted (set/list/json string of category IDs),
                 verified_count, rejected_count, latency_ms.
        dataset: Dataset identifier.
        split: Dataset split.
        model: Model name.
        lens_id: Lens configuration ID.
        lens_version: Lens version integer.
        categories: Category list to evaluate (defaults to ALL_CATEGORIES).

    Returns:
        EvalMetricsReport populated with full evaluation metrics.
    """
    import json

    cat_list = categories or ALL_CATEGORIES
    per_cat_stats: dict[str, dict[str, int]] = {
        cat: {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "support": 0} for cat in cat_list
    }

    total_samples = 0
    positive_samples = 0
    negative_samples = 0

    total_proposed = 0
    total_verified = 0
    total_rejected = 0
    total_latency = 0.0

    for rec in records:
        total_samples += 1

        # Extract ground truth categories
        gt_raw = (
            rec.get("ground_truth") if isinstance(rec, dict) else getattr(rec, "ground_truth", [])
        )
        if isinstance(gt_raw, str):
            try:
                gt_set = set(json.loads(gt_raw))
            except Exception:
                gt_set = set()
        elif isinstance(gt_raw, (list, set, tuple)):
            gt_set = set(gt_raw)
        else:
            gt_set = set()

        # Extract predicted categories
        pred_raw = rec.get("predicted") if isinstance(rec, dict) else getattr(rec, "predicted", [])
        if isinstance(pred_raw, str):
            try:
                pred_set = set(json.loads(pred_raw))
            except Exception:
                pred_set = set()
        elif isinstance(pred_raw, (list, set, tuple)):
            pred_set = set(pred_raw)
        else:
            pred_set = set()

        if gt_set:
            positive_samples += 1
        else:
            negative_samples += 1

        # Grounding counts
        ver_count = (
            rec.get("verified_count", 0)
            if isinstance(rec, dict)
            else getattr(rec, "verified_count", 0)
        )
        rej_count = (
            rec.get("rejected_count", 0)
            if isinstance(rec, dict)
            else getattr(rec, "rejected_count", 0)
        )
        total_verified += ver_count
        total_rejected += rej_count
        total_proposed += ver_count + rej_count

        lat = (
            rec.get("latency_ms", 0.0)
            if isinstance(rec, dict)
            else getattr(rec, "latency_ms", 0.0)
        )
        total_latency += lat

        # Update per-category confusion matrix
        for cat in cat_list:
            is_gt = cat in gt_set
            is_pred = cat in pred_set

            if is_gt:
                per_cat_stats[cat]["support"] += 1
                if is_pred:
                    per_cat_stats[cat]["tp"] += 1
                else:
                    per_cat_stats[cat]["fn"] += 1
            else:
                if is_pred:
                    per_cat_stats[cat]["fp"] += 1
                else:
                    per_cat_stats[cat]["tn"] += 1

    per_category: dict[str, CategoryMetric] = {}
    macro_p_sum = 0.0
    macro_r_sum = 0.0
    macro_f1_sum = 0.0

    total_tp = 0
    total_fp = 0
    total_fn = 0

    for cat in cat_list:
        stats = per_cat_stats[cat]
        tp = stats["tp"]
        fp = stats["fp"]
        fn = stats["fn"]
        tn = stats["tn"]
        support = stats["support"]

        total_tp += tp
        total_fp += fp
        total_fn += fn

        prec = (tp / (tp + fp)) if (tp + fp) > 0 else 0.0
        rec = (tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0

        macro_p_sum += prec
        macro_r_sum += rec
        macro_f1_sum += f1

        per_category[cat] = CategoryMetric(
            category=cat,
            name=CATEGORY_NAMES.get(cat, cat),
            tp=tp,
            fp=fp,
            fn=fn,
            tn=tn,
            support=support,
            precision=prec,
            recall=rec,
            f1=f1,
        )

    num_cats = len(cat_list)
    macro_p = (macro_p_sum / num_cats) if num_cats > 0 else 0.0
    macro_r = (macro_r_sum / num_cats) if num_cats > 0 else 0.0
    macro_f1 = (macro_f1_sum / num_cats) if num_cats > 0 else 0.0

    micro_p = (total_tp / (total_tp + total_fp)) if (total_tp + total_fp) > 0 else 0.0
    micro_r = (total_tp / (total_tp + total_fn)) if (total_tp + total_fn) > 0 else 0.0
    micro_f1 = (2 * micro_p * micro_r / (micro_p + micro_r)) if (micro_p + micro_r) > 0 else 0.0

    grounding_rate = (total_verified / total_proposed) if total_proposed > 0 else 1.0
    avg_latency = (total_latency / total_samples) if total_samples > 0 else 0.0

    return EvalMetricsReport(
        dataset=dataset,
        split=split,
        model=model,
        lens_id=lens_id,
        lens_version=lens_version,
        sample_count=total_samples,
        positive_samples=positive_samples,
        negative_samples=negative_samples,
        per_category=per_category,
        macro_precision=macro_p,
        macro_recall=macro_r,
        macro_f1=macro_f1,
        micro_precision=micro_p,
        micro_recall=micro_r,
        micro_f1=micro_f1,
        total_proposed=total_proposed,
        total_verified=total_verified,
        total_rejected=total_rejected,
        grounding_rate=grounding_rate,
        avg_latency_ms=avg_latency,
    )
