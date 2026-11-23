"""Train one new Hepta candidate from an admitted private A, then freeze it before any B.

Trusted Linux launcher: python -m cell_experiments.paired_source_train MATERIALS SPEC
SPEC_SHA BINARY BINARY_SHA ROOT_PID SQLITE_HOME ROUTE. Preserve original Root fds 3/4.
The incoming record files stay closed until the live native consent check returns.
"""

import argparse
import fcntl
import math
import os
from pathlib import Path

from . import (
    adoption,
    chat_protocol,
    coding_sft,
    data,
    paired_cold,
    paired_freeze,
    paired_source,
    paired_source_fit,
    prospective_exposure,
)

require = adoption.require
SPEC = "hepta.paired-learning.source-plan.v1"


def check_spec(spec):
    require(
        set(spec)
        == {
            "schema",
            "study",
            "delivery",
            "failure",
            "correction",
            "parent",
            "retention",
            "trainer_source_sha256",
            "mode",
            "training",
            "timeout_seconds",
        }
        and spec["schema"] == SPEC,
        "invalid A-only source plan",
    )
    for k in (
        "study",
        "delivery",
        "failure",
        "correction",
        "parent",
        "retention",
        "trainer_source_sha256",
    ):
        paired_source.sha(spec[k])
    require(
        spec["failure"] != spec["correction"]
        and spec["mode"] in ("final_answer", "trajectory"),
        "distinct failure/correction and known supervision mode required",
    )
    settings = spec["training"]
    require(
        set(settings)
        == {
            "rank",
            "learning_rate",
            "seed",
            "steps",
            "sequence_tokens",
            "adapter_target_modules",
            "retry_reserve",
        },
        "unknown or missing training settings",
    )
    for k, lo, hi in (
        ("rank", 1, 256),
        ("steps", 1, 4096),
        ("sequence_tokens", 16, 4096),
        ("seed", 0, 2**32 - 1),
    ):
        require(
            type(settings[k]) is int and lo <= settings[k] <= hi,
            "invalid training " + k,
        )
    targets = settings["adapter_target_modules"]
    require(
        isinstance(targets, list)
        and 0 < len(targets) <= 16
        and all(isinstance(t, str) and t.isidentifier() for t in targets)
        and len(set(targets)) == len(targets),
        "invalid LoRA target list",
    )
    require(
        type(settings["retry_reserve"]) is int
        and 0 <= settings["retry_reserve"] <= settings["steps"],
        "invalid retry reserve",
    )
    rate = settings["learning_rate"]
    require(
        type(rate) in (int, float) and math.isfinite(rate) and 0 < rate <= 1,
        "invalid learning rate",
    )
    require(
        type(spec["timeout_seconds"]) is int and 0 < spec["timeout_seconds"] <= 86400,
        "invalid evaluation limit",
    )


def source_hash():
    # Pin the executable source of this training and authorization path.
    from . import paired_intake

    modules = [
        adoption,
        chat_protocol,
        coding_sft,
        data,
        paired_cold,
        paired_freeze,
        paired_intake,
        paired_source,
        paired_source_fit,
        prospective_exposure,
    ]
    paths = [Path(__file__), *(Path(m.__file__) for m in modules)]
    return data.digest({p.name: coding_sft.file_hash(p) for p in paths})


def agree_or_write(path, value):
    if path.exists():
        require(
            data.digest(adoption.read_json(path)) == data.digest(value),
            "previous operation differs",
        )
    else:
        paired_freeze.publish(value, path)


def executable_exposures(materials, parent, records, example, spec):
    tok = paired_cold.frozen_tokenizer(parent, materials)
    protocol = chat_protocol.protocol_name(parent["runtime"])
    token_ids = set()
    for r in records:
        task = r["task"]
        prompt = coding_sft.prompt_text(
            task["input"], tok, protocol, task.get("messages")
        )
        token_ids.add(data.digest(tok.encode(prompt, add_special_tokens=False)))
    examples = chat_protocol.training_examples([example], spec["mode"], protocol)
    length = spec["training"]["sequence_tokens"]
    for ex in examples:
        rows = (
            chat_protocol.encode_native_turns(tok, ex, length)
            if protocol == chat_protocol.NATIVE
            else [coding_sft.encode_example(tok, ex, length)]
        )
        for row in rows:
            start = next(i for i, label in enumerate(row["labels"]) if label != -100)
            token_ids.add(data.digest(row["input_ids"][:start]))
    prior = parent.get("paired_source_exposure", {})
    known_input = paired_source.text_sha(example["task"]["input"])
    current_tokens = sorted(token_ids)
    catalogs = list(prior.get("registered_catalogs", []))
    direct = prospective_exposure.catalog_for(parent)
    if direct is not None:
        catalogs.append(direct)
    for item in catalogs:
        token_ids.update(r["input_ids_sha256"] for r in item["known_inputs"])
    current_keys = set.union(
        *(paired_source.known_source_keys(record) for record in records)
    )
    keys = current_keys.union(prior.get("source_keys", []))
    return {
        "schema": "hepta.paired-learning.source-exposure.v1",
        "record_digests": [data.record_digest(r) for r in records],
        "prompt_sha256": known_input,
        "known_prompt_hashes": sorted(
            set(prior.get("known_prompt_hashes", [])) | {known_input}
        ),
        "input_ids_sha256": sorted(token_ids.union(prior.get("input_ids_sha256", []))),
        "source_keys": sorted(keys),
        "registered_catalogs": catalogs,
        "current_source_keys": sorted(current_keys),
        "current_input_ids": current_tokens,
    }


