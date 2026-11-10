"""Read-only attribution of the two bound MEM delivery failures; no actor rerun."""

import hashlib
import json
from pathlib import Path

ROOT = Path("/home/qq/mem-candidate-retention-20261109-a6b21bc7/run-002")
MATERIALS = Path("/home/qq/ndu-real-materials-20261107-audit-bffe40c2")
SOURCE = ROOT.parent / "source-v2/scripts/ndu_real_materials/evaluator.py"
EXPECTED = {
    "REPORT.json": "465334e5483e263af09e68d232d08047507841c49a84e7154466b3527f12f8e3",
    "PLAN.json": "488639ca2bd2b25d5c90c77b3adaf58bd8133932bb2cb1bf70fc547447d187d5",
    "EVIDENCE.json": "eb2c4b21fd2c91005af23c61e9a8e2ffd992817815763b25ad693587eb3de009",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def bound(base, binding):
    path = base / binding["path"]
    if not path.resolve().is_relative_to(base.resolve()):
        raise ValueError("path outside original evidence root")
    data = path.read_bytes()
    if len(data) != binding["bytes"] or digest(data) != binding["sha256"]:
        raise ValueError("bound bytes differ: " + binding["path"])
    return data


def geometry(box, target):
    area = (box[2] - box[0]) * (box[3] - box[1])
    target_area = (target[2] - target[0]) * (target[3] - target[1])
    intersection = max(0, min(box[2], target[2]) - max(box[0], target[0])) * max(
        0, min(box[3], target[3]) - max(box[1], target[1])
    )
    return intersection / (
        area + target_area - intersection
    ), intersection / target_area


def main():
    objects, identities = {}, {}
    for name, expected in EXPECTED.items():
        data = (ROOT / name).read_bytes()
        if digest(data) != expected:
            raise ValueError("original top-level identity differs: " + name)
        objects[name] = json.loads(data)
        identities[name] = {"bytes": len(data), "sha256": digest(data)}
    report, plan, evidence = [
        objects[n] for n in ("REPORT.json", "PLAN.json", "EVIDENCE.json")
    ]
    if (
        report["plan_sha256"] != EXPECTED["PLAN.json"]
        or report["evidence_sha256"] != EXPECTED["EVIDENCE.json"]
        or evidence["plan_sha256"] != EXPECTED["PLAN.json"]
    ):
        raise ValueError("top-level chain differs")
    index_data = (MATERIALS / "private/reference-index.v2.json").read_bytes()
    if digest(index_data) != plan["reference_index_sha256"]:
        raise ValueError("reference index differs")
    index = json.loads(index_data)
    rubric_data = bound(MATERIALS, index["rubric"])
    if digest(rubric_data) != plan["rubric_sha256"]:
        raise ValueError("rubric differs")
    evaluator_data = SOURCE.read_bytes()
    if digest(evaluator_data) != plan["evaluator_sha256"]:
        raise ValueError("evaluator source differs")
    # This exact frozen source provides these image-pass thresholds.
    if b"coverage >= 0.95 and image_quality >= 0.5" not in evaluator_data:
        raise ValueError("frozen image threshold source differs")
    failures = []
    for row in report["episodes"]:
        if row.get("failure_stage") != "delivery_failure":
            continue
        entry = next(
            e
            for e in evidence["episodes"]
            if e["original_operation_id"] == row["original_operation_id"]
        )
        result = json.loads(bound(ROOT, entry["result"]))
        trajectory = json.loads(bound(ROOT, entry["trajectory"]))
        packet = json.loads(bound(ROOT, entry["public_case"]))
        final = json.loads(bound(ROOT, entry["final_delivery"]))
        score = result["score_components"]
        if (
            score["delivery_sha256"] != entry["final_delivery"]["sha256"]
            or score["evaluator_source_sha256"] != plan["evaluator_sha256"]
            or score["rubric_sha256"] != plan["rubric_sha256"]
        ):
            raise ValueError("score identity differs")
        ref_binding = index["cases"][row["case_id"]]
        reference = json.loads(bound(MATERIALS, ref_binding))
        if (
            score["reference_sha256"] != ref_binding["sha256"]
            or reference["role"] != "development"
            or index["case_roles"][row["case_id"]] != "development"
        ):
            raise ValueError("reference identity or evaluation role differs")
        image_root = (ROOT / entry["final_delivery"]["path"]).parent
        delivered = bound(image_root, final["image"])
        source = bound(MATERIALS, reference["source_image"])
        quality, coverage = max(
            geometry(final["image"]["bbox"], target)
            for target in reference["target_boxes"]
        )
        if (
            quality != score["image_quality"]
            or coverage != score["image_target_coverage"]
        ):
            raise ValueError("independent geometry differs from original score")
        if not (
            row["selected"] is True
            and row["wrote_selected_candidate"] is True
            and packet["requirements"] == {"image": True, "text": True}
            and score["text_quality"] == 1.0
            and score["committed_output_preserved"] is True
            and score["image_pixels_verified"] is True
            and quality >= 0.5
            and coverage < 0.95
            and score["image_pass"] is False
        ):
            raise ValueError("failure does not isolate image coverage")
        failures.append(
            {
                "operation_id": row["original_operation_id"],
                "case_id": row["case_id"],
                "mode": row["mode"],
                "pair_id": row["pair_id"],
                "result_binding": entry["result"],
                "trajectory_binding": entry["trajectory"],
                "delivery_binding": entry["final_delivery"],
                "reference_binding": ref_binding,
                "public_case_binding": entry["public_case"],
                "reference_target_boxes": reference["target_boxes"],
                "delivered_bbox": final["image"]["bbox"],
                "source_image_sha256": digest(source),
                "delivered_image_sha256": digest(delivered),
                "actions": [s["action"]["action"] for s in trajectory["steps"]],
                "original_score_components": score,
                "independent_geometry": {
                    "image_quality": quality,
                    "target_coverage": coverage,
                },
                "failure_subcriterion": "image_target_coverage_below_0.95",
            }
        )
    pairs = {}
    for row in report["episodes"]:
        pairs.setdefault(row["pair_id"], {})[row["mode"]] = row
    gained, common, transitions = [], [], {}
    for key, pair in pairs.items():
        left, right = pair["current_only"], pair["bounded"]
        if left["available"] is False and right["available"] is True:
            gained.append(
                {
                    "pair_id": key,
                    "left_selected": left["selected"],
                    "right_selected": right["selected"],
                }
            )
        if left["available"] is True and right["available"] is True:
            common.append(key)
            transition = str(left["selected"]) + "->" + str(right["selected"])
            transitions[transition] = transitions.get(transition, 0) + 1
    if len(failures) != 2 or len({x["pair_id"] for x in failures}) != 1:
        raise ValueError("unexpected failure roster")
    print(
        json.dumps(
            {
                "schema": "hepta.mem.delivery-subcriterion-readback.v1",
                "source_execution_commit": plan["source_commit"],
                "top_level_identities": identities,
                "reference_index_sha256": plan["reference_index_sha256"],
                "evaluator_sha256": plan["evaluator_sha256"],
                "rubric_sha256": plan["rubric_sha256"],
                "source_paths": {
                    "run_root": str(ROOT),
                    "material_root": str(MATERIALS),
                    "evaluator": str(SOURCE),
                },
                "failures": failures,
                "newly_available_pairs": gained,
                "common_availability_pair_count": len(common),
                "common_availability_selected_transitions": transitions,
                "limits": [
                    "post-hoc readback of exposed development evidence; not independent confirmation",
                    "geometry and bound image bytes rechecked; pixel decoding and scorer not rerun",
                    "original image_pixels_verified receipt retained; execution authenticity not established",
                    "common availability does not mean identical offered candidate rosters",
                ],
                "actor_rerun": False,
                "learning_performed": False,
                "scientific_acceptance": "HOLD",
                "production_adoption": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
