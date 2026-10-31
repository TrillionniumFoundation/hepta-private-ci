"""Metadata/freeze checks shared by independent selected-runtime audits."""

import gzip
import hashlib
import json
from pathlib import Path
import re


ARMS = ("fixed", "current", "history", "native", "reset_native")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def object_sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def child(root, relative):
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()), "Unsafe evidence/freeze path")
    return path


def records(path):
    """Read all gzip members to EOF, checking canonical JSON and commit order."""
    previous_time = -1
    with gzip.open(path, "rb") as stream:
        for index, line in enumerate(stream):
            row = json.loads(line)
            require(line == canonical(row) + b"\n", "Noncanonical or incomplete journal line")
            require(row["record_index"] == index and type(row["committed_monotonic_ns"]) is int and
                    row["committed_monotonic_ns"] >= previous_time, "Journal record/commit chronology differs")
            previous_time = row["committed_monotonic_ns"]
            yield row, object_sha(row)


def open_profile(run, profile, source, freeze_path):
    """Metadata only; requires the whole three-seed audit grid before raw rows."""
    run, source = Path(run).resolve(), Path(source).resolve()
    protocol = json.loads((source / "PROTOCOL.json").read_text())
    require(profile in protocol["runtime"]["profiles"], "Unknown prespecified profile")
    directories = [run / "runtime" / "audit" / f"{seed}-{profile}" for seed in protocol["seeds"]]
    require(all((path / "COMPLETE.json").is_file() and (path / "selected" / "COMPLETE.json").is_file()
                and not (path / "FAILED.json").exists() for path in directories),
            "All three successful selected-runtime completions are required before outcome access")
    freeze = json.loads(Path(freeze_path).read_text())
    protocol_sha = file_sha(source / "PROTOCOL.json")
    require(re.fullmatch(r"[0-9a-f]{40}", freeze["registered_commit"]) and
            "runtime-audit" in freeze["allowed_phases"] and freeze["protocol_sha256"] == protocol_sha,
            "Runtime audit is not authorized by this source freeze")
    for name, digest in freeze["source_files"].items():
        require(file_sha(child(source.parent, name)) == digest, "Frozen source changed: " + name)
    for name, digest in freeze.get("artifacts", {}).items():
        require(file_sha(child(run, name)) == digest, "Frozen artifact changed: " + name)
    allocation = json.loads((source / "SOURCE_ALLOCATION.json").read_text())
    require(file_sha(source / "SOURCE_ALLOCATION.json") == protocol["source_allocation_sha256"] and
            allocation["manifest_sha256"] == protocol["source_manifest_sha256"], "Source allocation binding differs")
    packed = (source / "SOURCE_IDENTITIES.json.gz").read_bytes()
    raw = gzip.decompress(packed)
    require(hashlib.sha256(packed).hexdigest() == allocation["registry_gzip_sha256"] and
            hashlib.sha256(raw).hexdigest() == allocation["registry_sha256"], "Source registry changed")
    registry = json.loads(raw)
    if profile != "frozen":
        qualification = run / "TRAINING_QUALIFICATION.json"
        require(freeze.get("artifacts", {}).get("TRAINING_QUALIFICATION.json") == file_sha(qualification),
                "Non-frozen runtime lacks a prior bound learning qualification")
        qualified = json.loads(qualification.read_text())
        require(qualified["passed"] is True and qualified["protocol_sha256"] == protocol_sha,
                "Non-frozen runtime did not qualify under the current protocol")
    result = {"run": run, "source": source, "protocol": protocol, "protocol_sha256": protocol_sha,
              "profile": profile, "freeze": freeze, "freeze_sha256": file_sha(freeze_path),
              "freeze_path": Path(freeze_path).resolve(), "registry": registry, "seeds": []}
    for seed, directory in zip(protocol["seeds"], directories, strict=True):
        outer = json.loads((directory / "COMPLETE.json").read_text())
        inner = json.loads((directory / "selected" / "COMPLETE.json").read_text())
        start = json.loads((directory / "START.json").read_text())
        actual_files = {str(path.relative_to(directory)) for path in directory.rglob("*")
                        if path.is_file() and path != directory / "COMPLETE.json"}
        require(set(outer["files"]) == actual_files, "Runtime evidence file inventory differs")
        for name, digest in outer["files"].items():
            require(file_sha(child(directory, name)) == digest, "Runtime evidence hash differs: " + name)
        require(set(inner["files"]) == {"media.h3m", "events.jsonl.gz", "rows.jsonl.gz"}, "Selected stream inventory differs")
        for name, digest in inner["files"].items():
            require(outer["files"]["selected/" + name] == digest, "Parent/selected stream identity differs")
        require({k: v for k, v in outer.items() if k != "files"} == {k: v for k, v in inner.items() if k != "files"},
                "Parent/selected completion summaries differ")
        require(start["phase"] == "runtime-audit" and start["seed"] == seed and start["profile"] == profile and
                start["role"] is None and start["protocol_sha256"] == protocol_sha and
                start["freeze_sha256"] == result["freeze_sha256"] and start["registered_commit"] == freeze["registered_commit"] and
                start["native_library_sha256"] == freeze["native_library_sha256"], "Runtime START/freeze scope differs")
        require(start["source_files"] and all(freeze["source_files"].get(k) == v for k, v in start["source_files"].items()),
                "Runtime START source inventory is not frozen")
        require(inner["role"] == "runtime_audit" and inner["seed"] == seed and inner["profile"] == profile and
                inner["arms"] == list(ARMS) and inner["source_manifest_sha256"] == protocol["source_manifest_sha256"] and
                inner["authority"] == "DENY_ALL" and inner["native_owner_integration"] is False and
                inner["unchosen_continuations_executed"] == 0, "Unexpected selected-runtime scope/authority")
        require(inner["episodes"] == protocol["runtime"]["audit_pairs"] * len(protocol["runtime"]["conditions"]) * len(ARMS),
                "Selected-runtime episode count differs")
        fit_directory = run / "runtime" / "fit" / f"{seed}-{profile}"
        for name in ("READOUTS.json", "COMPLETE.json"):
            path = fit_directory / name
            require(freeze.get("artifacts", {}).get(str(path.relative_to(run))) == file_sha(path), "Runtime head artifact was not frozen before audit")
        readouts = json.loads((fit_directory / "READOUTS.json").read_text())
        fit_complete = json.loads((fit_directory / "COMPLETE.json").read_text())
        require(set(fit_complete["files"]) == {str(path.relative_to(fit_directory)) for path in fit_directory.rglob("*")
                if path.is_file() and path != fit_directory / "COMPLETE.json"}, "Runtime fit inventory changed")
        for name, digest in fit_complete["files"].items():
            require(file_sha(child(fit_directory, name)) == digest, "Frozen runtime fit evidence changed")
        meta = readouts["fit_identities"]["metadata"]
        require(meta["seed"] == seed and meta["profile"] == profile and meta["protocol_sha256"] == protocol_sha and
                meta["source_manifest_sha256"] == protocol["source_manifest_sha256"] and
                inner["model_parameter_sha256"] == meta["model_parameter_sha256"] and
                inner["observer_parameter_sha256"]["reward"] == meta["reward_observer_parameter_sha256"],
                "Selected generator/public observer differs from fitted bank")
        require(set(meta["bank_complete_sha256"]) == {"runtime_fit", "runtime_select"}, "Both fitted bank roles must be bound")
        for role, digest in meta["bank_complete_sha256"].items():
            path = run / "runtime" / "bank" / f"{seed}-{profile}" / role / "COMPLETE.json"
            require(role in ("runtime_fit", "runtime_select") and file_sha(path) == digest, "Runtime bank provenance changed")
            bank = json.loads(path.read_text())
            expected_pairs = protocol["runtime"]["fit_pairs" if role == "runtime_fit" else "selection_pairs"]
            require(bank["role"] == role and bank["seed"] == seed and bank["profile"] == profile and
                    bank["pairs"] == expected_pairs and bank["rows"] == len(protocol["runtime"]["conditions"]) * expected_pairs and
                    bank["source_manifest_sha256"] == protocol["source_manifest_sha256"] and
                    bank["model_parameter_sha256"] == meta["model_parameter_sha256"] and
                    bank["observer_parameter_sha256"] == meta["reward_observer_parameter_sha256"],
                    "Fitted bank scope or generator/observer identity differs")
        require(set(readouts["models"]) == set(ARMS[1:]), "Registered runtime representation family differs")
        policies = {"fixed": {"kind": "fixed", **readouts["fixed_policy"]},
                    **{arm: readouts["models"][arm] for arm in ARMS[1:]}}
        require(inner["controller_sha256"] == {arm: object_sha(policy) for arm, policy in policies.items()},
                "Selected policy identity differs from frozen readout")
        result["seeds"].append({"seed": seed, "directory": directory, "selected": directory / "selected",
            "complete": inner, "start": start, "policies": policies,
            "input_sha256": {"parent_complete": file_sha(directory / "COMPLETE.json"),
                             "selected_complete": file_sha(directory / "selected" / "COMPLETE.json"),
                             "readouts": file_sha(fit_directory / "READOUTS.json"),
                             "fit_complete": file_sha(fit_directory / "COMPLETE.json"), **inner["files"]}})
    return result


def verify_unchanged(bundle):
    """Bind a verification run to the same source, freeze and completed bytes."""
    require(file_sha(bundle["freeze_path"]) == bundle["freeze_sha256"], "Audit freeze changed during verification")
    for name, digest in bundle["freeze"]["source_files"].items():
        require(file_sha(child(bundle["source"].parent, name)) == digest, "Scientific source changed during verification")
    for name, digest in bundle["freeze"].get("artifacts", {}).items():
        require(file_sha(child(bundle["run"], name)) == digest, "Prior artifact changed during verification")
    for item in bundle["seeds"]:
        for name, digest in item["complete"]["files"].items():
            require(file_sha(item["selected"] / name) == digest, "Selected evidence changed during verification")
        require(file_sha(item["directory"] / "COMPLETE.json") == item["input_sha256"]["parent_complete"] and
                file_sha(item["selected"] / "COMPLETE.json") == item["input_sha256"]["selected_complete"],
                "Completion receipt changed during verification")
