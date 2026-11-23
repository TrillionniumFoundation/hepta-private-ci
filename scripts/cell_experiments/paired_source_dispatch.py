"""Check the source authority's pre-arrival retention record for a new A candidate."""

from pathlib import Path

from . import adoption, data, paired_people, paired_source_gate


def authorize(snapshot, anchor, path):
    report = adoption.read_json(Path(path))
    adoption.require(
        data.digest(report) == anchor.get("source_retention_sha256"),
        "source retention was not committed by the freeze witness",
    )
    adoption.require(
        report["schema"] == "hepta.paired-learning.source-retention.v1"
        and report["policy"] == paired_source_gate.POLICY
        and report["freeze_sha256"] == data.digest(snapshot)
        and report["parent_sha256"] == data.digest(snapshot["parent"])
        and report["candidate_sha256"] == data.digest(snapshot["candidate"])
        and report["prospective_records_read"] == 0,
        "source retention receipt does not identify this pre-arrival pair",
    )
    rows = [r for r in report["comparisons"] if r["panel"] == "retention"]
    adoption.require(
        [r["record_sha256"] for r in rows]
        == [data.record_digest(r) for r in snapshot["retention"]]
        and rows
        and all(type(r[k]) is bool for r in rows for k in ("parent", "candidate")),
        "source retention coverage differs",
    )
    baseline = [r for r in rows if r["parent"]]
    adoption.require(
        report["decision"] == "eligible_for_prospective_evaluation"
        and baseline
        and all(r["candidate"] for r in baseline),
        "source retention gate did not permit prospective dispatch",
    )
    adoption.require(
        report["scope"] == "owner_intake", "source training lacks original owner scope"
    )
    return data.digest(report)


def verify_originals(path, study, freeze):
    """Register the protected training completion and original cold outputs at their source."""
    path = Path(path)
    folder = path.parent
    report = adoption.read_json(path)
    snapshot = adoption.read_json(folder / "FROZEN.json")
    completed = adoption.read_json(folder / "COMPLETED.json")
    owner = adoption.read_json(folder / "OWNER.json")
    adoption.require(
        data.digest(snapshot) == freeze
        and completed["schema"] == "hepta.paired-learning.source-completion.v1"
        and completed["study_sha256"] == study
        and completed["freeze_sha256"] == freeze
        and completed["future_records_consumed"] == 0
        and completed["parent_sha256"] == data.digest(snapshot["parent"])
        and completed["candidate_sha256"] == data.digest(snapshot["candidate"])
        and completed["owner_receipt_sha256"] == data.digest(owner)
        and report["source_completion_sha256"] == data.digest(completed)
        and report["scope"] == completed["scope"],
        "original source completion, owner or freeze differs",
    )
    panels = [("known_A", completed["failure_sha256"])]
    panels.extend(("retention", data.record_digest(r)) for r in snapshot["retention"])
    observed = [{"panel": panel, "record_sha256": digest} for panel, digest in panels]
    arm_inputs = {}
    for arm in ("parent", "candidate"):
        raw = adoption.read_json(folder / "cold-retention" / (arm + ".json"))
        adoption.require(
            data.digest(raw) == report["cold_receipts"][arm]
            and raw["arm"] == arm
            and raw["model"] == completed[arm + "_sha256"]
            and len(raw["rows"]) == len(observed),
            "original cold receipt differs",
        )
        arm_inputs[arm] = []
        for i, (comparison, row) in enumerate(zip(observed, raw["rows"], strict=True)):
            pred = row["prediction"]
            adoption.require(
                row["panel"] == comparison["panel"]
                and row["record_sha256"] == comparison["record_sha256"]
                and pred["loaded_model_digest"] == raw["model"]
                and pred["pid"] == raw["pid"]
                and type(row["outcome"]["success"]) is bool,
                "original cold row belongs to another arm or record",
            )
            if comparison["panel"] == "retention":
                expected = data.verify_answer(
                    snapshot["retention"][i - 1], pred["answer"]
                )
                adoption.require(
                    data.digest(row["outcome"]) == data.digest(expected),
                    "original retention score differs",
                )
            comparison[arm] = row["outcome"]["success"]
            arm_inputs[arm].append(pred["input_ids"])
    adoption.require(
        arm_inputs["parent"] == arm_inputs["candidate"]
        and observed == report["comparisons"],
        "original cold comparisons differ",
    )
    digest = authorize(snapshot, {"source_retention_sha256": data.digest(report)}, path)
    adoption.require(
        owner["schema"] == "hepta.paired-learning.consent-readback.v1"
        and owner["use"] == "train"
        and owner["study_sha256"] == study,
        "original source lacks the matching native training consent",
    )
    paired_people.check_training_statement(owner, completed)
    return digest
