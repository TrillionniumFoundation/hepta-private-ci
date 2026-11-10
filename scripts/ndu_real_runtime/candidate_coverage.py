"""Pinned, source-balanced candidate diagnostics on registered train/dev states.

Inputs contain identities and selection evidence, never candidate/reference text.
Missing evidence remains unknown; this does not authenticate labels or establish
new-task policy benefit. State inventories must be frozen before this diagnostic.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

SCHEMA = "ndu.ctrl.candidate-coverage-manifest.v1"
ROLES = {"train", "development"}
BINDINGS = {
    "generator_sha256",
    "selector_sha256",
    "normalizer_sha256",
    "observation_contract_sha256",
}
MAX_STATES = 8192
MAX_RECORDS = 16384
MAX_BYTES = 64 * 1024 * 1024


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    )


def _identity(value):
    return type(value) is str and 0 < len(value.encode()) <= 512


def _pin(value):
    return (
        type(value) is str
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _mean(values):
    return None if any(v is None for v in values) else math.fsum(values) / len(values)


def _candidates(value, cap):
    if value is None:
        return None
    if type(value) is not dict or set(value) != {
        "sha256",
        "count",
        "positive_indices",
        "selection",
        "pre_cap_unique_count",
    }:
        raise ValueError("COVERAGE_CANDIDATE_SCHEMA")
    count = value["count"]
    if not _pin(value["sha256"]) or type(count) is not int or not 0 <= count <= cap:
        raise ValueError("COVERAGE_CANDIDATE_BOUND")
    positive, selection, before = (
        value["positive_indices"],
        value["selection"],
        value["pre_cap_unique_count"],
    )
    if positive is not None and (
        type(positive) is not list
        or any(type(i) is not int or not 0 <= i < count for i in positive)
        or len(set(positive)) != len(positive)
    ):
        raise ValueError("COVERAGE_POSITIVE_INDEX")
    if selection is not None and (
        type(selection) is not dict
        or set(selection) != {"index"}
        or selection["index"] is not None
        and (type(selection["index"]) is not int or not 0 <= selection["index"] < count)
    ):
        raise ValueError("COVERAGE_SELECTION")
    # This is the count after deduplication, immediately before the stated cap.
    # Exactly cap candidates alone cannot establish whether truncation occurred.
    if before is not None and (
        type(before) is not int
        or not 0 <= before <= 1000000
        or count != min(before, cap)
    ):
        raise ValueError("COVERAGE_PRE_CAP_COUNT")
    return {**value, "positive_indices": None if positive is None else sorted(positive)}


def summarize(records, sources, *, bindings, candidate_cap=128):
    """Count every registered source/state once; incomplete full-cohort means are null.

    sources: [{source_id, role, state_ids: [SHA256, ...]}, ...].
    records: [{source_id, role, state_id, observation_id, observation_sha256,
               generator_sha256, bindings_sha256, candidates}, ...].
    candidates=None means missing evidence; positive_indices=None means unknown
    labels. selection=None means missing selection, while {index: None} records
    an observed abstention. Hash pins bind supplied bytes, not observer authority.
    """
    if (
        type(bindings) is not dict
        or set(bindings) != BINDINGS
        or not all(_pin(v) for v in bindings.values())
        or type(candidate_cap) is not int
        or not 1 <= candidate_cap <= 128
    ):
        raise ValueError("COVERAGE_BINDING_OR_CAP")
    binding_digest = digest(bindings)
    if type(sources) is not list or not 1 <= len(sources) <= 4096:
        raise ValueError("COVERAGE_SOURCE_INVENTORY")
    registry, planned = {}, set()
    for source in sources:
        if type(source) is not dict or set(source) != {
            "source_id",
            "role",
            "state_ids",
        }:
            raise ValueError("COVERAGE_SOURCE_SCHEMA")
        sid, role, states = source["source_id"], source["role"], source["state_ids"]
        if (
            not _identity(sid)
            or sid in registry
            or type(role) is not str
            or role not in ROLES
            or type(states) is not list
            or not 1 <= len(states) <= MAX_STATES
            or not all(_pin(s) for s in states)
            or len(set(states)) != len(states)
        ):
            raise ValueError("COVERAGE_SOURCE_ROLE_OR_STATES")
        registry[sid] = source
        planned.update((sid, state) for state in states)
        if len(planned) > MAX_STATES:
            raise ValueError("COVERAGE_STATE_BOUND")
    if type(records) is not list or len(records) > MAX_RECORDS:
        raise ValueError("COVERAGE_RECORD_BOUND")
    unique, observations = {}, {}
    fields = {
        "source_id",
        "role",
        "state_id",
        "observation_id",
        "observation_sha256",
        "generator_sha256",
        "bindings_sha256",
        "candidates",
    }
    for row in records:
        if type(row) is not dict or set(row) != fields:
            raise ValueError("COVERAGE_RECORD_SCHEMA")
        key = row["source_id"], row["state_id"]
        if (
            not all(_identity(v) for v in key)
            or key not in planned
            or type(row["role"]) is not str
            or row["role"] not in ROLES
            or row["role"] != registry[key[0]]["role"]
            or not _identity(row["observation_id"])
            or not _pin(row["observation_sha256"])
            or row["generator_sha256"] != bindings["generator_sha256"]
            or row["bindings_sha256"] != binding_digest
        ):
            raise ValueError("COVERAGE_RECORD_IDENTITY_OR_ROLE")
        candidate = _candidates(row["candidates"], candidate_cap)
        normalized = {**row, "candidates": candidate}
        oid = row["observation_id"]
        if oid in observations and observations[oid] != normalized:
            raise ValueError("COVERAGE_OBSERVATION_ID_REUSED")
        observations[oid] = normalized
        # Several observations may repeat one state. Different evidence for that
        # state cannot overwrite a failure, unknown label, or selected result.
        if key in unique and unique[key] != candidate:
            raise ValueError("COVERAGE_STATE_EVIDENCE_CONFLICT")
        unique[key] = candidate
    by_source = []
    for sid, source in registry.items():
        values = [unique.get((sid, state)) for state in source["state_ids"]]
        coverage, accuracy, truncation = [], [], []
        for value in values:
            positive = None if value is None else value["positive_indices"]
            selected = None if value is None else value["selection"]
            coverage.append(None if positive is None else float(bool(positive)))
            accuracy.append(
                None
                if positive is None or selected is None
                else float(
                    selected["index"] is not None and selected["index"] in positive
                )
            )
            truncation.append(
                None
                if value is None or value["pre_cap_unique_count"] is None
                else value["pre_cap_unique_count"] > value["count"]
            )
        ceiling, selected_accuracy = _mean(coverage), _mean(accuracy)
        by_source.append(
            {
                "source_id_sha256": digest(sid),
                "role": source["role"],
                "registered_states": len(values),
                "observed_states": sum((sid, s) in unique for s in source["state_ids"]),
                "missing_states": sum(
                    (sid, s) not in unique for s in source["state_ids"]
                ),
                "candidate_evidence_unknown": sum(v is None for v in values),
                "coverage_unknown": coverage.count(None),
                "selection_unknown": accuracy.count(None),
                "known_uncovered_states": coverage.count(0.0),
                "known_selection_errors_on_covered_states": sum(
                    c == 1.0 and a == 0.0 for c, a in zip(coverage, accuracy)
                ),
                "empty_candidate_sets": sum(
                    v is not None and v["count"] == 0 for v in values
                ),
                "at_cap_states": sum(
                    v is not None and v["count"] == candidate_cap for v in values
                ),
                "known_truncated_states": truncation.count(True),
                "truncation_unknown": truncation.count(None),
                "oracle_ceiling": ceiling,
                "selected_accuracy": selected_accuracy,
                "selection_gap": None
                if ceiling is None or selected_accuracy is None
                else ceiling - selected_accuracy,
            }
        )
    means = {
        name: _mean([s[name] for s in by_source])
        for name in ("oracle_ceiling", "selected_accuracy", "selection_gap")
    }
    return {
        "schema": "ndu.ctrl.candidate-coverage-report.v1",
        "bindings": dict(bindings),
        "candidate_cap": candidate_cap,
        "source_inventory_sha256": digest(sources),
        "records_sha256": digest(records),
        "registered_sources": len(sources),
        "registered_states": len(planned),
        "observed_sources": len({key[0] for key in unique}),
        "missing_sources": len(registry) - len({key[0] for key in unique}),
        "input_records": len(records),
        "unique_observations": len(observations),
        "observed_states": len(unique),
        "duplicate_state_records": len(records) - len(unique),
        "source_equal_means": means,
        "sources": sorted(by_source, key=lambda s: s["source_id_sha256"]),
        "scope": "registered_train_development_states_only",
        "observer_authenticated": False,
        "new_independent_tasks": 0,
        "policy_efficacy_evaluated": False,
        "production_admission": False,
    }


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("COVERAGE_DUPLICATE_JSON_FIELD")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("COVERAGE_NONFINITE_JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def read_pin(root, pin):
    if (
        type(pin) is not dict
        or set(pin) != {"path", "bytes", "sha256"}
        or not _identity(pin["path"])
        or not _pin(pin["sha256"])
        or type(pin["bytes"]) is not int
        or not 0 <= pin["bytes"] <= MAX_BYTES
    ):
        raise ValueError("COVERAGE_FILE_PIN")
    relative, base = Path(pin["path"]), Path(root).resolve(strict=True)
    if relative.is_absolute() or any(p in {".", ".."} for p in relative.parts):
        raise ValueError("COVERAGE_INPUT_PATH")
    path = base
    for part in relative.parts:
        path /= part
        if path.is_symlink():
            raise ValueError("COVERAGE_INPUT_SYMLINK")
    if not path.is_file() or not path.resolve(strict=True).is_relative_to(base):
        raise ValueError("COVERAGE_INPUT_FILE")
    with path.open("rb") as stream:
        raw = stream.read(pin["bytes"] + 1)
    if len(raw) != pin["bytes"] or sha(raw) != pin["sha256"]:
        raise ValueError("COVERAGE_INPUT_PIN_MISMATCH")
    return raw


def audit(root, manifest_raw, expected_manifest_sha256):
    if (
        len(manifest_raw) > 2 * 1024 * 1024
        or sha(manifest_raw) != expected_manifest_sha256
    ):
        raise ValueError("COVERAGE_MANIFEST_PIN_MISMATCH")
    manifest = _json(manifest_raw)
    if (
        type(manifest) is not dict
        or set(manifest)
        != {
            "schema",
            "sources",
            "bindings",
            "candidate_cap",
            "records",
            "diagnostic_sha256",
        }
        or manifest["schema"] != SCHEMA
        or manifest["diagnostic_sha256"] != sha(Path(__file__).read_bytes())
    ):
        raise ValueError("COVERAGE_MANIFEST_SCHEMA_OR_SOURCE")
    # Reject unregistered roles and malformed inventories before opening records.
    summarize(
        [],
        manifest["sources"],
        bindings=manifest["bindings"],
        candidate_cap=manifest["candidate_cap"],
    )
    raw = read_pin(root, manifest["records"])
    lines = raw.splitlines()
    if len(lines) > MAX_RECORDS or any(not line or len(line) > 65536 for line in lines):
        raise ValueError("COVERAGE_JSONL_BOUND")
    report = summarize(
        [_json(line) for line in lines],
        manifest["sources"],
        bindings=manifest["bindings"],
        candidate_cap=manifest["candidate_cap"],
    )
    report.update(
        manifest_sha256=expected_manifest_sha256,
        diagnostic_sha256=manifest["diagnostic_sha256"],
        records_file_sha256=manifest["records"]["sha256"],
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.manifest.is_symlink():
            raise ValueError("COVERAGE_MANIFEST_SYMLINK")
        with args.manifest.open("rb") as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
        report = audit(args.root, raw, args.expected_manifest_sha256)
        with args.output.open("x") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except Exception as error:
        code = str(error)
        if not code.startswith("COVERAGE_") or not code.replace("_", "").isalnum():
            code = "COVERAGE_REJECTED"
        print(json.dumps({"status": "rejected", "error_code": code}))
        return 2
    print(
        json.dumps(
            {"status": "completed", "registered_states": report["registered_states"]}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
