"""Check retained native bridge records; no model, Bellman or trajectory execution."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from verify_package import read, unique, invalid_constant


def verify(package):
    package = package.resolve(strict=True)
    manifest = read(package / "PACKAGE_SHA256.json")
    listed = {entry["path"] for entry in manifest["files"]}
    assert len(listed) == len(manifest["files"])
    actual = {path.relative_to(package).as_posix() for path in package.rglob("*")
              if path.is_file() and "__pycache__" not in path.parts}
    assert actual == listed | {"PACKAGE_SHA256.json"}
    for entry in manifest["files"]:
        path = package / entry["path"]
        assert not path.is_symlink() and path.resolve().is_relative_to(package)
        data = path.read_bytes()
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]

    def rows(kind):
        result = []
        groups = sorted((package / "replay_r1/run" / kind).glob("*.jsonl.gz"))
        assert len(groups) == 10
        for path in groups:
            group = [json.loads(line, object_pairs_hook=unique,
                                parse_constant=invalid_constant)
                     for line in gzip.decompress(path.read_bytes()).splitlines()]
            assert len(group) == 32
            result.extend(group)
        return result

    comparisons, replay = rows("comparisons"), rows("replay")
    summary_path = package / "replay_r1/run/RESULTS.json"
    summary = read(summary_path)
    assert len(comparisons) == len(replay) == summary["compared_worlds"] == 320
    assert summary["reevaluated_worlds"] == summary["planned_worlds"] == 320
    request_ids = {row["request_id"] for row in comparisons}
    assert len(request_ids) == 320
    assert request_ids == {row["request_id"] for row in replay}
    assert all(row["passed"] and not row["errors"] for row in comparisons)
    assert all(row["utility_passed"] for row in replay)
    assert sum(row["nodes"] for row in comparisons) == summary["total_compared_nodes"] == 246160
    assert sum(row["legal_Q_count"] for row in comparisons) == summary["total_compared_legal_Q"] == 928200
    for key in ("max_reference_Q_absolute_error", "max_scalar_graph_Q_absolute_error"):
        assert max(row[key] for row in comparisons) == summary[key] == 0
    assert all(abs(row["native_J"]["utility"] - row["scientific_J_utility"])
               == row["utility_absolute_error"] == 0 for row in replay)
    assert summary["max_utility_absolute_error"] == 0
    assert summary["passed"] and summary["native_execution_provenance_healthy"]
    assert summary["native_rpc_errors"] == 0
    for key in ("new_scientific_efficacy_qualification", "actual_packet_IO_qualified",
                "production_qualified", "full_economic_net_value_qualified"):
        assert summary[key] is False
    engineering = read(package / "ENGINEERING_QUALIFICATION.json")
    assert engineering["result_sha256"] == hashlib.sha256(summary_path.read_bytes()).hexdigest()
    assert engineering["native_mcp_graph_migration_qualified"]
    assert engineering["known_world_expected_trajectory_replay_qualified"]
    return {"schema": "hepta.wsp.native-record-review.v1", "passed": True,
            "files_including_manifest": len(actual), "worlds": 320,
            "nodes": 246160, "legal_Q": 928200,
            "reference_Q_max_error": 0, "scalar_Q_max_error": 0,
            "utility_max_error": 0,
            "source_result_sha256": engineering["result_sha256"],
            "scope": "Archive identity and saved comparison/replay consistency only. No independent reexecution of the frozen Q/mask/action verifier or trajectories; no new efficacy sample."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path,
                        default=Path(__file__).parent / "native_bellman_replay")
    print(json.dumps(verify(parser.parse_args().package), sort_keys=True))
