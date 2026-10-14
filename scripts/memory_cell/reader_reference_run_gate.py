"""Strict frozen-Reader run admission; failed jobs never become replay success.

A failed or cancelled generating workflow may still upload ZIPs. Those ZIPs
are *partial evidence*, never a completed multi-reader reference result.
This stdlib-only preflight creates an immutable failure reason before refusing
to launch any replay or independent verification.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

REPO = "TrillionniumFoundation/hepta-private-ci"
REQUIRED = {
    "smol": "memory-reader-reference-smol-1.7b",
    "qwen": "memory-reader-reference-qwen-3b",
}
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")


def _number(value):
    return type(value) is int and value > 0


def admit_run(run, metadata, *, expected_run_id, expected_source, inputs):
    if (
        not isinstance(run, dict)
        or not isinstance(metadata, dict)
        or not _number(expected_run_id)
        or not isinstance(expected_source, str)
        or HEX40.fullmatch(expected_source) is None
        or type(run.get("id")) is not int or run["id"] != expected_run_id
        or run.get("head_sha") != expected_source
        or run.get("run_attempt") != 1
        or run.get("name") != "MemoryCell fixed reader reference experiment"
        or not isinstance(inputs, dict)
        or not _number(inputs.get("id"))
        or not isinstance(inputs.get("sha"), str)
        or re.fullmatch(r"[0-9a-f]{64}", inputs["sha"]) is None
    ):
        raise ValueError("external exact model run/source/input identity drift")
    artifacts = metadata.get("artifacts")
    if (
        type(metadata.get("total_count")) is not int
        or not isinstance(artifacts, list)
        or not 0 <= metadata["total_count"] <= 100
        or len(artifacts) != metadata["total_count"]
    ):
        raise ValueError("incomplete or unbounded generating-run artifact metadata")

    by_name, ids = {}, set()
    for item in artifacts:
        if not isinstance(item, dict):
            raise ValueError("invalid frozen Reader artifact")
        ident, name, size, digest = (
            item.get("id"), item.get("name"), item.get("size_in_bytes"),
            item.get("digest"),
        )
        if (
            not _number(ident)
            or ident in ids or not isinstance(name, str) or not name
            or name in by_name
            or type(size) is not int or not 0 < size <= 64 * 1024 * 1024
            or not isinstance(digest, str) or re.fullmatch(
                r"sha256:[0-9a-f]{64}", digest
            ) is None
            or not isinstance(item.get("workflow_run"), dict)
            or item["workflow_run"].get("head_sha") != expected_source
        ):
            raise ValueError("ambiguous, unsigned or detached artifact metadata")
        by_name[name] = item
        ids.add(ident)

    blocked = []
    if run.get("status") != "completed":
        blocked.append("generating_run_not_completed")
    if run.get("conclusion") != "success":
        blocked.append("generating_run_not_successful")
    for name in REQUIRED.values():
        if name not in by_name:
            blocked.append("missing_required_model_artifact:" + name)
        elif by_name[name].get("expired") is not False:
            blocked.append("expired_required_model_artifact:" + name)
    eligible = not blocked
    observed = {
        short: (
            dict(
                id=by_name[name]["id"],
                sha256=by_name[name]["digest"][7:],
                size_bytes=by_name[name]["size_in_bytes"],
                expired=by_name[name].get("expired"),
            )
            if name in by_name else None
        )
        for short, name in REQUIRED.items()
    }
    specs = (
        {"inputs": dict(inputs)}
        | {
            key: dict(id=observed[key]["id"], sha=observed[key]["sha256"])
            for key in REQUIRED
        }
        if eligible else None
    )
    return dict(
        schema="hepta.reader-reference-generating-run-admission.v1",
        generating_run_id=expected_run_id,
        generating_source=expected_source,
        generating_status=run.get("status"),
        generating_conclusion=run.get("conclusion"),
        required_model_artifacts=observed,
        eligible_for_complete_replay=eligible,
        replay_download_pins=specs,
        blocked_reasons=blocked,
        available_zip_does_not_prove_original_run_success=True,
        prior_model_answers_not_re_generated=True,
        independent_semantic_sufficiency_certified=False,
        production_accepted=False,
    )


def _read(path):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 4 * 1024 * 1024:
        raise ValueError("bounded non-symlink GitHub metadata file required")
    raw = path.read_bytes()
    def unique(pairs):
        d = {}
        for key, value in pairs:
            if key in d:
                raise ValueError("duplicate GitHub metadata field")
            d[key] = value
        return d
    return json.loads(raw, object_pairs_hook=unique), hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--downloads", required=True, type=Path)
    parser.add_argument("--pins", required=True, type=Path)
    parser.add_argument("--expected-id", required=True, type=int)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--inputs-id", required=True, type=int)
    parser.add_argument("--inputs-sha256", required=True)
    args = parser.parse_args()
    run, run_sha = _read(args.run)
    metadata, metadata_sha = _read(args.artifacts)
    outcome = admit_run(
        run, metadata, expected_run_id=args.expected_id,
        expected_source=args.expected_source,
        inputs=dict(id=args.inputs_id, sha=args.inputs_sha256),
    )
    outcome["run_metadata_sha256"] = run_sha
    outcome["artifact_metadata_sha256"] = metadata_sha
    with args.report.open("x", encoding="utf-8") as dest:
        json.dump(outcome, dest, indent=2, sort_keys=True, allow_nan=False)
        dest.write("\n")
    if not outcome["eligible_for_complete_replay"]:
        raise SystemExit("Unqualified original model execution: " +
                         ", ".join(outcome["blocked_reasons"]))
    with args.pins.open("x", encoding="utf-8") as dest:
        json.dump(outcome["replay_download_pins"], dest, indent=2, sort_keys=True)
        dest.write("\n")
    with args.downloads.open("x", encoding="utf-8") as dest:
        for key in ("inputs", "smol", "qwen"):
            pin = outcome["replay_download_pins"][key]
            dest.write(f"{key}\t{pin['id']}\t{pin['sha']}\n")


if __name__ == "__main__":
    main()
