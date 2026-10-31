"""Independent scalar and artifact census checks of a completed actual run."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit(protocol, directory):
    protocol, directory = Path(protocol), Path(directory)
    spec = json.loads(protocol.read_text())
    rows = json.loads((directory / "ROWS.json").read_text())
    result = json.loads((directory / "RESULTS.json").read_text())
    names = [arm["name"] for arm in spec["arms"]]
    expected = {(case, route, arm) for case in range(spec["pair_count"])
                for route in spec["routes"] for arm in names}
    actual = [(row["case"], row["route"], row["arm"]) for row in rows]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("Full registered source/route/arm Cartesian census differs")
    if result["protocol_sha256"] != sha(protocol) or result["rows_sha256"] != sha(directory / "ROWS.json"):
        raise ValueError("Completed report does not bind the exact protocol and outcome rows")
    source = None
    if spec["mode"] == "confirmation":
        source = json.loads(Path(spec["source_allocation"]).read_text())["roles"]["confirmation"]
        if len(set(row["cluster"] for row in rows)) != 85:
            raise ValueError("Confirmation did not preserve all 85 writer/speaker groups")
        counts = Counter((row["arm"], row["cluster"]) for row in rows)
        if len(counts) != len(names) * 85 or set(counts.values()) != {8}:
            raise ValueError("Every arm must retain all eight tasks in every writer/speaker group")
    file_paths, content = set(), {name: Counter() for name in ("text", "image", "audio", "video")}
    posteriors, infinite_nll, source_checks = 0, 0, 0
    for row in rows:
        record_path = Path(row["record"])
        record = json.loads(record_path.read_text())
        if record["summary"] != row:
            raise ValueError("Aggregate row does not equal its completed actual-output record")
        observation_path = record_path.parent / "TARGET_FREE_OBSERVATION.json"
        decision_path = record_path.parent / "PUBLIC_DECISION.json"
        if sha(observation_path) != record["observation_sha256"] or sha(decision_path) != record["public_decision_sha256"]:
            raise ValueError("Observation or pre-generation public decision identity changed")
        observed = json.loads(observation_path.read_text())
        public = json.loads(decision_path.read_text())
        scoring = record["private_scoring_after_observation"]
        target = scoring["expected_after_observation"]
        if source is not None:
            ordered = source["source_records"][2 * row["case"]:2 * row["case"] + 2]
            if row["public_swap_command"]:
                ordered = list(reversed(ordered))
            if target != [item["label"] for item in ordered]:
                raise ValueError("Offline scoring target differs from immutable source metadata and public command")
            if str(source["pair_writer_ids"][row["case"]]) != row["writer"]:
                raise ValueError("Writer assignment changed")
            source_checks += 1
        relation = "less" if target[0] < target[1] else "greater" if target[0] > target[1] else "equal"
        measured = {"text": observed["caption_digits"] == target and observed["caption_relation"] == relation,
                    "image": observed["image_digits"] == target,
                    "audio": observed["speech"]["predictions"]["consensus_or_single_v3"] == target,
                    "video": observed["video_digits"] == [digit for digit in target for _ in range(10)]}
        strict = all(measured.values()) and observed["content_checks"]["moving_video"] and observed["content_checks"]["nonempty_audio"]
        if observed["target_supplied"] or measured != row["modality_success"] or sum(measured.values()) / 4 != row["utility"] or strict != row["strict_success"]:
            raise ValueError("Independent scalar scoring differs from the actual target-free observation")
        if row["arm"] != "unchanged_full_reference":
            q = public["q"]
            if len(q) != 100 or any(not math.isfinite(p) or p < 0 for p in q) or abs(sum(q) - 1) > 1e-5:
                raise ValueError("Malformed public 100-target probability law")
            if public["action"] != max(range(100), key=lambda code: q[code]):
                raise ValueError("Selected action does not minimize the measured identity-table conditional moment")
            p = q[target[0] * 10 + target[1]]
            if p == 0:
                infinite_nll += 1
                if row["posterior_NLL"] is not None:
                    raise ValueError("A zero true-target probability has finite declared log score")
            elif abs(-math.log(p) - row["posterior_NLL"]) > 1e-10:
                raise ValueError("Proper log score changed")
            posteriors += 1
        route_index = ("image", "text", "audio", "video").index(row["route"])
        rotation = (row["case"] + 2 * route_index) % 8
        if (names.index(row["arm"]) - rotation) % 8 != row["physical_execution_order"]:
            raise ValueError("Actual execution order differs from its prospectively balanced schedule")
        for name, item in record["generation"]["output"]["files"].items():
            path = Path(item["path"])
            if not path.is_relative_to(directory) or path.is_symlink() or str(path) in file_paths:
                raise ValueError("Actual output path is shared, outside custody or symbolic")
            if path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
                raise ValueError("Actual generated output bytes changed")
            file_paths.add(str(path))
            content[name][item["sha256"]] += 1
    if len(file_paths) != 4 * len(expected):
        raise ValueError("The actual four-file physical output census is incomplete")
    video_inputs = 0
    if source is not None:
        for case in range(spec["pair_count"]):
            codec_path = directory / "input" / f"case-{case:03d}" / "video/video/INPUT_CODEC.json"
            codec = json.loads(codec_path.read_text())
            if not codec["lossless_roundtrip"] or sha(codec["path"]) != codec["sha256"]:
                raise ValueError("Actual formal video input codec receipt or bytes changed")
            video_inputs += 1
    return {"schema": "hepta.advance.joint-independent-record-audit.v1", "passed": True,
            "protocol_sha256": sha(protocol), "rows_sha256": sha(directory / "ROWS.json"),
            "complete_registered_cases": len(expected), "actual_output_files_checked": len(file_paths),
            "independent_scalar_rescores": len(rows), "registered_source_target_checks": source_checks,
            "posterior_and_selection_checks": posteriors, "infinite_log_score_cases": infinite_nll,
            "actual_input_videos_checked": video_inputs,
            "unique_output_content_sha256": {name: len(values) for name, values in content.items()},
            "duplicate_content_is_not_independent_evidence": True,
            "independent_observer_family_or_neural_rerun_claimed": False,
            "scope": "Independent scalar implementation and complete byte/record census; same underlying frozen observations"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.protocol, args.directory)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
