"""Render the sealed experiment and its failures without selecting outcomes."""
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE / name).read_text())


def main():
    result, summary = read("results.json"), read("summary.json")
    audit, validation = read("audit.json"), read("validation.json")
    ledger, diagnosis = read("cost_ledger.json"), read("diagnosis.json")
    numerical = read("replay_diagnosis.json")
    if not result["complete"]:
        raise RuntimeError("Refuse an incomplete matrix report")
    rows, protocol = result["runs"], result["protocol"]
    replay_failures = [c for c in audit["checks"] if not c["passed"] or not c["labels_exact"]]
    failed_variants = sorted({next(r["variant"] for r in rows if r["run_id"] == c["run_id"]) for c in replay_failures})
    by = {(s["task"], s["variant"], s["split"]): s for s in summary["summaries"]}
    lines = [
        "# Frozen bounded-delta memory results",
        "",
        f"Thirty fresh actual training runs are complete. The new mechanism quality gate **{'passes' if summary['quality_gate']['passed'] else 'fails'}**; "
        f"**{summary['positive_shape_gates']}/8** prespecified function-family superiority gates pass.",
        "",
        f"The aggregate strict replay gate is **{'PASS' if audit['passed'] else 'FAIL'}**: "
        f"{len(replay_failures)} of {len(audit['checks'])} conditions fail, confined to {', '.join(failed_variants) or 'none'}. "
        "This failure is retained without changing the frozen numerical tolerance.",
        "",
        "The new candidate is a bounded residual-write memory inside the inherited learned key/value, content, boundary and fast/slow graph. "
        "Its deterministic orthogonal-filler and overwrite checks test a useful local mechanism; they do not imply learned long-sequence success. "
        "No frozen scientific source, seed, optimizer, selection rule or gate was changed after outcomes to improve these results.",
        "",
        "## Protocol and retained evidence",
        "",
        "The source baseline is `b1934022821f3fdafd509b43cf0c4d7d45852e6e`. "
        f"The scientific freeze is `{result['freeze_sha256']}`. "
        "All five arms have 6,217 learned parameters and identical initial parameter bytes within each task/seed. "
        "Seeds 61, 73 and 89 use the new data base 91,000,000, independently from earlier experiments. "
        "Each arm receives 600 Adam updates at batch32 and learning rate 0.003 on the same 8/16/32 curriculum. "
        "Each training length has 2,048 examples; validation and each evaluation condition have 512. "
        "Minimum validation32 cross entropy selects one of 12 candidates, never test or challenge scores.",
        "",
        "All 360 candidate checkpoints, 30 selected checkpoints, 18,000 update records and 135 prediction/label archives are retained under `runs/`. "
        "The published lossless `raw_evidence.zip` and per-file SHA256 manifest restore that directory with `restore_evidence.py`; "
        "an actual new-directory restore and full hash validation passed before publication. "
        "The matrix has 576,000 training-example presentations; this is a tiny synthetic-task experiment, not all-modal model pretraining. "
        "`freshness.json` reports exact-input disjointness from the enumerated earlier constructed evaluation cohorts and current validation-length training. "
        "The old conditional confirmation cohort was not instantiated.",
        "",
        "The original mass-ridge negative result and its unexecuted confirmation remain untouched. "
        "This experiment uses fresh paired fixed/mass baselines; those are not replacements for old reported outcomes.",
        "",
        "## Main accuracy results",
        "",
        "Values are means across the three fixed seeds, in percent. Per-seed values and dispersion are in `summary.json` and `results.json`.",
        "",
        "| Arm | Memory128 | Memory512 | Retrieval128 | Retrieval512 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for variant in protocol["variants"]:
        values = [100 * by[task, variant, split]["mean"]
                  for task, split in (("memory", "test128"), ("memory", "test512"),
                                      ("retrieval", "test128"), ("retrieval", "test512"))]
        lines.append(f"| {variant} | " + " | ".join(f"{x:.2f}" for x in values) + " |")
    lines += ["", "The original conjunctive quality gate is evaluated without relaxation:", "",
              "| Frozen check | Result |", "| --- | --- |"]
    for name, passed in summary["quality_gate"]["checks"].items():
        lines.append(f"| {name} | {'PASS' if passed else 'FAIL'} |")
    lines += ["", "## Capacity, overwrite and interference challenges", "",
              "These use retrieval-trained checkpoints. None of these altered task conditions was a training target. "
              "The challenge reports do not replace the main gate. Capacity uses eight associations at length512; "
              "overwrite uses a later conflicting write to the queried key and labels the newest value at length128; "
              "interference increases filler noise from 0.05 to 0.2 at length128.", "",
              "| Arm | Eight associations512 | Latest-write128 | Noisy filler128 |",
              "| --- | ---: | ---: | ---: |"]
    for variant in protocol["variants"]:
        values = [100 * by["retrieval", variant, split]["mean"]
                  for split in ("capacity8_512", "overwrite128", "interference128")]
        lines.append(f"| {variant} | " + " | ".join(f"{x:.2f}" for x in values) + " |")
    lines += ["", "The overwrite gain is a concrete challenge-specific benefit of the tested residual-write mechanism. "
              "The same gain also appears with the ordinary function controls, while long-memory, capacity and noisy-filler behavior deteriorate. "
              "It neither establishes a uniquely financial advantage nor passes the overall quality gate."]
    lines += ["", "## Fixed function-family comparison", "",
              "The three delta arms use identical state size, parameter tree, initialization, data and training opportunity. "
              "All use the same learned boundary coordinate. They are **not slope matched**: the risk derivative at zero "
              "is 0 for FullHX and ordinary C1, and 0.5 for sigmoid(2z). The financial nine-parameter template remains fixed; "
              "FullHX risk is the already documented C1 first-hit reinterpretation, not the original debt Put.", "",
              "Intervals are the prespecified familywise Bonferroni95 paired-seed t intervals over eight comparisons (three seeds, df2). "
              "Their nominal coverage assumes approximately normal seed-level paired differences; three seeds give weak distributional evidence. "
              "A positive gate requires a lower interval bound above 0 and a mean gain of at least 1 percentage point. "
              "Wide intervals and negative gates do not establish equivalence. Zero-width intervals reflect identical observed paired scores "
              "in these three seeds, not a known zero population difference.", "",
              "| Task/length | FullHX minus control | Mean difference pp | Family interval pp | Gate |",
              "| --- | --- | ---: | ---: | --- |"]
    for c in summary["shape_contrasts"]:
        lo, hi = np.array(c["bonferroni95_interval"]) * 100
        lines.append(f"| {c['task']}/{c['split']} | {c['control']} | {100*c['mean_difference']:.2f} | [{lo:.2f}, {hi:.2f}] | {'PASS' if c['passed'] else 'FAIL'} |")
    det = validation["deterministic"]
    lines += ["", "## Mechanism and replay checks", "",
              f"All {len(validation['checks'])} local numerical/derivative checks passed before training. "
              f"Maximum directional error was {max(c.get('directional_error', 0) for c in validation['checks']):.3g}. "
              f"The orthogonal target read stayed exactly {det['orthogonal_before']:.12f} through 4,096 filler writes; "
              f"same-key overwrite error was {det['overwrite_error']:.6g}. "
              "Zero-write invariance is for reachable states inside the radius8 balls. Projection keeps each column bounded "
              "and is nonexpansive for fixed key/value/write; it is not globally C1 and does not guarantee gradients through learned keys.", "",
              "The deliberate negative probes remain: correlated writes alter the old query, and overcomplete capacity degrades. "
              f"The 24/32 random-key RMSEs were {det['capacity'][-2]['rmse']:.4f}/{det['capacity'][-1]['rmse']:.4f}. "
              "Orthogonal preservation only holds while projection is inactive; an active column projection can alter that read.", "",
              f"Independent NumPy replay covered all {len(audit['checks'])} selected-checkpoint evaluation conditions. "
              f"Audit status: **{'PASS' if audit['passed'] else 'FAIL'}**. "
              f"Maximum absolute logit difference was {max(c['logit_error'] for c in audit['checks']):.3g}; "
              f"maximum metric difference was {max(c['maximum_metric_error'] for c in audit['checks']):.3g}. "
              f"All {sum(c['accuracy_exact'] and c['labels_exact'] for c in audit['checks'])} accuracies and label arrays match exactly. "
              f"The failed conditions are {', '.join(failed_variants) or 'none'}; "
              "the stricter absolute-logit tolerance still applies even when the aggregate metrics agree. "
              "The audit also gates finite update/candidate/auxiliary values, actual parameter updates, the measured delta radius invariant, "
              "all 12 candidates, fixed step logs, validation-only selection, paired initialization and saved hashes. "
              "NumPy recurrence code is independent; financial table and dataset definitions are shared.", "",
              "An additional independent, explicitly post hoc diagnosis examined only the worst exposed mass-ridge case: "
              f"`{numerical['run_id']}/{numerical['split']}`, example {numerical['selection']['example']}, output {numerical['selection']['output']}. "
              "The saved JAX FP32 logits reproduced bit for bit. The Gram/cross-statistic differences were "
              f"{numerical['worst_example']['state_differences']['gram']['maximum_absolute']:.3g}/"
              f"{numerical['worst_example']['state_differences']['cross']['maximum_absolute']:.3g}; "
              f"the ridge coefficient was {numerical['worst_example']['ridge_jax']:.3g} and condition number "
              f"{numerical['worst_example']['jax_solve']['condition_2']:.1f}. "
              "On identical matrices, JAX, NumPy and an 80-digit Decimal solve agreed to "
              f"{numerical['worst_example']['jax_decimal80_same_input_fitted_error']:.3g}. "
              "Promoting the same saved-weight recurrence to FP64 reduced independent JAX/NumPy batch logit disagreement to "
              f"{numerical['high_precision']['jax_numpy_logit_maximum_batch']:.3g}. "
              "This supports accumulated FP32 recurrence differences amplified by the small regularizer for this case. "
              "It does not replace any saved prediction, explain every failed case, or turn the failed frozen gate into a pass. "
              "See `replay_diagnosis.py` and `replay_diagnosis.json` for the perturbation identity and residual evidence.", "",
              "## Costs and state", "",
              "| Arm | Persistent state scalars/example | Logical fixed table bytes | Mean completed-run CPU s | Median warm batch32 logits ms |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for variant in protocol["variants"]:
        group = [r for r in rows if r["variant"] == variant]
        res = group[0]["resources"]
        lines.append(f"| {variant} | {res['persistent_state_scalars']} | {res['shared_fixed_operator_bytes']} | "
                     f"{np.mean([r['run_cpu_seconds'] for r in group]):.2f} | {np.median([r['latency']['median_ms'] for r in group]):.3f} |")
    lines += ["", "State scalar counts are not total memory bytes; parameters, optimizer, transient activations and dtype differences also matter. "
              "Table bytes count each arm's operator dependency; the inherited module eagerly loads a shared table even for C1, "
              "so the logical zero is not a measured process-residency saving. "
              "The delta arm avoids the old final Gram solve. Warm logits timings are for batch32, length32, shared CPU; "
              "they exclude compilation/metrics, have no exclusive-machine or GPU/energy interpretation, and are not Transformer/SNN comparisons.", "",
              f"The sum of completed-run scopes is {ledger['measured_completed_run_cpu_seconds']:.2f} CPU seconds and "
              f"{ledger['measured_completed_run_wall_seconds']:.2f} wall seconds. "
              f"Independent replay adds {ledger['additional_numpy_audit_cpu_seconds']:.2f} CPU seconds; "
              f"exploratory diagnosis adds {ledger['additional_exploratory_diagnosis_cpu_seconds']:.2f}. "
              f"Lossless archiving and an actual new-directory restore/check add {ledger['additional_archive_and_restore_cpu_seconds']:.2f} CPU seconds. "
              f"Independent diagnosis of the worst mass-ridge replay case adds {ledger['additional_independent_numerical_diagnosis_cpu_seconds']:.2f} CPU seconds. "
              f"The measured CPU lower bound is {ledger['measured_cpu_lower_bound_seconds']:.2f} seconds. "
              f"The measured nonoverlapping wall lower bound, including initial validation and completed admission waits, is "
              f"{ledger['measured_nonoverlapping_wall_lower_bound_seconds']:.2f} seconds. "
              "The potentially parallel diagnostic tail uses the larger branch wall duration, rather than adding overlapping intervals. "
              "Pretraining validation CPU, data/freshness/startup, summary/rendering/reporting repair and interrupted admission wait are unmeasured, explicitly null in `cost_ledger.json`. "
              "These figures must not be labeled full campaign cost. Compilation/optimizer/validation are nested within the completed-run scope and not added twice.", "",
              "Shared cgroup pressure required the documented cache-aware operational admission amendment after one completed run. "
              "The interrupted process was waiting between runs, not updating a model; completed runs were not repeated. "
              "Scientific source hashes stayed fixed. `operational_handoff.json` records the brief overlap of the old waiting process and the new continuation.", "",
              "## Exploratory diagnosis and scope", "",
              "`diagnostic_plan.json` was written after early results were seen, so this is explicitly post hoc. "
              "`diagnosis.json` examines the first 64 test512 examples per run for filler-write activity and learned key overlap. "
              "Markers are used only to classify diagnostic tokens, never for model routing. The exposure proxy is not an exact error bound "
              "or a proof of a unique cause, and it did not alter models, selection, data or gates.", "",
              "This package establishes a tested new memory recurrence, retained finite-capacity/interference limits and a reproducible small-task comparison. "
              "It does not establish a general trainable financial free boundary, exact continuous-time flow, all-modal encoder superiority, "
              "a replacement for Transformer/SNN backbones, or event-hardware energy savings. The new negative gates remain evidence for the next design decision.", ""]
    (HERE / "RESULTS.md").write_text("\n".join(lines))
    print(HERE / "RESULTS.md")


if __name__ == "__main__":
    main()
