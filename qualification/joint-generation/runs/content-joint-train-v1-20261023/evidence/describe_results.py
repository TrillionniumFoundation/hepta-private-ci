"""Write a report from retained summaries only; no numerical model library."""

import hashlib
import json
from pathlib import Path
import resource


ROOT = Path(__file__).resolve().parents[3]
RUN = Path(__file__).resolve().parent.parent
build = json.loads((RUN / "build.json").read_text())
quality = json.loads((RUN / "quality-summary.json").read_text())
analysis = json.loads((RUN / "analysis.json").read_text())
audit = json.loads((RUN / "evidence/audit-result.json").read_text())
freeze = json.loads((ROOT / "content_joint/frozen-v1.json").read_text())
for section in ("sources", "inputs"):
    for path, expected in freeze["identity"][section].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
assert audit["exit_code"] == 0 and audit["all_final_caps_hold"]
families, seeds = ("S", "H", "A", "N"), (11, 23, 47)
operator = dict(scalar_ops=0, div_ops=0)


def mean(values):
    operator["scalar_ops"] += len(values)
    operator["div_ops"] += 1
    return sum(values) / len(values)


averages = {}
for family in families:
    averages[family] = {}
    for recipe, law in (("independent", "KEEP"), ("independent", "log2"), ("native", "native")):
        rows = [quality[family][f"{recipe}-{s}"][law] for s in seeds]
        means = {key: mean([row["means"][key] for row in rows])
                 for key in ("ce", "joint_success", "both_wrong", "wrong_agreement", "text_correct", "image_correct")}
        means["greedy"] = mean([row["greedy"]["joint_success"] for row in rows])
        averages[family][law] = means
repairs = {f: sum(row["repairs"] for name, row in audit["behavior"].items()
                  if name.startswith(f + "-") and name.endswith("-log2")) for f in families}
updates = {f: {recipe: [next(s["updates"] for s in build["slot_results"]
                     if s["family"] == f and s["recipe"] == recipe and s["seed"] == seed)
                     for seed in seeds] for recipe in ("independent", "native")} for f in families}
groups = [v for model in audit["parameter_displacement"].values()
          for v in model.values() if isinstance(v, dict) and "clock" in v]
all_real_movements = all(g["first_nonzero_entries"] > 0 and g["final_nonzero_entries"] > 0 for g in groups)
parity = max(quality[f][f"native-{seed}"]["native"]["max_sparse_full_error"] for f in families for seed in seeds)

body = ["# Native12 TRAIN portfolio: additive contrast positive, two primary hypotheses rejected\n",
"The single precommitted build exited0. The frozen saved-output analysis exited2: "
"coupling versus strong S/H log2 failed, native A−H passed its developmental mean "
"CE/joint criterion, native N−A failed. This is reused TRAIN evidence, not formal "
"confirmation, reversal of CORE/r2, dynamic superiority or a best-static whole-budget win.\n",
"Source971f36e54a4a → freeze15d77cacd63d → immutable raw results54c9706c3d35. "
"Fourteen hand checks passed first. All24 models, every reached checkpoint, "
"losses/gradients/actual displacements/moments/clocks, p/q/s/Q, source maps and "
"36 real service receipts are retained. No failed condition caused a rerun.\n",
"## Fixed primary outcomes\n",
"| Contrast, native unless stated | Mean CE change | Mean joint-success change | Result |",
"|---|---:|---:|---|",
]
for title, value in (("S native − S independent log2", analysis["coupling"]["S"]["log2"]),
                     ("H native − H independent log2", analysis["coupling"]["H"]["log2"]),
                     ("A−H", analysis["native_A_minus_H"]), ("N−A", analysis["native_N_minus_A"]),
                     ("A−strong pure CE S (explicit comparison)", analysis["native_A_minus_S"])):
    body.append(f"| {title} | {value['means']['ce']:+.10f} | {value['means']['joint_success']:+.10f} | "
                + ("positive TRAIN means" if value["positive_mean_CE_and_joint"] else "rejected") + " |")
body += ["", "| Seed | Native A−H CE | A−H joint | Native N−A CE | N−A joint |",
         "|---|---:|---:|---:|---:|"]
