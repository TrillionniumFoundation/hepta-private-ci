"""Run one authored, uncredentialed development case. The native human path is a separate entry."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from cell_experiments import (
    adoption,
    coding_sft,
    data,
    paired_source_train,
    paired_freeze,
)
from cell_experiments.test_paired_source import capture

STUDY = "00e43fc72bb1cc2545d6f1d13fa67c448f413343c5e0c3ce1fdd9de91086f5fa"


def read(path):
    return json.loads(path.read_bytes())


def generate(root, which):
    if which == "parent":
        manifest = read(root / "parent.json")
    else:
        frozen = read(next((root / "paired-training").glob("*/FROZEN.json")))
        manifest = frozen["candidate"]
    p = coding_sft.load_predictor(manifest, root)
    prompt = "Return the JSON integer one for this amber receipt."
    try:
        old = read(root / "retention.json")[0]
        return {
            "pid": os.getpid(),
            "model": data.digest(manifest),
            "a": p.predict({"task": {"input": prompt}}, retain_encoding=True),
            "old": p.predict(old, retain_encoding=True),
        }
    finally:
        p.close()


def run(case, root):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    parent = read(case / "parent.json")
    if (
        data.digest(parent)
        != "e4173baea6cdb1e6278ce556c6a7f4bab64efd3312d132964675c37d4a24d3a1"
    ):
        raise ValueError("wrong owned seed")
    shutil.copytree(case / "parent-checkpoint", root / "parent-checkpoint")
    coding_sft.write_new(root / "parent.json", parent)
    old = read(case / "plan.json")["retention"]
    coding_sft.write_new(root / "retention.json", [old])

    def cold(arm):
        subprocess.run(
            [sys.executable, __file__, str(case), str(root), "--cold", arm],
            check=True,
            timeout=120,
        )
        return read(root / (arm + "-predictions.json"))

    first = cold("parent")
    failure = capture(
        root, "failure", first["a"]["answer"], data.digest(parent), first["a"], 1
    )
    correction = capture(
        root,
        "correction",
        "1",
        data.digest("authored-constant-one-policy-v1"),
        {"policy": "authored-constant-one-policy-v1", "output": "1"},
        2,
    )
    spec = {
        "schema": paired_source_train.SPEC,
        "study": STUDY,
        "delivery": data.digest("engineering-no-human"),
        "failure": data.record_digest(failure),
        "correction": data.record_digest(correction),
        "parent": data.digest(parent),
        "retention": data.digest([old]),
        "trainer_source_sha256": paired_source_train.source_hash(),
        "mode": "trajectory",
        "training": {
            "steps": 64,
            "retry_reserve": 1,
            "sequence_tokens": 192,
            "rank": 4,
            "seed": 1709,
            "learning_rate": 0.01,
            "adapter_target_modules": ["c_attn", "c_proj"],
        },
        "timeout_seconds": 120,
    }
    coding_sft.write_new(root / "SPEC.json", spec)
    fixture_owner = {
        "scope": "authored_engineering_fixture",
        "authenticated_human": False,
    }
    result = paired_source_train._fit_after_verification(root, spec, fixture_owner)
    second = cold("candidate")
    op = next((root / "paired-training").glob("*/FROZEN.json")).parent
    receipt = next((root / "models").glob("*/training.json"))
    before = receipt.read_bytes()
    replay = paired_source_train._fit_after_verification(root, spec, fixture_owner)
    if replay != result or receipt.read_bytes() != before:
        raise ValueError("retry changed the update")
    # The normal prospective interface must reject a renamed enrolled A. No future task is evaluated.
    r = json.loads(json.dumps(failure))
    r.update(
        record_id="engineering-negative",
        task_id="renamed",
        split="confirmation",
        exposure="unexposed",
    )
    r["authorization"]["training_allowed"] = False
    source = root / "overlap-control.json"
    coding_sft.write_new(source, [r])
    try:
        paired_freeze.assemble(
            op / "FROZEN.json",
            result["freeze_sha256"],
            source,
            root / "forbidden.json",
            materials=root,
        )
    except adoption.EvidenceError as err:
        if "enrolled A" not in str(err) and "input token" not in str(err):
            raise
    else:
        raise ValueError("known training input was admitted")
    summary = {
        "scope": "engineering_fixture",
        "model_updates": read(receipt)["steps"],
        "native_humans": 0,
        "future_records": 0,
        "retry_identical": True,
        "renamed_A_refused": True,
        "outputs": {},
        "commitments": result,
    }
    for arm, outputs in (("parent", first), ("candidate", second)):
        summary["outputs"][arm] = {
            k: {
                "text": outputs[k]["answer"],
                "pass": data.verify_answer(row, outputs[k]["answer"])["success"],
                "input_tokens": outputs[k]["input_tokens"],
                "output_tokens": outputs[k]["output_tokens"],
            }
            for k, row in (("a", failure), ("old", old))
        }
    coding_sft.write_new(root / "SUMMARY.json", summary)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("case", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--cold", choices=["parent", "candidate"])
    a = p.parse_args()
    os.umask(0o077)
    if a.cold:
        coding_sft.write_new(
            a.output / (a.cold + "-predictions.json"), generate(a.output, a.cold)
        )
    else:
        run(a.case, a.output)
