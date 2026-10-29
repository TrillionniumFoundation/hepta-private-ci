"""Explicit cost-roundoff audit views; never edits the frozen scientific audit.

Only a negative top-level completed_child_cpu_seconds token in [-1e-12, 0)
may become 0.0. Original inputs and the original audit outcome remain intact.
The unchanged audit_run executes again on an independently validated derived
input view. Scientific outcomes, gates, records, and historical costs never change.
"""

import argparse
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import shutil

from . import audit as frozen_audit

FIELD = "completed_child_cpu_seconds"
LOWER = Decimal("-1e-12")
POLICY = {
    "field": FIELD,
    "location": "current-run root costs.jsonl, top-level JSON object only",
    "allowed_original_interval": "[-1e-12,0)",
    "replacement_token": "0.0",
    "positive_values": "unchanged",
    "history": "byte-identical reporting inputs; never normalized or counted as current samples",
}


class CostViewError(ValueError):
    """The requested view would exceed the explicit roundoff allowance."""


def require(condition, message):
    if not condition:
        raise CostViewError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _number(token):
    value = float(token)
    require(math.isfinite(value), "Nonfinite JSON number")
    return value


def _constant(token):
    raise CostViewError(f"Forbidden JSON constant: {token}")


DECODER = json.JSONDecoder(
    object_pairs_hook=_pairs, parse_float=_number, parse_constant=_constant
)


def object_spans(raw):
    """Parse an object and locate top-level value tokens without reserializing."""
    text = raw.decode("utf-8")
    skip = lambda i: i + len(text[i:]) - len(text[i:].lstrip())
    start = skip(0)
    obj, end = DECODER.raw_decode(text, start)
    require(
        isinstance(obj, dict) and not text[end:].strip(),
        "Expected exactly one JSON object",
    )
    spans, i = {}, skip(start + 1)
    while text[i] != "}":
        key, i = DECODER.raw_decode(text, i)
        require(isinstance(key, str), "Object key is not a string")
        i = skip(i)
        require(text[i] == ":", "Missing JSON colon")
        begin = skip(i + 1)
        _, finish = DECODER.raw_decode(text, begin)
        spans[key] = (begin, finish)
        i = skip(finish)
        if text[i] == "}":
            break
        require(text[i] == ",", "Missing JSON comma")
        i = skip(i + 1)
    return obj, spans, text


