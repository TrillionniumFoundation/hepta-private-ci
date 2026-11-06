"""Compare two already archived runs; no scientific source or model is executed."""
import datetime
import json

from recalculate_frozen_records import ROOT, PKG, RUN, READS, read, raw, sha, canonical

TRAJECTORY_RESOURCES = {
    "arm_initialization_cpu_seconds", "cpu_seconds", "wall_seconds",
    "full_cold_preparation_cpu_seconds", "full_cold_preparation_wall_seconds",
    "policy_cpu_seconds", "verification_cpu_seconds", "world_feature_cpu_seconds",
}
SUMMARY_RESOURCES = {"cpu_seconds", "wall_seconds", "peak_rss_bytes"}


def remove_resources(value, excluded):
    if isinstance(value, list):
        return [remove_resources(x, excluded) for x in value]
    if isinstance(value, dict):
        return {key: remove_resources(item, excluded) for key, item in value.items() if key not in excluded}
    return value


def main():
    replay = PKG / "independent_replay/attempt_2/run"
    published = read(PKG / "independent_replay/attempt_2/COMPARISON.json")
    original_checks = {x["path"]: x for x in published["comparisons"]}
    assert len(original_checks) == 77
    assert sorted(TRAJECTORY_RESOURCES) == published["trajectory_resource_fields_excluded"]
    assert sorted(SUMMARY_RESOURCES) == published["summary_resource_fields_excluded"]
    groups = [(sorted((RUN / "models").glob("*.json.gz")), set(), "model"),
              (sorted((RUN / "worlds").glob("*.json.gz")), set(), "world"),
              (sorted(RUN.glob("*_RESULTS.json.gz")), TRAJECTORY_RESOURCES, "trajectory"),
              ([RUN / "RESULTS.json"], SUMMARY_RESOURCES, "summary"),
              ([RUN / "ALL_GATES_BEFORE_TEST.json"], set(), "gate")]
    assert [len(g[0]) for g in groups] == [35, 20, 20, 1, 1]
    checks = []
    for files, excluded, category in groups:
        for first in files:
            relative = first.relative_to(RUN).as_posix()
            second = replay / relative
            old, new = remove_resources(read(first), excluded), remove_resources(read(second), excluded)
            assert old == new, relative
            check = {"path": relative, "category": category,
                     "original_file_sha256": sha(raw(first)), "replay_file_sha256": sha(raw(second)),
                     "compared_semantic_sha256": sha(canonical(old)), "exact_json_equal": True}
            assert check == original_checks[relative]
            checks.append(check)
    result = {"schema": "hepta.pr4823.independent-comparison-of-archived-replay.v1",
              "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "passed": True, "comparisons": checks, "count": len(checks),
              "trajectory_resource_fields_excluded": sorted(TRAJECTORY_RESOURCES),
              "summary_resource_fields_excluded": sorted(SUMMARY_RESOURCES),
              "numerical_tolerance": 0, "input_identities": READS,
              "this_audit_executed_models_or_environment": False,
              "original_replay_independent_implementation": False, "new_holdout": False,
              "scope": "Both frozen runs compare exactly as stored JSON after only the original enumerated resource omissions; this audit reads their existing records, not a third execution."}
    (ROOT / "independent-replay-comparison.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print(json.dumps({"passed": True, "comparisons": len(checks), "new_model_execution": False}))


if __name__ == "__main__":
    main()
