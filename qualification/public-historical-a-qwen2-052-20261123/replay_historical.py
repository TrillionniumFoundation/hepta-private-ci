"""Read-only cold replay of an already seen training task and one authored retention item."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from cell_experiments import coding_sft, data
from historical_a import PARQUET, QUERY, TARGET, check, cold

FROZEN = "447ace5cc8bc031cc772e63ccb90380f16fc81404003bc04057ec4f8b7470ef6"


def read(path):
    return json.loads(path.read_bytes())


def frozen_models(root):
    freeze = read(root / "FROZEN.json")
    check(data.digest(freeze) == FROZEN, "wrong historical freeze")
    for arm in ("parent", "candidate"):
        model = read(root / (arm + ".json"))
        check(
            model == freeze[arm]
            and coding_sft.verify_model(model, root) == data.digest(model),
            "frozen model differs",
        )
    return freeze


def replay(parquet, root, out):
    models = frozen_models(root)
    check(coding_sft.file_hash(parquet) == PARQUET, "different public release")
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    work = dict(
        scope="retrospective_historical_A_and_authored_retention",
        freeze_sha256=FROZEN,
        public_parquet_sha256=PARQUET,
        historical_prompt_sha256=QUERY,
        historical_target_sha256=TARGET,
        historical_source_row=52,
        retention_digest=data.digest(models["retention"]),
        future_records=0,
        prospective_arrivals=0,
        certified_hepta_users=0,
    )
    coding_sft.write_new(out / "REQUEST.json", work)
    results = {}
    for arm in ("parent", "candidate"):
        command = [
            sys.executable,
            __file__,
            "--arm",
            arm,
            str(parquet),
            str(root),
            str(out),
        ]
        with subprocess.Popen(
            command,
            env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
        ) as process:
            try:
                status = process.wait(timeout=models["timeout_seconds"])
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise
            if status:
                raise subprocess.CalledProcessError(status, command)
        file = out / (arm + "-cold.json")
        raw = read(file)
        check(
            raw["arm"] == arm
            and raw["pid"] == process.pid
            and raw["ppid"] == os.getpid(),
            "different cold child",
        )
        rows = raw["rows"]
        check(
            set(rows) == {"historical_training_A", "old_capability"}, "wrong task scope"
        )
        for row in rows.values():
            check(
                row["pid"] == process.pid
                and row["loaded_model_digest"] == data.digest(models[arm]),
                "different predictor",
            )
        results[arm] = dict(
            pid=process.pid,
            model_sha256=data.digest(models[arm]),
            raw_file_sha256=coding_sft.file_hash(file),
            outcomes={k: v["success"] for k, v in rows.items()},
            model_calls=len(rows),
            input_tokens=sum(v["input_tokens"] for v in rows.values()),
            output_tokens=sum(v["output_tokens"] for v in rows.values()),
        )
    check(
        results["parent"]["pid"] != results["candidate"]["pid"]
        and frozen_models(root) == models,
        "cold isolation or disk changed",
    )
    result = dict(
        **work,
        request_sha256=data.digest(work),
        arms=results,
        external_teachers_used=0,
        weight_updates=0,
        adoption=False,
        native_full_iteration_claimed=False,
    )
    coding_sft.write_new(out / "RESULT.json", result)
    print(data.digest(result))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arm", choices=("parent", "candidate"))
    for arg in ("parquet", "materials", "output"):
        p.add_argument(arg, type=Path)
    a = p.parse_args()
    if a.arm:
        frozen_models(a.materials)
        cold(a.materials, a.arm, a.parquet, a.output)
    else:
        replay(a.parquet, a.materials, a.output)
