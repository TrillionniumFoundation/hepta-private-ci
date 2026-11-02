"""Fail-closed, offline validation of a byte-bound AV admission submission.

This checks supplied evidence, not the truth/completeness of an external archive.
In particular, it cannot turn a claim of complete history into independent proof.
"""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

V6_COMMIT = "febdbb1ebb5e7fb9f585b10b3ec743fb5d22eb24"
KNOWN_PRIOR_CAMPAIGNS = {"v3", "v5", "v6", "v7", "v8"}
REQUIRED_ROLES = {
    "original_v6_protocol", "original_v6_head", "strong_audio_head",
    "history_catalog", "history_ledger", "history_reconciliation",
    "confirmation_index", "av_evaluation", "audio_evaluation",
}
HEX256 = re.compile(r"^[0-9a-f]{64}$")
HEX160 = re.compile(r"^[0-9a-f]{40}$")


def strict_json(data: bytes | str) -> object:
    def pairs(items: list) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def validate(submission: object, root: Path) -> dict:
    errors: list[str] = []
    verified: dict[str, dict] = {}
    payloads: dict[str, object] = {}

    def fail(message: str) -> None:
        errors.append(message)

    def load_artifact(role: str, record: object) -> object:
        if not isinstance(record, dict):
            fail(f"{role}: missing artifact")
            return None
        path, digest, size = record.get("path"), record.get("sha256"), record.get("bytes")
        if not isinstance(path, str) or not path or Path(path).is_absolute():
            fail(f"{role}: path must be relative")
            return None
        if not isinstance(digest, str) or not HEX256.fullmatch(digest):
            fail(f"{role}: missing SHA256")
            return None
        if type(size) is not int or size <= 0:
            fail(f"{role}: missing positive byte count")
            return None
        try:
            target = (root / path).resolve(strict=True)
            target.relative_to(root.resolve())
            data = target.read_bytes()
        except (OSError, ValueError):
            fail(f"{role}: bytes unavailable or outside root")
            return None
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            fail(f"{role}: content hash/size mismatch")
            return None
        commit = record.get("source_commit")
        if not isinstance(commit, str) or not HEX160.fullmatch(commit):
            fail(f"{role}: missing pinned source commit")
            return None
        if role in {"original_v6_protocol", "original_v6_head"} and commit != V6_COMMIT:
            fail(f"{role}: original v6 commit is required")
            return None
        blob = record.get("git_blob_sha1")
        if blob is not None:
            actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if blob != actual:
                fail(f"{role}: Git blob mismatch")
                return None
        verified[role] = {"path": path, "sha256": digest, "bytes": size,
                          "source_commit": commit}
        if role.endswith("_head") or role.startswith("confirmation_media_"):
            return None
        try:
            return strict_json(data)
        except (ValueError, UnicodeError):
            fail(f"{role}: expected strict JSON evidence")
            return None

    if not isinstance(submission, dict):
        return {"status": "FAIL", "errors": ["submission must be an object"],
                "verified_artifacts": {}}
    if submission.get("schema") != "hcsn-frontend-admission.v1":
        fail("schema: unsupported or missing")
    assets = submission.get("artifacts")
    assets = assets if isinstance(assets, dict) else {}
    for role in sorted(REQUIRED_ROLES):
        payloads[role] = load_artifact(role, assets.get(role))

    def obj(role: str) -> dict:
        value = payloads.get(role)
        return value if isinstance(value, dict) else {}

    protocol = obj("original_v6_protocol")
    tasks = protocol.get("tasks")
    if (not isinstance(tasks, dict) or not tasks or
            any(not isinstance(k, str) or not k or not isinstance(v, dict)
                for k, v in tasks.items())):
        fail("protocol: missing original task/quality contract")
        tasks = {}
    if protocol.get("campaign") != "v6":
        fail("protocol: original v6 campaign identity missing or mismatched")
    for role in ("original_v6_head", "strong_audio_head"):
        expected = protocol.get("head_sha256", {}).get(role) if isinstance(protocol.get("head_sha256"), dict) else None
        if role not in verified or expected != verified[role]["sha256"]:
            fail(f"protocol: {role} is not bound to original contract")
    minimum = protocol.get("minimum_independent_recordings")
    if type(minimum) is not int or minimum < 1:
        fail("protocol: missing positive independent-recording requirement")
        minimum = 1

    catalog, ledger, reconciliation = (obj(x) for x in
        ("history_catalog", "history_ledger", "history_reconciliation"))
    campaigns = catalog.get("campaigns")
    if (not isinstance(campaigns, list) or not campaigns or
            any(not isinstance(x, str) or not x for x in campaigns) or
            len(set(campaigns)) != len(campaigns)):
        fail("history: campaign catalog is missing, empty or duplicated")
        campaigns = []
    if not KNOWN_PRIOR_CAMPAIGNS.issubset(set(campaigns)):
        fail("history: catalog omits known prior v3/v5/v6/v7/v8 campaigns")
    if catalog.get("all_prior_uses_through_v8") is not True:
        fail("history: complete development/calibration/selection/confirmation scope undeclared")
    coverage = ledger.get("campaigns")
    if not isinstance(coverage, dict) or not coverage or set(coverage) != set(campaigns):
        fail("history: ledger does not cover the full declared campaign catalog")
        coverage = {}
    historical = []
    for campaign, entry in coverage.items():
        if not isinstance(entry, dict) or entry.get("complete") is not True:
            fail(f"history/{campaign}: completeness not established")
            continue
        rows = entry.get("recordings")
        # An empty list is never evidence that earlier recorded experiments used nothing.
        if not isinstance(rows, list) or not rows:
            fail(f"history/{campaign}: empty recording exclusion list")
            continue
        historical.extend(rows)
    expected_history = {role: verified.get(role, {}).get("sha256") for role in
                        ("history_catalog", "history_ledger")}
    if (reconciliation.get("complete") is not True or
            reconciliation.get("artifact_sha256") != expected_history or
            reconciliation.get("campaigns") != campaigns or
            reconciliation.get("includes_exploration_and_failed_runs") is not True):
        fail("history: byte-bound reconciliation including exploration/failures is missing")

    def identity(row: object, where: str) -> tuple | None:
        if not isinstance(row, dict):
            fail(f"{where}: malformed recording identity")
            return None
        source, session, capture = (row.get(k) for k in
                                    ("source_recording_id", "acquisition_session_id", "original_capture_sha256"))
        if (not isinstance(source, str) or not source or not isinstance(session, str) or
                not session or not isinstance(capture, str) or not HEX256.fullmatch(capture)):
            fail(f"{where}: canonical source/session/original-capture identity required")
            return None
        return source, session, capture

    historical_ids = [identity(r, "history") for r in historical]
    historical_ids = [x for x in historical_ids if x is not None]
    index = obj("confirmation_index")
    new = index.get("recordings")
    if not isinstance(new, list) or len(new) < minimum:
        fail("confirmation: insufficient independent new recordings")
        new = []
    new_ids: list[tuple] = []
    for i, row in enumerate(new):
        where = f"confirmation/{i}"
        ident = identity(row, where)
        if ident is None:
            continue
        ancestors = row.get("derivation_ancestors")
        if not isinstance(ancestors, list):
            fail(f"{where}: derivation ancestry must be explicitly declared")
            ancestors = []
        lineage = [ident] + [x for a in ancestors if (x := identity(a, where + "/ancestor")) is not None]
        # Renaming, recoding, cropping or resplitting does not create a new capture.
        if any(any(a[j] == b[j] for j in range(3)) for a in lineage for b in historical_ids):
            fail(f"{where}: recording/session/capture ancestry overlaps history")
        if any(any(ident[j] == other[j] for j in range(3)) for other in new_ids):
            fail(f"{where}: duplicate recording/session/capture in confirmation")
        if row.get("independent_capture") is not True or ancestors:
            fail(f"{where}: independent recording acquisition is not established")
        media_role, receipt_role = f"confirmation_media_{i}", f"acquisition_receipt_{i}"
        load_artifact(media_role, row.get("media"))
        receipt = load_artifact(receipt_role, row.get("acquisition_receipt"))
        if not isinstance(receipt, dict) or identity(receipt, where + "/receipt") != ident:
            fail(f"{where}: acquisition receipt identity mismatch")
        elif (receipt.get("record_kind") != "independent_recording" or
              receipt.get("original_capture_sha256") != verified.get(media_role, {}).get("sha256") or
              not isinstance(receipt.get("recorded_at"), str) or not receipt.get("recorded_at")):
            fail(f"{where}: independent original media acquisition receipt missing")
        new_ids.append(ident)

    # Freeze case identities and labels once; both heads must report every case.
    expected_cases = {}
    cases = index.get("cases")
    if not isinstance(cases, list) or not cases:
        fail("confirmation: frozen case catalog missing")
        cases = []
    for row in cases:
        if not isinstance(row, dict):
            fail("confirmation: malformed frozen case")
            continue
        task, case, source, label = (row.get(k) for k in
                                     ("task", "case_id", "source_recording_id", "label"))
        if (not isinstance(task, str) or task not in tasks or not isinstance(case, str) or not case or
                not isinstance(source, str) or source not in {x[0] for x in new_ids} or
                type(label) is not int or type(tasks[task].get("classes")) is not int or
                not 0 <= label < tasks[task]["classes"] or (task, case) in expected_cases):
            fail("confirmation: invalid or duplicated frozen case identity/label")
            continue
        expected_cases[(task, case)] = (source, label)

    index_digest = verified.get("confirmation_index", {}).get("sha256")
    protocol_digest = verified.get("original_v6_protocol", {}).get("sha256")
    measured = {}
    for role, head in (("av_evaluation", "original_v6_head"), ("audio_evaluation", "strong_audio_head")):
        evaluation = obj(role)
        if (evaluation.get("protocol_sha256") != protocol_digest or not protocol_digest or
                evaluation.get("confirmation_index_sha256") != index_digest or not index_digest or
                evaluation.get("head_sha256") != verified.get(head, {}).get("sha256") or
                head not in verified):
            fail(f"{role}: protocol, fitted head or confirmation identities are unbound")
        rows = evaluation.get("predictions")
        if not isinstance(rows, list) or not rows:
            fail(f"{role}: raw predictions missing")
            rows = []
        seen, grouped = set(), {}
        for row in rows:
            if not isinstance(row, dict):
                fail(f"{role}: malformed prediction")
                continue
            task, case, source = row.get("task"), row.get("case_id"), row.get("source_recording_id")
            probabilities, label = row.get("probabilities"), row.get("label")
            key = (task, case)
            if (not isinstance(task, str) or task not in tasks or
                    not isinstance(case, str) or not case or key in seen or
                    not isinstance(source, str) or source not in {x[0] for x in new_ids}):
                fail(f"{role}: duplicate/unknown task, case or recording")
                continue
            seen.add(key)
            if expected_cases.get(key) != (source, label):
                fail(f"{role}: prediction differs from frozen case/label catalog")
                continue
            classes = tasks[task].get("classes")
            if (type(classes) is not int or classes < 2 or not isinstance(probabilities, list) or
                    len(probabilities) != classes or type(label) is not int or not 0 <= label < classes or
                    any(type(p) not in (int, float) or not math.isfinite(p) or p < 0 or p > 1 for p in probabilities) or
                    not math.isclose(sum(probabilities), 1, abs_tol=1e-7)):
                fail(f"{role}: invalid class probability/label contract")
                continue
            grouped.setdefault(task, []).append((source, int(max(range(classes), key=probabilities.__getitem__) == label)))
        if seen != set(expected_cases) or not expected_cases:
            fail(f"{role}: frozen case coverage incomplete or unexpected")
        measured[role] = {}
        for task, contract in tasks.items():
            outcomes = grouped.get(task, [])
            threshold = contract.get("minimum_av_accuracy" if role == "av_evaluation" else "minimum_audio_accuracy")
            if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 < threshold <= 1:
                fail(f"{role}/{task}: original positive quality threshold missing")
                continue
            if {x[0] for x in outcomes} != {x[0] for x in new_ids} or not new_ids:
                fail(f"{role}/{task}: new recording coverage incomplete")
            accuracy = sum(x[1] for x in outcomes) / len(outcomes) if outcomes else None
            measured[role][task] = {"count": len(outcomes), "accuracy": accuracy, "minimum": threshold}
            if accuracy is None or accuracy < threshold:
                fail(f"{role}/{task}: strong quality gate failed")
    return {"schema": "hcsn-frontend-admission-result.v1", "status": "FAIL" if errors else "PASS",
            "errors": errors, "verified_artifacts": verified, "recomputed_quality": measured,
            "scope": "Offline submitted-byte and identity contract only; external completeness/acquisition authenticity requires independent review.",
            "production_authorized": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission", type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        submission = strict_json(args.submission.read_bytes())
        result = validate(submission, args.root)
    except (OSError, ValueError) as exc:
        result = {"status": "FAIL", "errors": [str(exc)]}
    rendered = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
