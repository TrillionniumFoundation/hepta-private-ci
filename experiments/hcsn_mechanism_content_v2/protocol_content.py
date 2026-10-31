"""Freeze content capacity, common initialization, budgets and heldout diagnostics."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys


NAMESPACE = Path("experiments/hcsn_mechanism_content_v2")


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True); stream.write("\n")


def make(root, python, output):
    root, output = Path(root).resolve(), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    templates = output / "jobs"
    templates.mkdir()
    results = NAMESPACE / "results/content001/jobs"
    jobs, task_configs = [], []
    for task in ("selective_copy", "mqar", "async_av", "av_binding"):
        audiovisual = task in ("async_av", "av_binding")
        for seed in (81031, 81032, 81033):
            shared_id = f"{task}_s{seed}_shared"
            shared_path = results / shared_id
            common = dict(schema="hcsn-content-v2.job", task=task, seed=seed, width=32,
                depth=2, physical=1, data_seed=2026110103, train_size=512,
                validation_size=128, eval_size=256, length=32,
                eval_lengths=[32] if audiovisual else [32, 64, 128],
                batch_size=6 if audiovisual else 16, eval_batch_size=6 if audiovisual else 16,
                validate_every=32, learning_rate=.003, clip_grad_norm=1., freeze_groups=[],
                diagnostics=True, allow_initial_selection=True)
            if audiovisual:
                common.update(av_directory="experiments/hcsn_task_value_v1/results/async_frontend001/data",
                              av_window_seconds=.1)
            if task == "av_binding":
                common.update(binding_deadline_seconds=1.5, binding_pair_seed=2026110173)
            configurations = [(shared_id, dict(common, family="shared", content_mode="joint",
                updates=512 if audiovisual else 1024, budget_label="shared_pretraining"), [])]
            for mode in ("frozen_shared", "joint"):
                for budget in ("updates256", "cpu20"):
                    for family in ("two_gate", "analytic"):
                        job_id = f"{task}_s{seed}_{family}_{mode}_{budget}"
                        config = dict(common, family=family, content_mode=mode, budget_label=budget,
                                      pretrained_from=str(shared_path))
                        if budget == "updates256":
                            config["updates"] = 256
                        else:
                            config.update(max_updates=100000, budget_cpu_seconds=20.)
                        configurations.append((job_id, config, [shared_id]))
            for job_id, config, dependencies in configurations:
                path = results / job_id
                template = templates / (job_id + ".json")
                save(template, config)
                relative_template = str(template.resolve().relative_to(root))
                task_configs.append(relative_template)
                jobs.append(dict(id=job_id, depends=dependencies,
                    argv=[str(python), "-m", "experiments.hcsn_mechanism_content_v2.worker",
                          "--template", relative_template, "--output", str(path), "--allow-test"],
                    outputs=[str(path / name) for name in ("job.json", "summary.json", "selection.json",
                        "selected.pt", "final.pt", "initial_parameters.pt", "access.jsonl", "trace.jsonl",
                        "inference_profile_validation.json", "data_preparation_costs.json")]))
    random.Random(2026103107).shuffle(jobs)
    sources = [NAMESPACE / name for name in ("__init__.py", "content.py", "content_train.py",
        "data.py", "binding_data.py", "worker.py", "study.py", "protocol_content.py")]
    baseline = [json.loads(row) for row in (root / NAMESPACE / "provenance/source_files.jsonl").read_text().splitlines()]
    sources += [Path(row["path"]) for row in baseline if row["path"].endswith(".py")]
    data = json.loads((root / NAMESPACE / "DATA_IDENTITY_VERIFIED.json").read_text())["verified_members"]
    sources += [Path(row["path"]) for row in data]
    sources += [Path(path) for path in task_configs]
    frozen = [dict(path=str(path), sha256=hashlib.sha256((root / path).read_bytes()).hexdigest())
              for path in sorted(set(sources))]
    plan = dict(schema="hcsn-fourtrack-content-protocol.v1",
        frozen_at_utc=datetime.now(timezone.utc).isoformat(), repository_root=str(root),
        source_base_commit="9709af902dc029efc007e4122425c6a72f0559b9", frozen_files=frozen, jobs=jobs,
        matrix="4 tasks x 3 seeds x (one common pretraining + 2 cores x 2 content modes x 2 budgets) = 108 jobs",
        common_capacity="identical trainable causal SDPA, encoder and readout; common checkpoint bound by exact SHA",
        capacity_limit="analytic and two_gate adapters have different total parameter counts; report them",
        content_contract=dict(copy="input-only causal selected/query prefix counts and ordinal addresses, common to all arms",
            mqar="four queried early key/value bindings; original input and counterfactual query/gold permutation",
            async_av="previously observed 48 CREMA-D clips, actor split 4/2/2, 24/12/12 clips; six emotions",
            binding="same-actor matched vs deranged AV pairs, balanced each modality, fixed 1.5s deadline and .1s clock",
            binding_controls=["audio-only", "video-only", "metadata-only", "full-payload"],
            frontend="fixed log-mel/DCT; common downstream encoder trained here, not a foundation encoder",
            timestamps="causal physical time; no full-duration normalized grid",
            observation_cost="window compression still consumes all original observations, no sensor saving claim"),
        selection=dict(rule="minimum validation CE, first tie, including initialization at step zero",
            step_zero="report donor_selected_step and donor_trained; zero cannot be called a trained content encoder",
            heldout="all test and diagnostics after selection; no post-test hyperparameter changes",
            development_data_seed=2026110099, formal_data_seed=2026110103),
        quality=dict(primary_content_contrast="analytic minus two_gate within same task/seed/mode/budget/condition",
            metrics=["query accuracy", "all-query exact sequence recall", "CE", "adapter-disabled difference"],
            synthetic_noninferiority_margin_accuracy=.01, synthetic_noninferiority_margin_ce=.02,
            critical_content_floor="99% exact recall on copy/MQAR ID; report 64/128-length OOD separately",
            uncertainty="seed/episode paired bootstrap, descriptive; AV only two heldout actors, no general significance claim",
            all_conditions="report every predeclared condition, not only positive strata"),
        economics=dict(budgets="256 optimizer updates and 20 CPU seconds are separate experiments",
            cpu_budget="loop includes scheduled validation, can overshoot by one batch/validation; report actual",
            complete_worker="imports, preparation, training, selection, inference and evidence serialization via wait4",
            shared_pretraining="bill once per task/seed; do not duplicate in the total study ledger",
            inference="prepared features to logits, whole-sequence batch1 validation profile and batch evaluation throughput",
            deployment_limits="no incremental cache benchmark, raw-media decoding, live sensor, network or device energy measurement",
            energy_joules=None, acceptance="quality noninferior and lower actual relevant execution cost required jointly"),
        architecture_limits=["shared attention retains its content-addressing and quadratic-length cost",
            "finite-grid regenerative adapter is not the global continuous He-Xiong closed-form solution",
            "content matrix isolates dynamics; it is separate from the mechanism core/controller 2x2",
            "old AV heldout cohort is not fresh external confirmation"])
    save(output / "plan.json", plan)
    print(json.dumps({"plan": str(output / "plan.json"), "jobs": len(jobs),
                      "sha256": hashlib.sha256((output / "plan.json").read_bytes()).hexdigest()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    make(args.root, args.python, args.output)
