"""Cold adapter probes and source-growth diagnostics for the frozen study."""

import os
from pathlib import Path
import subprocess
import sys
import time

from . import adoption, circuit_study_v2, circuit_task_readout_v2, circuit_v2
from . import coding_sft, data, study_v2 as study
from .composition_core import digest as circuit_digest, require
from .study_v2_evidence import source_macro


def cold(root, name):
    """Reload one actual adapter in a new process using only a retained B request."""
    require(name in ("final_answer", "trajectory"), "cold adapter name differs")
    study.guard(root)
    root = Path(root)
    request = study.read(root / "cold_checks" / name / "REQUEST.json")
    model = study.manifest(root, name)
    identity = coding_sft.verify_model(model, root)
    require(
        identity == request["model_digest"]
        and data.digest(request["record"]) == request["record_digest"],
        "cold request/model changed",
    )
    predictor = coding_sft.load_predictor(model, root)
    try:
        prediction = predictor.predict(request["record"])
    finally:
        predictor.close()
    require(coding_sft.verify_model(model, root) == identity, "cold adapter changed")
    study.guard(root)
    return {
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "model_digest": identity,
        "request_digest": data.digest(request),
        "prediction": prediction,
        "checkpoint_recovery": True,
        "adoption_performed": False,
    }


def cold_probes(root, evaluations, models):
    root = Path(root)
    results = {}
    for name in ("final_answer", "trajectory"):
        report = evaluations[name]
        index = len(report["rows"]) - 1
        step = report["rows"][-1]["steps"][-1]
        warm = step["output"]
        actual_request = study.read(
            root / "evaluation/B" / name / str(index) / f"request-{step['number']}.json"
        )
        directory = root / "cold_checks" / name
        request = {
            "model_digest": data.digest(models[name]),
            "record": actual_request,
            "record_digest": data.digest(actual_request),
            "warm_output_digest": data.digest(warm),
            "warm_pid": warm["pid"],
            "scope": "same retained last B inference; no new task and no adoption",
        }
        coding_sft.write_new(directory / "REQUEST.json", request)
        started = time.perf_counter()
        command = [
            sys.executable,
            "-m",
            "cell_experiments.study_v2",
            "cold",
            "--root",
            str(root),
            "--name",
            name,
        ]
        try:
            process = subprocess.run(
                command, capture_output=True, text=True, timeout=300, check=False
            )
        except subprocess.TimeoutExpired as failure:
            coding_sft.write_new(
                directory / "PROCESS.json",
                {
                    "status": "TIMEOUT",
                    "stdout": str(failure.stdout or ""),
                    "stderr": str(failure.stderr or ""),
                    "wall_seconds": time.perf_counter() - started,
                },
            )
            raise ValueError("actual adapter cold probe timed out") from failure
        coding_sft.write_new(
            directory / "PROCESS.json",
            {
                "returncode": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr,
                "wall_seconds": time.perf_counter() - started,
            },
        )
        require(process.returncode == 0, "actual adapter cold probe failed")
        restored = data._parse(process.stdout)
        require(
            restored["pid"] != os.getpid()
            and restored["pid"] != warm["pid"]
            and restored["ppid"] == os.getpid()
            and restored["request_digest"] == data.digest(request)
            and restored["model_digest"] == data.digest(models[name]),
            "cold process binding differs",
        )
        require(
            adoption.comparable(restored["prediction"]) == adoption.comparable(warm),
            "cold adapter answer or token count differs",
        )
        for key in ("input_sha256", "rendered_input_sha256", "message_protocol"):
            require(
                restored["prediction"].get(key) == warm.get(key),
                "cold prompt protocol differs",
            )
        result = {
            "status": "MATCH",
            "name": name,
            "warm_pid": warm["pid"],
            "cold_pid": restored["pid"],
            "warm_output_digest": data.digest(warm),
            "cold": restored,
            "wall_seconds": time.perf_counter() - started,
            "new_independent_tasks": 0,
            "adoption_performed": False,
            "cold_checkpoint_recovery_verified": True,
        }
        coding_sft.write_new(directory / "RESULT.json", result)
        results[name] = result
    return results