def _check_other_costs(obj, path=()):
    if isinstance(obj, dict):
        for key, value in obj.items():
            current = (*path, key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                measured = (
                    key.endswith(("_seconds", "_bytes", "_calls", "_evals", "_updates"))
                    or key == "fits"
                )
                if measured and current != (FIELD,):
                    require(
                        value >= 0,
                        f"Negative non-whitelisted cost at {'.'.join(current)}",
                    )
            _check_other_costs(value, current)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            _check_other_costs(value, (*path, str(index)))


def normalize_costs(raw):
    """Return a token-only transformation and its complete per-line ledger."""
    output, corrections = [], []
    for number, original in enumerate(raw.splitlines(keepends=True), 1):
        obj, spans, text = object_spans(original)
        _check_other_costs(obj)
        replacement = original
        if FIELD in obj:
            value = obj[FIELD]
            require(
                type(value) in (int, float), "Child CPU must be a finite real number"
            )
            begin, end = spans[FIELD]
            token = text[begin:end]
            precise = Decimal(token)
            if precise < 0:
                require(
                    precise >= LOWER,
                    "Child CPU negative value exceeds 1e-12-second allowance",
                )
                replacement = (text[:begin] + "0.0" + text[end:]).encode("utf-8")
                corrections.append(
                    {
                        "line": number,
                        "json_pointer": "/" + FIELD,
                        "original_token": token,
                        "replacement_token": "0.0",
                        "original_value": value,
                        "replacement_value": 0.0,
                        "correction_seconds_decimal": str(-precise),
                        "original_line_sha256": sha(original),
                        "derived_line_sha256": sha(replacement),
                    }
                )
        output.append(replacement)
    require(output, "Empty current-run cost ledger")
    return b"".join(output), corrections


def _path(root, relative):
    require(
        isinstance(relative, str) and relative and not Path(relative).is_absolute(),
        "Expected relative artifact path",
    )
    path = (root / relative).resolve()
    require(
        path.is_relative_to(root.resolve()) and path.is_file(),
        f"Missing/escaping artifact: {relative}",
    )
    return path


def _report(path):
    name = Path(path).name.upper()
    return "AUDIT" in name or "DERIVATION" in name


def _allowed_extra(relative):
    path = Path(relative)
    if _report(relative):
        return False
    if path.parts[0] == "history":
        name = path.name.upper()
        return name == "COSTS.JSONL" or name.startswith(
            ("ABORTED", "SOURCE_SEAL", "PUBLICATION")
        )
    return (
        relative
        in {
            "ENVIRONMENT.json",
            "SCENARIOS.json",
            "SOURCE_SEAL.json",
            "SELECTION_SEAL.json",
        }
        or path.parts[0] == "datasets"
        or path.parts[0].startswith("PUBLICATION")
        or (
            path.parts[0] == "training"
            and ("profiles" in path.parts or path.name == "TRAINING.json")
        )
    )


def dependencies(root, manifest, include_extras):
    """Manifest closure plus bounded reporting metadata, never previous outcomes."""
    require(
        manifest.get("costs_path", "costs.jsonl") == "costs.jsonl",
        "Only current-run root costs.jsonl can be normalized",
    )
    paths = {
        "manifest.json",
        "costs.jsonl",
        manifest.get("protocol_path", "protocol.json"),
    }
    for group in ("records", "checkpoints"):
        for entry in manifest[group]:
            relative = entry["path"]
            require(
                Path(relative).parts[0] != "history" and not _report(relative),
                "Primary dependency points to history/report",
            )
            paths.add(relative)
            if group == "checkpoints":
                checkpoint = object_spans(_path(root, relative).read_bytes())[0]
                if "profile_path" in checkpoint:
                    require(
                        Path(checkpoint["profile_path"]).parts[0] != "history",
                        "Current checkpoint uses historical profile",
                    )
                    paths.add(checkpoint["profile_path"])
    for label in ("source", "selection"):
        if label + "_seal_sha256" in manifest:
            name = label.upper() + "_SEAL.json"
            paths.add(name)
            if label == "selection":
                paths.update(
                    object_spans(_path(root, name).read_bytes())[0].get("profiles", {})
                )
    if include_extras:
        for name in (
            "ENVIRONMENT.json",
            "SCENARIOS.json",
            "SOURCE_SEAL.json",
            "SELECTION_SEAL.json",
        ):
            if (root / name).is_file():
                paths.add(name)
        for pattern in (
            "datasets/**/*",
            "training/*/*/profiles/*.json",
            "training/*/*/TRAINING.json",
            "PUBLICATION*",
            "history/**/costs.jsonl",
            "history/**/ABORTED*",
            "history/**/SOURCE_SEAL*",
            "history/**/PUBLICATION*",
        ):
            for candidate in root.glob(pattern):
                candidates = candidate.rglob("*") if candidate.is_dir() else [candidate]
                for item in candidates:
                    if item.is_file():
                        relative = str(item.relative_to(root))
                        if _allowed_extra(relative):
                            paths.add(relative)
    for relative in paths:
        require(not _report(relative), "Audit/derivation reports cannot be view inputs")
        _path(root, relative)
    return paths


def frozen_audit_hash(root, manifest):
    """Bind the imported original auditor to the run's scientific source seal."""
    digest = file_sha(frozen_audit.__file__)
    if "source_seal_sha256" in manifest:
        seal_bytes = _path(root, "SOURCE_SEAL.json").read_bytes()
        require(
            sha(seal_bytes) == manifest["source_seal_sha256"],
            "Original source seal hash mismatch",
        )
        seal = object_spans(seal_bytes)[0]
        matches = [
            value
            for name, value in seal["source_files"].items()
            if name.replace("\\", "/").endswith("/continuous_boundary_flow/audit.py")
        ]
        require(
            matches == [digest],
            "Imported scientific auditor is not the sealed original",
        )
    return digest


def save_json(path, data):
    with Path(path).open("xb") as stream:
        stream.write(
            (
                json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n"
            ).encode()
        )


def validate_derivation(original_dir, view_dir):
    """Independently compare original/view bytes; does not call normalize_costs."""
    original, view = Path(original_dir).resolve(), Path(view_dir).resolve()
    receipt = object_spans((view / "DERIVATION.json").read_bytes())[0]
    require(
        receipt.get("schema") == "hepta.cost-roundoff-derivation.v1"
        and receipt.get("policy") == POLICY,
        "Unknown derivation policy",
    )
    require(
        receipt["helper_sha256"] == file_sha(__file__),
        "Helper source differs from derivation",
    )
    old_manifest = (original / "manifest.json").read_bytes()
    new_manifest = (view / "manifest.json").read_bytes()
    old, spans, text = object_spans(old_manifest)
    new = object_spans(new_manifest)[0]
    require(
        receipt["frozen_audit_sha256"] == frozen_audit_hash(original, old),
        "Frozen scientific auditor differs",
    )
    old_cost, new_cost = (
        (original / "costs.jsonl").read_bytes(),
        (view / "costs.jsonl").read_bytes(),
    )
    for label, raw in (
        ("original_manifest", old_manifest),
        ("derived_manifest", new_manifest),
        ("original_costs", old_cost),
        ("derived_costs", new_cost),
    ):
        require(receipt[label + "_sha256"] == sha(raw), f"{label} digest differs")
    require(
        old["costs_sha256"] == sha(old_cost) and new["costs_sha256"] == sha(new_cost),
        "Cost ledger hash binding failed",
    )
    begin, end = spans["costs_sha256"]
    expected_manifest = (text[:begin] + json.dumps(sha(new_cost)) + text[end:]).encode()
    require(
        new_manifest == expected_manifest,
        "Derived manifest changed more than the cost hash token",
    )
    old_lines, new_lines = (
        old_cost.splitlines(keepends=True),
        new_cost.splitlines(keepends=True),
    )
    require(len(old_lines) == len(new_lines), "Cost lines were inserted/deleted")
    observed = []
    for number, (left, right) in enumerate(zip(old_lines, new_lines), 1):
        if left == right:
            continue
        before, positions, line = object_spans(left)
        after = object_spans(right)[0]
        require(
            FIELD in positions and type(before[FIELD]) in (int, float),
            "Changed line lacks child-CPU scalar",
        )
        a, b = positions[FIELD]
        token, amount = line[a:b], Decimal(line[a:b])
        require(
            LOWER <= amount < 0 and after.get(FIELD) == 0,
            "Changed field is outside strict allowance",
        )
        require(
            right == (line[:a] + "0.0" + line[b:]).encode(),
            "Changed another ledger byte or field",
        )
        observed.append(
            {
                "line": number,
                "json_pointer": "/" + FIELD,
                "original_token": token,
                "replacement_token": "0.0",
                "original_value": before[FIELD],
                "replacement_value": 0.0,
                "correction_seconds_decimal": str(-amount),
                "original_line_sha256": sha(left),
                "derived_line_sha256": sha(right),
            }
        )
    require(
        observed and observed == receipt["corrections"],
        "Derivation correction list is incomplete/inaccurate",
    )
    copied = receipt["copied_inputs"]
    mandatory = dependencies(original, old, include_extras=False) - {
        "manifest.json",
        "costs.jsonl",
    }
    require(mandatory <= set(copied), "Derived view omitted a manifest dependency")
    for relative, expected in copied.items():
        require(
            relative in mandatory or _allowed_extra(relative),
            f"Unexpected copied input: {relative}",
        )
        require(
            file_sha(_path(original, relative))
            == file_sha(_path(view, relative))
            == expected,
            f"Non-cost input changed: {relative}",
        )
    expected_files = set(copied) | {"manifest.json", "costs.jsonl", "DERIVATION.json"}
    if "derived_audit_result_sha256" in receipt:
        result_path = view / "AUDIT.json"
        require(
            file_sha(result_path) == receipt["derived_audit_result_sha256"],
            "Derived audit output hash mismatch",
        )
        result = object_spans(result_path.read_bytes())[0]
        require(
            result.get("integrity_passed") is True
            and result.get("manifest_sha256") == sha(new_manifest)
            and result.get("protocol_sha256") == old["protocol_sha256"],
            "Derived audit output is bound to another manifest/protocol",
        )
        expected_files.add("AUDIT.json")
    view_files = {str(p.relative_to(view)) for p in view.rglob("*") if p.is_file()}
    require(
        view_files == expected_files,
        "Derived view contains missing or extra inputs/reports",
    )
    require(
        receipt["protocol_sha256"] == old["protocol_sha256"] == new["protocol_sha256"],
        "Protocol identity changed",
    )
    require(
        receipt.get("source_seal_sha256") == old.get("source_seal_sha256"),
        "Source seal identity changed",
    )
    return {
        "validated": True,
        "validation_scope": "Exact byte transformation only; scientific acceptance requires the unchanged original audit",
        "correction_count": len(observed),
        "byte_identical_inputs": len(copied),
        "total_correction_seconds_decimal": str(
            sum(
                (Decimal(x["correction_seconds_decimal"]) for x in observed), Decimal(0)
            )
        ),
        "original_manifest_sha256": sha(old_manifest),
        "derived_manifest_sha256": sha(new_manifest),
    }


def audit_with_cost_view(original_dir, view_dir, receipt_dir):
    """Preserve original verdict; create a derived view only when indispensable."""
    original, view, receipts = (
        Path(p).resolve() for p in (original_dir, view_dir, receipt_dir)
    )
    require(
        original.is_dir() and not view.exists(),
        "Original must exist and view must be new",
    )
    require(
        not view.is_relative_to(original) and not original.is_relative_to(view),
        "View must be a separate sibling/subtree",
    )
    require(
        not receipts.is_relative_to(view) and receipts != original,
        "Audit reports must be outside input view",
    )
    receipts.mkdir(parents=True, exist_ok=False)
    try:
        bound_manifest = object_spans((original / "manifest.json").read_bytes())[0]
        source_digest = frozen_audit_hash(original, bound_manifest)
        original_result = frozen_audit.audit_run(original)
    except Exception as exc:
        original_result = {
            "integrity_passed": False,
            "exception_type": type(exc).__name__,
            "error": str(exc),
        }
    save_json(receipts / "ORIGINAL_AUDIT_RESULT.json", original_result)
    if original_result.get("integrity_passed"):
        result = {
            "status": "original_passed_no_view",
            "view_created": False,
            "original_manifest_sha256": file_sha(original / "manifest.json"),
        }
        save_json(receipts / "COST_VIEW_STATUS.json", result)
        return result
    try:
        require(
            original_result.get("exception_type") == "AuditError"
            and original_result.get("error") == FIELD + ": negative value",
            "Original audit did not reject solely at the whitelisted child-CPU cost check",
        )
        old_manifest = (original / "manifest.json").read_bytes()
        manifest, spans, manifest_text = object_spans(old_manifest)
        raw_costs = (original / "costs.jsonl").read_bytes()
        require(
            manifest.get("costs_path", "costs.jsonl") == "costs.jsonl"
            and manifest.get("costs_sha256") == sha(raw_costs),
            "Current root ledger is not hash-bound",
        )
        new_costs, corrections = normalize_costs(raw_costs)
        require(
            corrections, "No permitted correction exists; derived view is unnecessary"
        )
        inputs = dependencies(original, manifest, include_extras=True) - {
            "manifest.json",
            "costs.jsonl",
        }
        view.mkdir(parents=True, exist_ok=False)
        copied = {}
        for relative in sorted(inputs):
            source, destination = _path(original, relative), view / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            copied[relative] = file_sha(source)
            require(
                file_sha(destination) == copied[relative],
                "Input copy was not byte-identical",
            )
        (view / "costs.jsonl").write_bytes(new_costs)
        a, b = spans["costs_sha256"]
        new_manifest = (
            manifest_text[:a] + json.dumps(sha(new_costs)) + manifest_text[b:]
        ).encode()
        (view / "manifest.json").write_bytes(new_manifest)
        derivation = {
            "schema": "hepta.cost-roundoff-derivation.v1",
            "policy": POLICY,
            "helper_sha256": file_sha(__file__),
            "frozen_audit_sha256": source_digest,
            "original_audit_result_sha256": file_sha(
                receipts / "ORIGINAL_AUDIT_RESULT.json"
            ),
            "original_manifest_sha256": sha(old_manifest),
            "derived_manifest_sha256": sha(new_manifest),
            "original_costs_sha256": sha(raw_costs),
            "derived_costs_sha256": sha(new_costs),
            "protocol_sha256": manifest["protocol_sha256"],
            "source_seal_sha256": manifest.get("source_seal_sha256"),
            "corrections": corrections,
            "copied_inputs": copied,
            "original_verdict": "rejected at strict child-CPU nonnegativity; preserved separately",
            "limits": "No scientific source, episode, gate, seed, profile, or historical cost changed",
        }
        save_json(view / "DERIVATION.json", derivation)
        validate_derivation(original, view)
        derived_result = frozen_audit.audit_run(view)
        save_json(receipts / "DERIVED_AUDIT_RESULT.json", derived_result)
        save_json(view / "AUDIT.json", derived_result)
        derivation["derived_audit_result_sha256"] = file_sha(view / "AUDIT.json")
        (view / "DERIVATION.json").write_text(
            json.dumps(derivation, sort_keys=True, indent=2, allow_nan=False) + "\n"
        )
        validation = validate_derivation(original, view)
        save_json(receipts / "DERIVATION_VALIDATION.json", validation)
        result = {
            "status": "original_rejected_derived_passed",
            "view_created": True,
            "derivation_sha256": file_sha(view / "DERIVATION.json"),
            "derived_audit_result_sha256": file_sha(view / "AUDIT.json"),
            **validation,
        }
        save_json(receipts / "COST_VIEW_STATUS.json", result)
        return result
    except Exception as exc:
        result = {
            "status": "rejected_no_relaxation",
            "view_created": view.exists(),
            "exception_type": type(exc).__name__,
            "error": str(exc),
        }
        save_json(receipts / "COST_VIEW_STATUS.json", result)
        raise CostViewError(str(exc)) from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "validate"))
    parser.add_argument("original_dir", type=Path)
    parser.add_argument("view_dir", type=Path)
    parser.add_argument("--receipt-dir", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            result = validate_derivation(args.original_dir, args.view_dir)
        else:
            require(
                args.receipt_dir is not None,
                "run requires --receipt-dir outside the view",
            )
            result = audit_with_cost_view(
                args.original_dir, args.view_dir, args.receipt_dir
            )
    except Exception as exc:
        parser.exit(1, f"COST VIEW REJECTED: {exc}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
