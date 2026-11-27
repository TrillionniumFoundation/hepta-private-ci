#!/usr/bin/env python3
"""Reject mixed or weakened receipts from a real historical Cargo build."""
import argparse
import copy
import json
from pathlib import Path

from file_update_oracle import historical


def controls(record, output):
    historical.verify(record)
    output.mkdir(parents=True, exist_ok=False)
    results = []

    def check(name, alter, diagnostic):
        mutated = copy.deepcopy(record)
        alter(mutated)
        path = output / (name + "-record.json")
        path.write_text(json.dumps(mutated, indent=2) + "\n")
        try:
            historical.verify(mutated)
        except (RuntimeError, OSError, KeyError) as error:
            message = str(error)
            if diagnostic not in message:
                raise RuntimeError(name + " failed for an unexpected reason: " + message) from error
            results.append({"name": name, "rejected": True, "diagnostic": message,
                            "mutated_record": historical.bind(path)})
        else:
            raise RuntimeError("invalid historical qualification was accepted: " + name)

    def change_document(name, field, alter):
        def change(mutated):
            data = json.loads(Path(record[field]["path"]).read_text())
            alter(data)
            path = output / (name + ".json")
            path.write_text(json.dumps(data, indent=2) + "\n")
            mutated[field] = historical.bind(path)
        return change

    check("native-feature", lambda r: r.update(native_features_enabled=True),
          "missing successful historical Cargo")
    check("unapproved-codegen", lambda r: r.update(codegen_environment_overrides={"RUSTFLAGS": "-C overflow-checks=no"}),
          "compiler flags lack their explicit admission")
    check("different-original", lambda r: r["source"].update(commit="0" * 40),
          "unreviewed historical dependency baseline")
    check("unlocked-build", change_document("unlocked-build", "commands",
          lambda rows: rows[1]["argv"].remove("--locked")), "historical Cargo command")
    check("failed-build", change_document("failed-build", "commands",
          lambda rows: rows[1].update(returncode=7)), "historical dependency command failed")
    check("boolean-returncode", change_document("boolean-returncode", "commands",
          lambda rows: rows[1].update(returncode=False)), "historical dependency command failed")
    check("unbound-graph", change_document("unbound-graph", "graph",
          lambda graph: graph.update(artifact_jsonl_sha256="0" * 64)), "not bound to its successful Cargo output")
    check("wrong-native-owner", change_document("wrong-native-owner", "graph",
          lambda graph: graph["direct"]["codex_apply_patch"]["unit"].update(features=["hia-native"])),
          "another owner or native feature")
    check("wrong-target", lambda r: r.update(actual_target_directory=str(output)),
          "escaped the actual target directory")
    check("mixed-overflow-policy", change_document("mixed-overflow-policy", "graph",
          lambda graph: graph["direct"]["similar"]["unit"]["profile"].update(
              overflow_checks=not graph["direct"]["similar"]["unit"]["profile"]["overflow_checks"])),
          "profile or unit differs")
    check("changed-manifest", change_document("changed-manifest", "metadata",
          lambda metadata: next(iter(metadata["packages"].values())).update(manifest_sha256="0" * 64)),
          "historical dependency manifest changed")
    check("changed-package-version", change_document("changed-package-version", "metadata",
          lambda metadata: next(iter(metadata["packages"].values())).update(version="0.0.0-invented")),
          "source inventory differs from actual Cargo metadata")
    check("invented-unit", change_document("invented-unit", "graph",
          lambda graph: graph["units"][0].update(fingerprint_sha256="0" * 64)),
          "graph differs from the actual Cargo artifact stream")
    historical.verify(record)
    return {"schema": "codex.hia.historical-dependency-admission-controls.v1",
            "passed": True, "actual_original": record["source"],
            "actual_graph": record["graph"], "positive_unchanged": True,
            "rejections": results, "rejection_count": len(results)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise RuntimeError("refusing to replace an existing admission report")
    parent = json.loads(args.receipt.read_text())
    record = parent.get("dependency_baseline", parent.get("qualification"))
    if record is None:
        raise RuntimeError("the supplied actual build report has no historical dependency receipt")
    output = args.output_dir.resolve()
    original = Path(record["source"]["root"])
    if output.is_relative_to(original) or args.report.resolve().is_relative_to(original):
        raise RuntimeError("control artifacts must remain outside the immutable original")
    report = controls(record, output)
    report["input_receipt"] = historical.bind(args.receipt)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": True, "rejection_count": report["rejection_count"],
                      "report": str(args.report)}))


if __name__ == "__main__":
    main()
