"""Consume unsigned correction observations without upgrading their authority.

Only the final corrected text is a supervision candidate. The teacher's observed
answer never appears as a prior context answer or an executed action. Native
permission, signed native labels and the late Evaluator remain separate gates.
"""

import copy
import os
from pathlib import Path
import stat

from . import data, opaque_teacher_data as opaque

DERIVED = "hepta.paired-learning.opaque-derived.v1"


def _read_original(originals, digest, maximum):
    """Read one bounded private original by commitment, never a record-supplied path."""
    opaque.sha(digest)
    path = Path(originals)
    data._require(
        path.is_absolute() and ".." not in path.parts,
        "absolute originals path required",
    )
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = child
        info = os.fstat(directory)
        data._require(
            info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
            "private owned originals directory required",
        )
        fd = os.open(
            digest, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            data._require(
                stat.S_ISREG(before.st_mode)
                and before.st_uid == os.geteuid()
                and stat.S_IMODE(before.st_mode) == 0o600
                and 0 < before.st_size <= maximum,
                "bounded private regular original required",
            )
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        fields = (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
            "st_mode",
            "st_uid",
        )
        data._require(
            all(getattr(before, k) == getattr(after, k) for k in fields)
            and len(raw) == before.st_size,
            "original changed while reading",
        )
        return raw
    finally:
        os.close(directory)


def capture_correction(
    draft,
    originals,
    record_path,
    *,
    prompt_item_id,
    answer_item_id,
    student_policy_sha256,
):
    """Materialize a declared correction; the returned receipts grant no Train authority."""
    from . import paired_source

    originals = Path(originals)
    source = _read_original(
        originals, draft["source"]["sha256"], opaque.MAX_SOURCE_BYTES
    )
    record = opaque.from_capture(
        draft,
        source,
        prompt_item_id=prompt_item_id,
        answer_item_id=answer_item_id,
        student_policy_sha256=student_policy_sha256,
    )
    receipt = opaque.verify_answer(record)
    record["verified_outcome"] = {
        "success": receipt["success"],
        "receipt_sha256": receipt["receipt_sha256"],
        "verifier_name": "json_artifact",
        "verifier_version": "1",
    }
    opaque.validate_record(record)
    paired_source._publish_bytes(
        originals / receipt["receipt_sha256"], data.canonical(receipt)
    )
    paired_source._publish_bytes(Path(record_path), data.canonical(record))
    return record


def check_correction(record, originals):
    opaque.validate_record(record)
    data._require(
        record["authorization"]["training_allowed"] is True, "A must permit training"
    )
    opaque.verify_source(
        record,
        _read_original(originals, record["source"]["sha256"], opaque.MAX_SOURCE_BYTES),
    )
    computed = opaque.verify_answer(record)
    outcome = record["verified_outcome"]
    data._require(
        computed["success"] is True
        and outcome["success"] is True
        and computed["receipt_sha256"] == outcome["receipt_sha256"],
        "opaque correction semantic check differs",
    )
    raw = _read_original(originals, outcome["receipt_sha256"], opaque.MAX_RECORD_BYTES)
    data._require(
        data.canonical(data._parse(raw)) == data.canonical(computed),
        "complete unsigned semantic receipt differs",
    )


def _project(failure, correction):
    """Pure projection; raw-source and execution checks belong to derive's owner."""
    data.validate_record(failure)
    opaque.validate_record(correction)
    for key in ("task_id", "lineage_id", "project_id", "task"):
        data._require(
            failure[key] == correction[key],
            "failure and correction describe different tasks",
        )
    data._require(
        failure["source"]["repository"] == correction["source"]["repository"]
        and failure["record_id"] != correction["record_id"]
        and failure["observed_at"] <= correction["observed_at"],
        "different or unordered original attempts",
    )
    data._require(
        failure["split"] == "train"
        and failure["origin_kind"] == "authorized_agent_run"
        and failure["authorization"]["training_allowed"] is True
        and correction["authorization"]["training_allowed"] is True
        and failure["verified_outcome"]["success"] is False
        and correction["verified_outcome"]["success"] is True,
        "A must permit a failed/corrected pair",
    )
    actions = [event for event in failure["trajectory"] if event["executed"]]
    data._require(
        actions
        and actions[-1]["actor"] == "student"
        and actions[-1]["content"] == failure["final_answer"]
        and actions[-1]["policy_sha256"]
        == correction["teacher_observation"]["student_policy_sha256"],
        "observation does not bind the original student policy declaration",
    )
    example = copy.deepcopy(failure)
    example.update(
        schema=DERIVED,
        record_id="paired-opaque-A/"
        + data.digest([data.record_digest(failure), data.record_digest(correction)]),
        final_answer=correction["final_answer"],
        verified_outcome=copy.deepcopy(correction["verified_outcome"]),
        available_at=max(failure["available_at"], correction["available_at"]),
        original_pair={
            "failure": copy.deepcopy(failure),
            "correction": copy.deepcopy(correction),
        },
        derivation={
            "failure": data.record_digest(failure),
            "correction": data.record_digest(correction),
        },
        production_eligible=False,
        human_training_consent_proven=False,
    )
    for event in example["trajectory"]:
        event["trainable"] = False
    return example


def derive(failure, correction, originals):
    from . import paired_source

    paired_source.check_attempt(failure, False, originals)
    check_correction(correction, originals)
    return _project(failure, correction)


def training_example(record, mode):
    """Encode the verified derivation; never convert teacher observations to actions."""
    data._require(
        record.get("schema") == DERIVED and mode in ("final_answer", "trajectory"),
        "invalid opaque derived example",
    )
    pair = record.get("original_pair", {})
    expected = _project(pair["failure"], pair["correction"])
    data._require(
        data.canonical(expected) == data.canonical(record), "opaque derivation changed"
    )
    segments = []
    if mode == "trajectory":
        for event in record["trajectory"]:
            segments.append(
                {
                    "role": "tool" if event["kind"] == "observation" else "assistant",
                    "content": event["content"],
                    "train": False,
                    "trainable": False,
                    "actor": event["actor"],
                    "kind": event["kind"],
                }
            )
    segments.append(
        {
            "role": "assistant",
            "content": record["final_answer"],
            "train": True,
            "trainable": True,
            "actor": "answer",
            "kind": "final_answer",
        }
    )
    return {
        "record_id": record["record_id"],
        "input": record["task"]["input"],
        "target_text": "\n".join(s["content"] for s in segments),
        "segments": segments,
        "source_sha256": record["source"]["sha256"],
        "record_sha256": data.digest(record),
        "mode": mode,
    }
