"""Verify an original agent failure and correction, and derive one A-only training record."""

import copy
import hashlib
import re

from . import adoption, coding_sft, data, prospective_exposure

require = adoption.require


def sha(value):
    require(
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value)
        and value != "0" * 64,
        "nonzero SHA-256 required",
    )
    return value


def text_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_bound(path, expected):
    value = adoption.read_json(path)
    require(
        data.digest(value) == sha(expected),
        "private material does not match its commitment",
    )
    return value


def check_attempt(record, expected_success, originals):
    """First execution profile uses readback of bytes actually stored by an artifact sink."""
    data.validate_record(record)
    require(
        record["split"] == "train"
        and record["origin_kind"] == "authorized_agent_run"
        and record["authorization"]["training_allowed"] is True,
        "A must permit training",
    )
    require(
        record["task"]["verifier"]["name"] == "json_artifact"
        and record["task"]["verifier"]["version"] == "1",
        "unsupported artifact verifier",
    )
    outcome = record["verified_outcome"]
    require(outcome["success"] is expected_success, "wrong original outcome")
    computed = data.verify_answer(record, record["final_answer"])
    require(computed["success"] is expected_success, "semantic verification disagrees")
    verified = adoption.read_json(originals / sha(outcome["receipt_sha256"]))
    require(
        data.canonical(verified) == data.canonical(computed)
        and computed["receipt_sha256"] == outcome["receipt_sha256"],
        "original semantic receipt differs",
    )
    source_sha = sha(record["source"]["sha256"])
    require(
        coding_sft.file_hash(originals / source_sha) == source_sha,
        "original source bytes differ",
    )
    actions = [event for event in record["trajectory"] if event["executed"]]
    require(
        actions and actions[-1]["content"] == record["final_answer"],
        "terminal executed action missing",
    )
    last = actions[-1]
    observed = read_bound(
        originals / sha(last["receipt_sha256"]), last["receipt_sha256"]
    )
    require(
        observed.get("schema") == "hepta.paired-learning.artifact-readback.v1"
        and observed.get("task_id") == record["task_id"]
        and observed.get("record_id") == record["record_id"]
        and observed.get("actor") == last["actor"]
        and observed.get("source_sha256") == source_sha
        and observed.get("input_sha256") == text_sha(record["task"]["input"])
        and observed.get("readback_sha256") == text_sha(record["final_answer"])
        and observed.get("semantic_receipt_sha256") == computed["receipt_sha256"],
        "artifact readback differs from the recorded action",
    )
    policy = (
        last.get("policy_sha256")
        if last["actor"] == "student"
        else record.get("model_digest")
    )
    require(observed.get("policy_sha256") == sha(policy), "executing policy mismatch")
    # Verify retained bytes too. Never execute code or read paths supplied by the event.
    digest = sha(observed["readback_sha256"])
    with (originals / digest).open("rb") as source:
        raw = source.read(65537)
    require(raw == record["final_answer"].encode(), "retained artifact bytes differ")


def derive(failure, correction, originals):
    from . import opaque_teacher_data, paired_opaque_teacher

    if correction.get("schema") == opaque_teacher_data.SCHEMA:
        return paired_opaque_teacher.derive(failure, correction, originals)
    for key in ("task_id", "lineage_id", "project_id", "task"):
        require(
            failure[key] == correction[key],
            "failure and correction describe different tasks",
        )
    require(
        failure["record_id"] != correction["record_id"],
        "distinct attempt records required",
    )
    require(
        failure["observed_at"] <= correction["observed_at"],
        "correction predates failure",
    )
    check_attempt(failure, False, originals)
    check_attempt(correction, True, originals)
    example = copy.deepcopy(failure)
    example["record_id"] = "paired-A/" + data.digest(
        [data.record_digest(failure), data.record_digest(correction)]
    )
    example["final_answer"] = correction["final_answer"]
    example["verified_outcome"] = copy.deepcopy(correction["verified_outcome"])
    example["available_at"] = max(failure["available_at"], correction["available_at"])
    for event in example["trajectory"]:
        event["trainable"] = False
    example["derivation"] = {
        "failure": data.record_digest(failure),
        "correction": data.record_digest(correction),
    }
    data.validate_record(example)
    return example


def known_source_keys(record):
    src = record["source"]
    keys = {
        "task": [src["repository"], record["task_id"]],
        "material": [src["sha256"], src.get("row_zero_based")],
    }
    for name in ("intake_receipt_sha256", "original_task_id", "operation_id"):
        if src.get(name):
            keys[name] = (
                [src["repository"], src[name]]
                if name != "intake_receipt_sha256"
                else src[name]
            )
    return {data.digest([key, value]) for key, value in keys.items()}


