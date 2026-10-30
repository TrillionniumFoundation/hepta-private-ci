"""Build a descriptive report from frozen v4 evidence; never select checkpoints."""
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent


def percent(value):return f"{100*value:.2f}"


def main():
    result=json.loads((HERE/"results.json").read_text())
    challenge=json.loads((HERE/"challenge_results.json").read_text())
    audit=json.loads((HERE/"audit_results.json").read_text())
    stress=json.loads((HERE/"stress_solve_results.json").read_text())
    validation=json.loads((HERE/"validation.json").read_text())
    frozen=json.loads((HERE/"freeze.json").read_text())
    resources=json.loads((HERE/"resource_accounting.json").read_text())
    independent=json.loads((HERE/"independent_audit.json").read_text())
    if not result["complete"] or not challenge["complete"]:raise RuntimeError("Incomplete experiment")
    if independent["replay_pending"]:raise RuntimeError("Independent long-sequence/challenge replay still pending")
    p=result["metadata"]["protocol"]
    primary=[g for g in result["summary"] if g["kind"]==p["primary_model"] and g["task"] in p["primary_acceptance"]]
    target_pass=all(g["all_observed_seed_lengths_meet_target"] and g["all_five_seeds_complete"] for g in primary)
    lines=["# HCSN v4 regularized associative memory: measured results", "",
        f"The frozen {len(result['runs'])}-run confirmation matrix is complete. The combined FullHX every-seed/every-length acceptance gate {'passed' if target_pass else 'failed'}. Retrieval passed at all five seeds and all three test lengths. Memory seed 2 at L128 reached 93.84765625%, below the declared 95% minimum. This result is limited to the declared synthetic sequence family and budget.","",
        "## What changed and why", "",
        "The previous eight-slot memory suffered learned address collisions. v4 replaces it with learned bounded key/value projections, normalized Gram/cross-value statistics, a C1 generic write gate, and a final-query ridge solve. FullHX, toy HCSN, sigmoid and a memory-only control share this memory mechanism. Any benefit shared by these controls cannot be attributed uniquely to the financial operator.","",
        "The detailed recurrence, exact-arithmetic state/SPD proof, positive-time-gap assumptions and finite-precision limitations are in DESIGN.md. The fixed ridge is 0.01 and key dimension is 16; neither was changed after test construction.","",
        "## Development and confirmation separation", "",
        "Development used base 2690000 and one initialization. Its four fullHX/memory-only memory/retrieval runs used only train/validation and all reached 100% validation accuracy. The initial lazy-table JAX tracer error and source are preserved. Loading the table outside tracing fixed that implementation issue; no architectural changes followed the validation scores.","",
        f"Sources and prospective protocols were frozen at {frozen['frozen_at_utc']}. Confirmation used base 2700000, five seeds, 2048 training sequences at each of lengths 8/16/32, 600 Adam updates, batch 32 and learning rate 0.003. Every model used exactly 19200 sampled training examples. Checkpoints were selected by validation loss alone. Held-out sets have 1024 examples each.","",
        "The primary criteria are memory ≥95% and retrieval ≥90% for **every seed at every length 32/64/128**. Challenge base 2800000 was also declared before confirmation. It provides new 512-token, eight-association and noisy-filler data; challenge scores do not change checkpoint selection.","",
        "## Held-out accuracy", "",
        "Entries are mean ± sample standard deviation across five seeds, in percent. These comparisons match data, optimizer updates and approximately 6200 trainable parameters; they do not match state capacity, operations or hardware cost.",""]
    for task in p["tasks"]:
        lines += [f"### {task}","","| Model | L32 | L64 | L128 | Worst seed/length | Target in every seed/length |",
                  "|---|---:|---:|---:|---:|---|"]
        for group in result["summary"]:
            if group["task"]!=task:continue
            scores=group["metrics"]
            cells=[f"{percent(scores[f'test_{length}']['mean'])} ± {percent(scores[f'test_{length}']['seed_sd'])}" for length in p["heldout_lengths"]]
            worst=min(scores[f"test_{length}"]["min"] for length in p["heldout_lengths"])
            accepted=group["all_observed_seed_lengths_meet_target"]
            criterion="Not declared" if accepted is None else ("Pass" if accepted else "Fail")
            lines.append(f"| {group['kind']} | "+" | ".join(cells)+f" | {percent(worst)} | {criterion} |")
        lines.append("")
    lines += ["### Noisy and missing irregular input", "",
        "The corruption split uses noise 0.35 and missingness 0.5 at length 32. Its labels are computed from the available underlying observed events by the shared generator; this is a synthetic robustness test.","",
        "| Model | Accuracy, mean ± seed SD | Worst seed |","|---|---:|---:|"]
    for group in result["summary"]:
        if group["task"]!="irregular":continue
        score=group["metrics"]["corrupt_32"]
        lines.append(f"| {group['kind']} | {percent(score['mean'])} ± {percent(score['seed_sd'])} | {percent(score['min'])} |")
    lines += ["","## Extrapolation and capacity challenges","",
        "These checkpoints were neither retrained nor reselected. No post hoc challenge pass threshold is imposed.","",
        "| Challenge | Model | Accuracy, mean ± seed SD | Worst seed |","|---|---|---:|---:|"]
    for group in challenge["summary"]:
        lines.append(f"| {group['challenge']} | {group['kind']} | {percent(group['mean'])} ± {percent(group['seed_sd'])} | {percent(group['min'])} |")
    lines += ["","## Operator-specific evidence","",
        "The following are paired FullHX minus control accuracy differences at L128, in percentage points. The approximate t intervals use five paired seeds, are descriptive and are not corrected for multiple comparisons. They do not establish universal equivalence or superiority.","",
        "| Task | Control | Mean difference | Approximate 95% interval |","|---|---|---:|---:|"]
    differences=[]
    for task in p["tasks"]:
        full={r["seed"]:r for r in result["runs"] if r["task"]==task and r["kind"]=="full_hx"}
        for kind in ("hcsn","sigmoid","ridge_memory_only"):
            controls={r["seed"]:r for r in result["runs"] if r["task"]==task and r["kind"]==kind}
            delta=np.array([full[s]["metrics"]["test_128"]["accuracy"]-controls[s]["metrics"]["test_128"]["accuracy"] for s in p["training_seeds"]])
            mean=float(delta.mean());half=float(2.776445105*delta.std(ddof=1)/np.sqrt(len(delta)))
            lines.append(f"| {task} | {kind} | {100*mean:+.3f} | [{100*(mean-half):+.3f}, {100*(mean+half):+.3f}] |")
            differences.append(dict(task=task,control=kind,mean=mean,ci95=[mean-half,mean+half],paired_values=delta.tolist()))
    lines += ["","The FullHX-versus-sigmoid irregular-L128 contrast is a limited positive signal: +0.859 percentage points with a nominal 95% interval [+0.022, +1.697]. It uses five paired seeds, has no multiple-comparison adjustment, and changes both the risk and Call shapes. It cannot isolate a Put-specific effect. FullHX's 81.660% mean is also below the GRU's 84.766% in this condition.","",
        "A ceiling score shared with ridge-memory-only is evidence that this memory mechanism solves the tested task, not evidence that the financial Call/risk shape is necessary. FullHX versus toy/sigmoid changes activation shapes under a shared dynamic graph; memory-only also reallocates the parameter budget and therefore is not an identical-width single-factor removal.","",
        "The memory-only prefix statistics commute under token/time-gap permutations with a fixed final query. They cannot represent every order-sensitive exponential-filter target in the irregular task. Adding temporal state can therefore matter substantially; the similar toy/sigmoid results and the GRU control are needed to distinguish this effect from a financial-shape effect.","",
        "## Resource accounting","",
        "Times are medians across runs of each run's measured median. Optimizer execution excludes AOT compilation, validation and discarded warmup updates (there are zero such updates). Inference is logits only, batch 32 at length 32. These are shared-CPU measurements, not an energy benchmark, GPU kernel comparison or quality-cost scaling curve.","",
        "| Model | Trainable parameters | Logical persistent state scalars/sequence | Fixed operator KiB | Optimizer update ms | Logits inference ms |",
        "|---|---:|---:|---:|---:|---:|"]
    for kind in p["models"]:
        rows=[r for r in result["runs"] if r["kind"]==kind]
        state=rows[0]["persistent_state_scalars"]
        state="Sequence dependent" if state is None else str(state)
        update=float(np.median([r["timing"]["optimizer_update_median_ms"] for r in rows]))
        infer=float(np.median([r["latency_test32_batch32"]["median_ms"] for r in rows]))
        runtime_bytes=resources["runtime_fp32_array_bytes"] if kind=="full_hx" else 0
        lines.append(f"| {kind} | {rows[0]['parameter_count']} | {state} | {runtime_bytes/1024:.2f} | {update:.4f} | {infer:.4f} |")
    lines += ["","The frozen results field `fixed_operator_bytes` is mislabeled: it records 262256 bytes of source float64 table arrays. The actual JAX runtime casts every table leaf to float32 and needs 131128 bytes (128.05 KiB). Raw results and runner remain unchanged. `resource_accounting.json` records the correction and per-array evidence; the table above uses runtime FP32 bytes.","",
        "The ridge state is much larger than a same-parameter GRU state. It performs outer products at every prefix token and a dense solve at the final query. Streaming state does not grow with sequence length, while training activations and repeated autoregressive queries add costs. The financial table is fixed and shared across units; it is not trainable capacity, but it is real storage.","",
        "## Numerical verification and independent replay","",
        f"State/gradient validation passed: {validation['passed']}. The separately declared zero/rank-one solve finite-difference stress passed: {stress['passed']}. Independent replay of all {audit['expected_runs']} test32 checkpoints, data fingerprints, selection histories and budgets passed: {audit['passed']}.","",
        "The solve stress preserved two FP32 finite-difference failures at step 2e-5: normalized errors 0.003610 and 0.004519 exceeded the declared 0.003 tolerance. FP64 checks passed and FP32 linear-system residuals were at most 4.71e-8. An independent NumPy float64 closed-form adjoint comparison then found maximum normalized FP32 gradient error 2.536e-6 (below its declared 2e-5 threshold). The complete difference-step sweep reduced errors to at most 2.15e-4 at step 2e-3 and reproduced the failures at 2e-5. This evidence supports small-step cancellation rather than an autodiff error, while the original failed test remains failed in its raw record.","",
        "The independent audit also verified that changing only the last query leaves Gram, cross-value and inverse-mass statistics bitwise unchanged, while fast/slow neuron states and logits may respond. Dataset hashes and exact input-overlap checks found no reuse of the confirmation/challenge datasets from v3 or development, and no evaluation input duplicates in any v3/development/v4 training set.","",
        f"The separate-agent replay of {len(independent['replay']['confirmation_checks'])} test64/test128 evaluations and {len(independent['replay']['challenge_checks'])} challenge evaluations passed: {independent['replay']['passed']}. It uses independently implemented metric calculations and recomputes the per-seed acceptance failures. Passing an integrity replay does not turn a failed task target into a pass.","",
        "| Precision | Online-statistic error versus independent weighted sum | Exact closed-write retention | Maximum tested gradient absolute error |","|---|---:|---|---:|"]
    for row in validation["statistics"]:
        err=max(g["maximum_gradient_absolute_error"] for g in validation["gradients"] if g["dtype"]==row["dtype"])
        lines.append(f"| {row['dtype']} | {row['weighted_sum_max_error']:.3e} | {row['exact_closed_retention']} | {err:.3e} |")
    lines += ["","The stress sequence contains 4096 updates. The dynamic stress multiplies random inputs by one million and positive time gaps by 100. Bounds are for recurrent state, not a proof of stable gradients at arbitrary length or arbitrary floating-point magnitude. The solve diagnostic includes rank-one statistics near the declared condition bound of 101.","",
        "## Remaining scope limits","",
        "This experiment meets the declared associative-retrieval criterion under its fixed conditions. The FullHX memory-retention criterion remains unmet, so the combined prerequisite for scaling is not satisfied. The results do not establish a novel optimal neuron model, biological spiking equivalence, a unique cross-task benefit from financial operators, improved energy consumption, a large-language-model scaling law, or readiness for language/multimodal backbone pretraining. The normalized statistics can dilute old rare events and finite key dimension still limits independent associations. Broader capacities, learned financial parameters, mixed precision beyond FP32, fused kernels and quality-cost scaling remain separate research questions.","",
        "## Evidence files","",
        "- `freeze.json`, `protocol.json`, `challenge_protocol.json`: prospective sources and evaluation conditions.",
        "- `development_results.json`, `development_failures/`: all development successes and the implementation failure.",
        "- `validation.json`, `stress_solve_results.json`: stated numerical standards and raw checks.",
        "- `resource_accounting.json`: source-float64 versus runtime-FP32 table memory correction; original raw fields retained.",
        "- `results.json`, `checkpoints/`: complete confirmation matrix, histories, source/data/checkpoint hashes and measured timings.",
        "- `challenge_results.json`: duration, capacity and noisy-input evidence with frozen checkpoints.",
        "- `audit_results.json`: independent replay and budget checks.",
        "- `independent_audit.json`, `INDEPENDENT_AUDIT.md`: separate-agent mathematical, adjoint, data-isolation, resource and checkpoint review.",
        "- `summary.json`: machine-readable acceptance and paired comparisons.",""]
    (HERE/"REPORT.md").write_text("\n".join(lines))
    payload=dict(primary_every_seed_length_targets_passed=target_pass,complete_runs=len(result["runs"]),
        challenge_runs=len(challenge["runs"]),validation_passed=validation["passed"],
        solve_stress_passed=stress["passed"],audit_passed=audit["passed"],
        independent_static_passed=independent["static_passed"],
        independent_long_and_challenge_replay_passed=independent["replay"]["passed"],
        paired_differences_l128=differences,
        scientific_operator_advantage_established=False,full_backbone_readiness_established=False)
    (HERE/"summary.json").write_text(json.dumps(payload,indent=2)+"\n")
    print(json.dumps(payload,indent=2))


if __name__=="__main__":main()
