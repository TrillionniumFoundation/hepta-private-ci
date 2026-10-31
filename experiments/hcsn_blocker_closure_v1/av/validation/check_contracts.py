"""Synthetic corruption checks for AV evidence readers; never load real media."""

import copy
import json
from pathlib import Path
import resource
import tempfile
import time

import numpy as np
import torch

from experiments.hcsn_blocker_closure_v1.av import analysis, study
from experiments.hcsn_blocker_closure_v1.av.metrics import evaluation_arrays
from experiments.hcsn_blocker_closure_v1.content import study as common


def main():
    started = time.process_time()
    sources = study.source_map()
    design = study.read(study.HERE / "AV_DESIGN.json")
    destination = study.HERE / "results" / "contract_checks002.json"
    if destination.exists():
        raise FileExistsError("Preserve every contract audit attempt")
    checks = []

    def check(name, function, reject=False):
        try:
            function()
        except ValueError:
            if not reject:
                raise
        else:
            if reject:
                raise AssertionError("Corrupt evidence was accepted: " + name)
        checks.append(dict(name=name, passed=True))

    with tempfile.TemporaryDirectory(prefix="hcsn-av-contract-") as temporary:
        temporary = Path(temporary)
        torch.manual_seed(992001)
        model = torch.nn.Linear(8, 6)
        common.save_state(model, temporary / "state.npz")
        assert analysis.tensor_hash(temporary / "state.npz") == common.state_hash(model.state_dict())
        checks.append(dict(name="independent_npz_and_live_tensor_hash_agree", passed=True))

        rng = np.random.default_rng(992003)
        n = 16
        outputs = {key: rng.normal(size=(n, width)).astype(np.float32) for key, width in
                   (("audio_embedding", 8), ("video_embedding", 8), ("audio_logits", 6), ("video_logits", 6))}
        outputs["fused_logits"] = .5 * (outputs["audio_logits"] + outputs["video_logits"])
        labels = np.arange(n) % 6
        actors = np.repeat(np.arange(4), 4).astype(str)
        clips = np.array([f"synthetic-{index}" for index in range(n)])
        arrays, summary = evaluation_arrays(outputs, labels, actors, clips, "synthetic")
        dataset = dict(y=labels, actor=actors, clip=clips)

        def evaluate(values):
            path = temporary / "synthetic.npz"
            np.savez_compressed(path, **values)
            row = dict(summary, file=path.name, sha256=study.digest(path))
            analysis.checked_evaluation(temporary, row, "synthetic", dataset)

        check("raw_evaluation_roundtrip", lambda: evaluate(arrays))
        corrupt = copy.deepcopy(arrays)
        corrupt["rank_audio_to_video_whole"][0] += 1
        check("changed_rank_rejected_even_with_updated_file_hash", lambda: evaluate(corrupt), reject=True)
        corrupt = copy.deepcopy(arrays)
        corrupt["fused_logits"][0, 0] += .5
        check("changed_fusion_rejected_even_with_updated_file_hash", lambda: evaluate(corrupt), reject=True)
        corrupt = copy.deepcopy(arrays)
        corrupt["labels"][0] = (corrupt["labels"][0] + 1) % 6
        check("changed_label_rejected_even_with_updated_file_hash", lambda: evaluate(corrupt), reject=True)

        rows = [dict(step=index + 1, training_cpu_seconds=clock, loss=4.,
                     components=dict(fused_ce=2., audio_ce=1., video_ce=1., symmetric_infonce=3.),
                     gradient_groups=dict(content=dict(l2=.5, nonzero=3, maximum_absolute=.4)),
                     physical=dict(audio={}, video={}))
                for index, clock in enumerate((15., 30., 45., 60.25))]
        result = dict(updates=4, training_cpu_seconds=60.25, training_cpu_budget_overrun_seconds=.25,
                      job=dict(stage="equal_cpu", updates=4),
                      validations=[dict(step=2, training_cpu_seconds=30.),
                                   dict(step=4, training_cpu_seconds=60.25)])

        def trajectory(values, report):
            path = temporary / "trajectory.json"
            study.write(path, values)
            analysis.validate_trajectory(path, report, design)

        check("first_complete_cpu_crossing_accepted", lambda: trajectory(rows, result))
        fixed = copy.deepcopy(result)
        fixed["job"]["stage"] = "fixed"
        check("fixed_midpoint_end_accepted", lambda: trajectory(rows, fixed))
        for name, mutate in (
            ("missing_update_rejected", lambda values, report: values.pop(1)),
            ("nonfinite_loss_rejected", lambda values, report: values[0].update(loss=float("nan"))),
            ("nonfinite_gradient_rejected", lambda values, report: values[0]["gradient_groups"]["content"].update(l2=float("nan"))),
            ("incorrect_loss_sum_rejected", lambda values, report: values[0].update(loss=4.5)),
            ("late_cpu_stop_rejected", lambda values, report: values[2].update(training_cpu_seconds=60.1)),
            ("clock_mismatch_rejected", lambda values, report: report.update(training_cpu_seconds=60.5)),
            ("wrong_midpoint_rejected", lambda values, report: report["validations"][0].update(step=1)),
        ):
            values, report = copy.deepcopy(rows), copy.deepcopy(result)
            mutate(values, report)
            check(name, lambda values=values, report=report: trajectory(values, report), reject=True)

    choices = dict(choices={arm: dict(learning_rate=.001) for arm in design["models"]})
    for stage, expected in design["expected_jobs"].items():
        jobs = analysis.job_matrix(design, choices, stage)
        assert len(jobs) == expected == len({row["id"] for row in jobs})
        if stage != "development":
            assert all(sorted(row["seed"] for row in jobs if row["arm"] == arm) == sorted(design["formal_seeds"])
                       for arm in design["models"])
        checks.append(dict(name=stage + "_exact_unique_design_matrix", passed=True))
    assert study.source_map() == sources
    study.write(destination, dict(schema="hcsn-av-synthetic-contract-checks.v1", passed=True, checks=checks,
        source_sha256=sources, audit_source_sha256=study.digest(__file__), real_data_loaded=False,
        previous_test_data_loaded=False, process_cpu_seconds=time.process_time(),
        contained_audit_cpu_seconds=time.process_time() - started,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024))
    print(json.dumps(dict(passed=True, checks=len(checks), real_data_loaded=False)))


if __name__ == "__main__":
    main()
