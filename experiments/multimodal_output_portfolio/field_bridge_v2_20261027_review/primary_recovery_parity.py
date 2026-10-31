"""Verify deterministic I/O recovery against every complete original record.

Original partial evidence is never overwritten. This script computes no effect
estimate and excludes only execution timing and timestamp-dependent decision
bytes from the equality comparison. It accepts a truncated gzip trailer while
retaining every complete JSON line that was actually written.
"""

import argparse
import hashlib
import json
from pathlib import Path
import zlib


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stable(value, *, row=False):
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items()
                if not key.endswith("_ns") and not (row and key in {"decision_bytes_utf8", "decision_sha256"})}
    return [stable(item) for item in value] if isinstance(value, list) else value


def identity(value, *, row=False):
    return hashlib.sha256(json.dumps(stable(value, row=row), sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def complete_records(path, status):
    # GzipFile can reject a missing trailer after already-complete records. The
    # streaming inflater preserves that prefix without inventing missing bytes.
    inflater, buffer, count = zlib.decompressobj(wbits=31), b"", 0
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            buffer += inflater.decompress(block)
            while b"\n" in buffer:
                raw, buffer = buffer.split(b"\n", 1)
                require(bool(raw), "Blank original JSON record")
                value = json.loads(raw.decode("utf-8", errors="strict"))
                count += 1
                yield value
    require(not inflater.unused_data, "Unexpected concatenated gzip members or trailing data")
    if inflater.eof:
        require(not buffer, "Completed gzip contains an unterminated JSON record")
    status.update(complete_records=count, gzip_stream_complete=inflater.eof,
                  trailing_unterminated_record_bytes=len(buffer), file_sha256=file_sha(path))


def row_key(row):
    return tuple(row[key] for key in ("seed", "arm", "split", "corruption", "pair"))


def native_key(record):
    return record["batch_id"], record["native"]["case"]


def verify_one(old_path, new_path, kind, key_fn):
    previous, old_status, new_status = {}, {}, {}
    for record in complete_records(old_path, old_status):
        key = key_fn(record)
        require(key not in previous, "Duplicated original complete record")
        previous[key] = identity(record, row=kind == "rows")
    matched, seen, ledger = set(), set(), hashlib.sha256()
    for record in complete_records(new_path, new_status):
        key = key_fn(record)
        require(key not in seen, "Duplicated recovered record")
        seen.add(key)
        if key in previous:
            current = identity(record, row=kind == "rows")
            require(current == previous[key], f"Recovered {kind} differ from a complete original record: {key}")
            matched.add(key)
            ledger.update(json.dumps([key, current], separators=(",", ":")).encode())
    require(new_status["gzip_stream_complete"] and matched == set(previous),
            "Recovery omitted a complete original record")
    return {"original": old_status, "recovered": new_status, "exact_matches": len(matched),
            "stable_comparison_ledger_sha256": ledger.hexdigest()}


def audit(root):
    completion_path = root/"EVALUATION_COMPLETE.json"
    completion = json.loads(completion_path.read_text())
    require(completion.get("evaluation_subdirectory") == "eval_recovered", "No completed registered recovery cohort")
    registration_path = root/"IO_RECOVERY_REGISTRATION.json"
    registration = json.loads(registration_path.read_text())
    require(completion["recovery_registration_sha256"] == file_sha(registration_path) and
            completion["recovery_source_sha256"] == registration["recovery_source_sha256"] ==
            file_sha(Path(__file__).with_name("primary_io_recovery.py")) and
            completion["pretest_freeze_sha256"] == registration["pretest_freeze_sha256"] ==
            file_sha(root/"PRETEST_FREEZE.json"), "Recovery registration or original pretest binding differs")
    require(registration["independent_replicate"] is False and
            registration["outcome_statistics_inspected_or_used_for_repair"] is False and
            registration["predictors_models_or_thresholds_refit_or_changed"] is False,
            "Recovery scientific access boundary differs")
    reports, hashes_before = {}, {}
    for path in sorted((root/"eval").rglob("*")):
        if path.is_file():
            hashes_before[str(path.relative_to(root))] = file_sha(path)
    require(hashes_before, "Original partial evaluation evidence is absent")
    require(all(hashes_before.get(name) == value for name, value in registration["partial_attempt_files_sha256"].items()),
            "Registered original partial evidence changed")
    for seed in (17, 29, 43):
        old, new = root/"eval"/str(seed), root/"eval_recovered"/str(seed)
        require(not (old/"COMPLETE.json").exists() and (new/"COMPLETE.json").exists(),
                "Unexpected original completion or missing recovered completion")
        done = json.loads((new/"COMPLETE.json").read_text())
        require(done == completion["seeds"][str(seed)] and
                done["recovery_source_sha256"] == registration["recovery_source_sha256"] and
                done["registered_pretest_commit"] == registration["original_pretest_commit"] and
                done["registered_recovery_commit"] == completion["registered_recovery_commit"],
                "Recovery completion binding differs")
        reports[str(seed)] = {}
        for kind, key in (("rows", row_key), ("native", native_key)):
            filename = kind+".jsonl.gz"
            require(file_sha(new/filename) == done["files_sha256"][filename], "Recovered evidence file changed")
            reports[str(seed)][kind] = verify_one(old/filename, new/filename, kind, key)
    hashes_after = {str(path.relative_to(root)): file_sha(path) for path in sorted((root/"eval").rglob("*")) if path.is_file()}
    require(hashes_before == hashes_after, "Original partial evidence changed during verification")
    return {"schema": "hepta.field-bridge.v2.primary-io-recovery-parity.1", "passed": True,
        "seeds": reports, "original_partial_file_sha256": hashes_before,
        "original_complete_rows_reproduced": sum(r["rows"]["exact_matches"] for r in reports.values()),
        "original_complete_native_receipts_reproduced": sum(r["native"]["exact_matches"] for r in reports.values()),
        "evaluation_completion_sha256": file_sha(completion_path), "script_sha256": file_sha(Path(__file__)),
        "recovery_registration_sha256": file_sha(registration_path),
        "registered_original_partial_files": len(registration["partial_attempt_files_sha256"]),
        "additional_preserved_partial_files": sorted(set(hashes_before)-set(registration["partial_attempt_files_sha256"])),
        "preserved": "Every original complete row and native receipt: scores, actions, sources, model/controller IDs, public features, PNG/UTF8 SHA256, non-timing counts, full native state/digests.",
        "excluded_from_equality": ["All timing/timestamp fields ending _ns.",
                                   "Original decision UTF8 text and SHA256 because the embedded monotonic timestamp changes; the parsed decision is compared except that timestamp."],
        "scientific_choices_changed": False, "effect_estimates_computed": False,
        "limitations": ["Byte/scientific-record equality is verified, not external process attestation.",
                        "The recovered actual media bytes are independently checked by the full media audit.",
                        "Flushed rows/native receipts give a lower bound on repeated partial work; the interrupted last batch may contain additional unlogged work."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run)
    with args.out.open("x") as output:
        json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
    print(json.dumps({key: result[key] for key in ("passed", "original_complete_rows_reproduced",
                                                "original_complete_native_receipts_reproduced")}))