def freeze_growth(
    root, a_rows, b_rows, base_plan, b_records, b_evaluations, models, capacity
):
    """Vary A source groups in the routing head, with fixed upstream experts."""
    root = Path(root)
    report = {
        "scope": "routing-head source scaling over already trained frozen experts; not growth of users or foundation-model training",
        "verified_users": 0,
        "experiments": {},
        "plans": {},
        "adoption_rate": None,
        "forgetting": None,
        "forgetting_reason": "no independent longitudinal retention panel",
        "full_system_cost": None,
        "independent_scientific_qualification": "BLOCKED",
    }
    for unit in ("project_id", "source_id"):
        plan = circuit_study_v2.source_growth_plan(
            a_rows, unit_field=unit, updates_per_source=224
        )
        report["plans"][unit] = plan
        coding_sft.write_new(root / "growth" / unit / "PLAN.json", plan)
        for setting in plan["settings"]:
            key = (
                unit + "/" + setting["regime"] + "-" + str(setting["requested_groups"])
            )
            if setting["status"] != "READY_FOR_DIAGNOSTIC":
                report["experiments"][key] = setting
                continue
            rows = [a_rows[i] for i in setting["row_indices"]]
            require(
                circuit_digest(rows) == setting["records_digest"],
                "E5 selected source rows differ",
            )
            run_plan = {**base_plan, "updates": setting["updates"]}
            model, training = circuit_v2.fit_arm(rows, run_plan, "single")
            b = circuit_v2.evaluate(model, b_rows)
            business = circuit_task_readout_v2.readout(
                {"arms": {"single": b}, "selected_arm": "single"},
                b_evaluations,
                models,
                b_records,
                b_rows,
                expected_panel_digest=data.digest(b_records),
                capacity_evidence=capacity,
            )
            directory = root / "growth" / key
            for filename, value in (
                ("INPUTS_A.json", rows),
                ("PLAN.json", run_plan),
                ("MODEL.json", model.record()),
                ("TRAINING.json", training),
                ("B.json", b),
                ("B_BUSINESS.json", business),
            ):
                coding_sft.write_new(directory / filename, value)
            report["experiments"][key] = {
                **setting,
                "status": "FROZEN",
                "directory": str(directory.relative_to(root)),
                "model_digest": circuit_digest(model.record()),
                "training_digest": circuit_digest(training),
                "b_digest": circuit_digest(b),
                "b_business_digest": data.digest(business),
                "B_business_source_macro": source_macro(
                    business["arms"]["single"]["main"]["rows"], "success"
                ),
                "actual_routing_training_kernel_cost": training["kernel_totals"],
                "effective_experience_count": setting[
                    "provenance_disjoint_task_clusters"
                ],
                "statistical_effective_sample_size": None,
                "uses_real_user_groups": False,
            }
    coding_sft.write_new(root / "growth" / "FROZEN.json", report)
    return report


def confirm_growth(root, frozen, c_rows, c_records, c_evaluations, models, capacity):
    root = Path(root)
    results = {}
    for key, setting in frozen["experiments"].items():
        if setting["status"] != "FROZEN":
            results[key] = setting
            continue
        directory = root / setting["directory"]
        model = circuit_v2.PathCircuit.restore(
            study.read(directory / "MODEL.json"), setting["model_digest"]
        )
        c = circuit_v2.evaluate(model, c_rows)
        business = circuit_task_readout_v2.readout(
            {"arms": {"single": c}, "selected_arm": "single"},
            c_evaluations,
            models,
            c_records,
            c_rows,
            expected_panel_digest=data.digest(c_records),
            capacity_evidence=capacity,
        )
        coding_sft.write_new(directory / "C.json", c)
        coding_sft.write_new(directory / "C_BUSINESS.json", business)
        results[key] = {
            **setting,
            "C": c,
            "C_business": business,
            "C_business_source_macro": source_macro(
                business["arms"]["single"]["main"]["rows"], "success"
            ),
        }
    return {
        **frozen,
        "experiments": results,
        "selected_settings_changed_after_C": False,
    }
