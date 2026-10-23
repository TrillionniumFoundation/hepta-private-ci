"""Reject marginal-preserving fixed-head improvement using saved mean bounds."""

import argparse
import hashlib
import json
from pathlib import Path
import resource


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / "runs/content-joint-train-v1-20261023/quality-summary.json"
    raw = source.read_bytes()
    quality = json.loads(raw)
    result = dict(scope="read-only bound on existing aggregate TRAIN means, no request or model call",
        bound="E joint_success <= E min(text_correct_probability,image_correct_probability) <= min(E text_correct_probability,E image_correct_probability)",
        source=str(source.relative_to(root)), source_sha256=hashlib.sha256(raw).hexdigest(),
        model_forwards=0, model_updates=0, real_requests=0, families={})
    for family in ("S", "H", "A", "N"):
        rows = [quality[family][f"independent-{seed}"] for seed in (11, 23, 47)]
        text = sum(row["KEEP"]["means"]["text_correct"] for row in rows) / 3
        image = sum(row["KEEP"]["means"]["image_correct"] for row in rows) / 3
        repaired = sum(row["log2"]["means"]["joint_success"] for row in rows) / 3
        upper = min(text, image)
        result["families"][family] = dict(mean_original_text_correct=text,
            mean_original_image_correct=image, any_marginal_preserving_joint_upper_bound=upper,
            existing_log2_joint_success=repaired, log2_above_upper_by=repaired - upper,
            marginal_preserving_fixed_head_candidate_rejected=repaired > upper)
    result["all_four_rejected_without_probe"] = all(x["marginal_preserving_fixed_head_candidate_rejected"] for x in result["families"].values())
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result["independent_review_CPU_before_receipt"] = usage.ru_utime + usage.ru_stime
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