for seed in seeds:
    ah, na = analysis["native_A_minus_H"]["per_seed"][str(seed)], analysis["native_N_minus_A"]["per_seed"][str(seed)]
    body.append(f"| {seed} | {ah['ce']:+.10f} | {ah['joint_success']:+.10f} | {na['ce']:+.10f} | {na['joint_success']:+.10f} |")
body += ["", "Native A−H and A−S CE/joint changes are positive in all three seeds. "
         "For A−H, mean both-wrong and wrong-agreement each decrease by.001974286802; "
         "both head correctness rates increase by the same amount. Greedy mean improves "
         "by.000434027778, one row in2304 seed/request observations. This supports a "
         "bounded training effect within this fixed joint architecture and resource recipe; "
         "independent-source benefit remains unconfirmed. N−A is mixed by seed and negative "
         "on both primary means. Do not substitute its positive seed47.\n",
         "## All architectures and visible error cases\n",
         "| Family/law | CE | Joint success | Both wrong | Wrong agreement |",
         "|---|---:|---:|---:|---:|"]
for f in families:
    for law in ("KEEP", "log2", "native"):
        row = averages[f][law]
        body.append(f"| {f}/{law} | {row['ce']:.9f} | {row['joint_success']:.9f} | {row['both_wrong']:.9f} | {row['wrong_agreement']:.9f} |")
body += ["", "| Family/native | Text correct | Image correct | Greedy joint |",
         "|---|---:|---:|---:|"]
for f in families:
    row = averages[f]["native"]
    body.append(f"| {f} | {row['text_correct']:.9f} | {row['image_correct']:.9f} | {row['greedy']:.9f} |")
body += ["", "Native has zero one-correct/disagreement mass because every output is "
         "one semantic code; consistency alone says nothing about correctness. "
         "Both-wrong is still higher than the corresponding independent log2 in every "
         "family mean. Even A native has lower CE than A independent log2 despite slightly "
         "higher joint success. Every marginal, both one-correct cases, wrong disagreement, "
         "pixel MSE and greedy array is preserved in quality-summary/quality NPZ.\n",
         "All native families improve over the identical zero-update conditional law; "
         "A's mean gains are CE+.024965682213 and joint+.016197788645. Zero controls "
         "separate real training from changing the law at initialization. Native A remains "
         "below historical strong S/H/A log2 CE and below the new independent N log2. "
         "Those are retained historical/same-portfolio references, not a free model portfolio.\n",
         "## Actual updates and causal limits\n",
         "| Family | Independent updates11/23/47 | Native updates11/23/47 |",
         "|---|---|---|"]
for f in families:
    body.append(f"| {f} | {' / '.join(map(str, updates[f]['independent']))} | {' / '.join(map(str, updates[f]['native']))} |")
body += ["", f"All24 model clocks match real updates. All{len(groups)} active parameter "
         f"groups have nonzero first and final actual displacement: {all_real_movements}. "
         "The saved PNG/state audit verifies this without another model forward. "
         "Decoder parameters remained exact and decoder moments were never advanced.\n",
         "All slots stopped on the frozen CPU preflight. Checkpoint costs were inside "
         "the slot allowance: a due1/128/256/512 checkpoint requires.10 remaining CPU "
         "seconds. This creates visible255/511 stopping cliffs, including A independent23 "
         "at255 and most native slots at511; H native23 reaches613. No checkpoint/guard "
         "was removed after seeing scores. These update counts, changed objectives and "
         "checkpoint/trace costs prevent assigning a failure to head capacity or a single "
         "optimizer mechanism. The saved fixed fit/inner curves are in evidence/audit-result, "
         "separated by partition and including every reached checkpoint. Mini-batch first/last "
         "losses refer to different batches and are not matched learning curves.\n",
         "## Full budgets and real service\n",
         "The same10-CPU-second/12B cap applies to each full six-model family. "
         "Common CPU=4.495378557: inherited bases2.075925876 + both preflights.982089705 "
         "+ actual new common1.437362976. The2-second/500M tail reserve leaves.584103574 "
         "CPU seconds and1.297706064B per training slot. No unexecuted allowance is padded. "
         "Final allocation includes active work, common scheduler and .203826386 seconds "
         "of outer administration/saved-output analysis; that analysis adds2,982 actual "
         "priced summary units.\n",
         f"The native four-group compiler alone cost{build['new_native_compile']['CPU']:.9f} "
         "CPU seconds (a subset of preflight). The inherited independent compiler cost "
         f"{build['inherited_old_independent_compile_CPU']:.9f}, a subset of old preparation. "
         "Per-slot architecture-specific binding/initialization CPU/units are retained in "
         "candidate.json. Both are paid here because every family contains both recipes. "
         "A future independent-only deployable system must not inherit unused native costs.\n",
         "The separately frozen saved-output audit adds.930167 CPU seconds and19,195,498 "
         "units to EACH SAME family. It verifies all2304 actual PNGs/captions against "
         "decoded semantics, source/label/probability/action records, and all24 model states. "
         "No new model/decoder forward, sampling draw, model image render, service repeat "
         "or retiming occurred. Original build/analysis arrays and gates are unchanged.\n",
         "| Family | Complete CPU, including final descriptive receipt work | Complete units |",
         "|---|---:|---:|"]