def check_future(request):
    source = request["candidate"].get("paired_source_exposure")
    if source is None:
        return
    for catalog in source["registered_catalogs"]:
        prospective_exposure.check_records(request, catalog)
    for record in request["future"]:
        require(
            record["origin_kind"] == "authorized_agent_run"
            and record["exposure"] == "unexposed"
            and record["authorization"]["training_allowed"] is False,
            "future requires a new evaluation-only task",
        )
        require(
            text_sha(record["task"]["input"]) not in source["known_prompt_hashes"]
            and not known_source_keys(record).intersection(source["source_keys"]),
            "future repeats enrolled A input or source",
        )


def sync_directory(path):
    import os

    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish_bytes(path, raw):
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(dir=path.parent) as tmp:
        tmp.write(raw)
        tmp.flush()
        os.fsync(tmp.fileno())
        try:
            os.link(tmp.name, path)
            sync_directory(path.parent)
        except FileExistsError:
            with path.open("rb") as existing:
                require(
                    existing.read(len(raw) + 1) == raw,
                    "existing original material differs",
                )


def capture_attempt(draft, destination, originals, record_path):
    """Execute a create-only artifact write chosen by the host and keep readback for A's later consent."""
    import os
    from pathlib import Path

    destination, originals, record_path = map(
        Path, (destination, originals, record_path)
    )
    record = copy.deepcopy(draft)
    data.validate_record(record, require_outcome=False)
    require(
        "verified_outcome" not in record
        and record["split"] == "train"
        and record["origin_kind"] == "authorized_agent_run",
        "uncaptured A training draft required",
    )
    require(
        record["task"]["verifier"]["name"] == "json_artifact"
        and record["task"]["verifier"]["version"] == "1",
        "unsupported artifact sink verifier",
    )
    require(record["trajectory"], "action trajectory required")
    last = record["trajectory"][-1]
    require(
        last["kind"] == "action"
        and last["actor"] in ("student", "teacher")
        and not last["executed"]
        and last["content"] == record["final_answer"],
        "terminal unexecuted submission required",
    )
    policy = sha(
        last.get("policy_sha256")
        if last["actor"] == "student"
        else record.get("model_digest")
    )
    source_sha = sha(record["source"]["sha256"])
    require(
        coding_sft.file_hash(originals / source_sha) == source_sha,
        "source material must be archived before capture",
    )
    semantic = data.verify_answer(record, record["final_answer"])
    originals.mkdir(mode=0o700, parents=True, exist_ok=True)
    archive = destination.parent / ".hepta-paired-writes"
    archive.mkdir(mode=0o700, exist_ok=True)
    # A per-submission inode distinguishes retrying our own write from finding an identical foreign file.
    staged = archive / data.digest([data.digest(draft), str(destination.absolute())])
    raw = last["content"].encode("utf-8")
    _publish_bytes(staged, raw)
    try:
        os.link(staged, destination)
        sync_directory(destination.parent)
    except FileExistsError:
        require(
            not destination.is_symlink() and os.path.samefile(staged, destination),
            "destination belongs to another write",
        )
    with destination.open("rb") as stream:
        observed = stream.read(len(raw) + 1)
    require(observed == raw, "stored bytes differ from submitted action")
    _publish_bytes(originals / text_sha(last["content"]), observed)
    _publish_bytes(originals / semantic["receipt_sha256"], data.canonical(semantic))
    operation = {
        "schema": "hepta.paired-learning.artifact-readback.v1",
        "record_id": record["record_id"],
        "task_id": record["task_id"],
        "actor": last["actor"],
        "source_sha256": source_sha,
        "input_sha256": text_sha(record["task"]["input"]),
        "policy_sha256": policy,
        "readback_sha256": hashlib.sha256(observed).hexdigest(),
        "semantic_receipt_sha256": semantic["receipt_sha256"],
    }
    commitment = data.digest(operation)
    _publish_bytes(originals / commitment, data.canonical(operation))
    if last.get("receipt_sha256") is not None:
        last["original_generation_receipt_sha256"] = last["receipt_sha256"]
    last.update(executed=True, receipt_sha256=commitment)
    record["verified_outcome"] = {
        "success": semantic["success"],
        "receipt_sha256": semantic["receipt_sha256"],
        "verifier_name": "json_artifact",
        "verifier_version": "1",
    }
    check_attempt(record, semantic["success"], originals)
    _publish_bytes(record_path, data.canonical(record) + b"\n")
    return record


if __name__ == "__main__":
    import argparse
    import os
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Place a new JSON artifact and retain the executed A attempt"
    )
    for name in ("draft", "new_destination", "originals", "signed_record_input"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    print(
        data.record_digest(
            capture_attempt(
                adoption.read_json(args.draft),
                args.new_destination,
                args.originals,
                args.signed_record_input,
            )
        )
    )