def _fit_after_verification(materials, spec, owner):
    """Private host or qualification driver after the original scope has been checked."""
    check_spec(spec)
    require(source_hash() == spec["trainer_source_sha256"], "trainer source changed")
    root = Path(materials)
    parent = paired_source.read_bound(root / "parent.json", spec["parent"])
    coding_sft.verify_model(parent, root)
    retention = paired_source.read_bound(root / "retention.json", spec["retention"])
    paired_cold.checked_panels({"retention": retention}, parent["runtime"])
    records = [
        paired_source.read_bound(root / (label + ".json"), spec[label])
        for label in ("failure", "correction")
    ]
    derived = paired_source.derive(*records, root / "originals")
    exposures = executable_exposures(root, parent, records, derived, spec)
    for row in retention:
        require(
            row["split"] != "train"
            and row["authorization"]["training_allowed"] is False,
            "retention must be evaluation-only",
        )
        require(
            paired_source.text_sha(row["task"]["input"]) != exposures["prompt_sha256"]
            and not paired_source.known_source_keys(row).intersection(
                exposures["current_source_keys"]
            ),
            "A overlaps the fixed retention panel",
        )
    # Use each parent/retention task's actual tokenizer representation before spending updates.
    retained_ids = paired_cold.token_inputs(
        {"future": [], "retention": retention, "candidate": parent, "parent": parent},
        parent,
        root,
    )
    require(
        not set(retained_ids.values()).intersection(exposures["current_input_ids"]),
        "A shares frozen tokens with retention",
    )
    plan = {
        "parent_model_digest": spec["parent"],
        "train_sources": [derived["source_id"]],
        "training_records_digest": data.digest([derived]),
        "training_mode": spec["mode"],
        "source_digest": spec["trainer_source_sha256"],
        "training": spec["training"],
        "training_owner": "paired-source-A",
        "paired_source_exposure": exposures,
    }
    key = data.digest([spec["study"], spec["failure"], spec["correction"]])
    op = root / "paired-training" / key
    op.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = "paired-source-" + key
    model_out = root / "models" / name
    with (op / "lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        agree_or_write(op / "PLAN.json", spec)
        agree_or_write(op / "OWNER.json", owner)
        if (model_out / "training.json").is_file() and (
            model_out / "manifest.json"
        ).is_file():
            manifest = adoption.read_json(model_out / "manifest.json")
            receipt = adoption.read_json(model_out / "training.json")
        else:
            manifest, receipt = paired_source_fit.train(
                derived, parent, root, plan, name
            )
        require(
            receipt["status"] == "COMPLETE"
            and receipt["plan_digest"] == data.digest(plan)
            and receipt["records_digest"] == plan["training_records_digest"]
            and receipt["parameter_change"] is True
            and receipt["candidate_model_digest"]
            == coding_sft.verify_model(manifest, root),
            "training material or completed update differs",
        )
        snapshot_spec = {
            "parent": parent,
            "candidate": manifest,
            "retention": retention,
            "timeout_seconds": spec["timeout_seconds"],
        }
        agree_or_write(op / "freeze-spec.json", snapshot_spec)
        frozen = op / "FROZEN.json"
        expected = {"schema": paired_freeze.FREEZE_SCHEMA, **snapshot_spec}
        if not frozen.exists():
            paired_freeze.freeze(op / "freeze-spec.json", root, frozen)
        require(
            data.digest(adoption.read_json(frozen)) == data.digest(expected),
            "stored freeze differs",
        )
        scope = (
            "owner_intake"
            if owner.get("schema") == "hepta.paired-learning.consent-readback.v1"
            else "engineering_fixture"
        )
        result = {
            "schema": "hepta.paired-learning.source-completion.v1",
            "scope": scope,
            "independent_human_identity_established": False,
            "study_sha256": spec["study"],
            "source_plan_sha256": data.digest(spec),
            "owner_receipt_sha256": data.digest(owner),
            "failure_sha256": spec["failure"],
            "correction_sha256": spec["correction"],
            "parent_sha256": spec["parent"],
            "candidate_sha256": data.digest(manifest),
            "freeze_sha256": data.digest(expected),
            "training_receipt_sha256": data.digest(receipt),
            "steps": receipt["steps"],
            "future_records_consumed": 0,
        }
        agree_or_write(op / "COMPLETED.json", result)
        paired_source.sync_directory(op)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in (
        "materials",
        "spec",
        "spec_sha",
        "consent_binary",
        "binary_sha",
        "root_pid",
        "sqlite_home",
        "route",
    ):
        parser.add_argument(argument)
    args = parser.parse_args()
    from .paired_intake import verify_live

    os.umask(0o077)
    # The launcher holds these original capabilities before any file is opened in this process.
    os.fstat(3)
    os.fstat(4)
    spec = paired_source.read_bound(args.spec, args.spec_sha)
    check_spec(spec)
    with open(args.consent_binary, "rb") as binary:
        require(
            binary.read(4) == b"\x7fELF",
            "registered Linux native consent binary required",
        )
    try:
        owner = verify_live(
            args.consent_binary,
            args.binary_sha,
            spec["study"],
            spec["delivery"],
            {
                "use": "train",
                "failure": spec["failure"],
                "correction": spec["correction"],
            },
            (args.root_pid, args.sqlite_home, args.route),
        )
    finally:
        os.close(3)
        os.close(4)
    result = _fit_after_verification(args.materials, spec, owner)
    print(data.canonical(result).decode())


if __name__ == "__main__":
    main()