# Only administrative descriptive arithmetic remains; bill this whole process.
usage = resource.getrusage(resource.RUSAGE_SELF)
description_CPU = usage.ru_utime + usage.ru_stime
description_units = operator["scalar_ops"] + 4 * operator["div_ops"]
costs = {f: dict(CPU=row["CPU"] + description_CPU, units=row["units"] + description_units)
         for f, row in audit["combined_complete_costs"].items()}
for f in families:
    body.append(f"| {f} | {costs[f]['CPU']:.9f} | {costs[f]['units']:,} |")
body += ["", "All final caps hold: " + str(all(x["CPU"] <= 10 and x["units"] <= 12_000_000_000 for x in costs.values())) + ". "
         "The final lossless descriptor write follows its CPU snapshot, as explicitly labeled. "
         "The new source/result Git publication and prose editing are research archival work, "
         "not a claim that all historical R&D consumed the same resource budget. Old e7de "
         "ledgers are untouched.\n",
         "There are exactly576 new actual requests per family (9 calls),2304 total. "
         "The separately paid inherited64 calibration requests and nine hand-test PNGs "
         "are not added to this service-test denominator. Log2 real repairs by family: "
         + ", ".join(f"{f}={repairs[f]}" for f in families) + ". "
         "All actual sampled outcomes, including errors, are in the PNG audit; they do "
         "not replace exact-law primary expectations.\n",
         "Per-call timers now include input/guard/ledger setup through inference, sampling, "
         "PNG/JSON and full probability/source receipt export. They stop before Python "
         "return and parent ledger aggregation, whose CPU is in complete family totals but "
         "not separately timed per profile. They are trace-heavy batched observations, "
         "not a complete production latency/net-CE comparison. No e7de component timing "
         "was promoted or rerun.\n",
         f"Maximum final native sparse/full-Q metric discrepancy={parity:.17g}. "
         "Exact requestwise joint CE, the original scorer/rho and declared greedy contracts "
         "are retained. TRAIN positivity here does not authorize formal opening or close "
         "the parent training/NDU/dynamic research goals.\n",
         "Review build.json, analysis.json, the outer .execution.json, source-map.json, "
         "quality-summary.json, every model directory and evidence/audit-result.json.\n"]
(ROOT / "content_joint/TRAIN_RESULTS.md").write_text("\n".join(body) + "\n")
final = dict(scope="original complete build + frozen saved-output audit + this retained-summary report",
             saved_description_CPU_before_receipt=description_CPU,
             saved_description_operators=operator, saved_description_units=description_units,
             complete_costs=costs, all_final_caps_hold=all(x["CPU"] <= 10 and x["units"] <= 12_000_000_000 for x in costs.values()),
             source_input_freeze_still_matches=True, model_work_in_this_description=0,
             original_build_analysis_and_gates_unchanged=True,
             original_immutable_raw_commit="54c9706c3d3582c305d06119eb8baf1c70efa04a")
(RUN / "evidence/final-costs.json").write_text(json.dumps(final, indent=2, sort_keys=True) + "\n")
print(json.dumps(dict(costs=costs, repairs=repairs, active_groups=len(groups),
                     real_parameter_movement=all_real_movements, parity=parity), indent=2))
