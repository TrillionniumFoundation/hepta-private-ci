# Research gate v2: development, selection and confirmation

This addition leaves every v1 result and failed acceptance rule intact. It is a
guard for the next experiment, not evidence of an improved model. The actual
registered objective remains the finite-horizon, undiscounted population
certainty equivalent `-log(E[exp(-2R)])/2`. It does not solve a general recursive
NDU driver, certify a global HJB optimum, or establish natural semantic quality.

## Before evaluation

`research_gate_v2.default_plan()` returns a development template. Its complete
plan, code identities and selected training settings must be published before
running the associated evaluation. `seal_plan` writes a canonical SHA-256 seal
once; changing a field after sealing is rejected. Publishing the seal is an
external repository action. A local digest does not prove chronology or prevent
someone from inspecting data outside the authorized runner.

The template uses seeds 17/29, widths 32/64, 32 sources and two draws per source
in the new `controller-v2-development` namespace. The unchanged source generator
uses `SHA256(joint-mechanism-v1:{namespace}:{source})`; a new namespace changes
the actual source-generating law's seed. Old train, development and test sources
retain their identities and historical roles. Renaming an existing source is not
a fresh observation. Candidate selection uses development evidence only.

The eight arms retain the old six and add `ordinary_dynamic_risk` and
`hepta_fixed_risk`. Four required comparisons hold the risk preference fixed
when testing dynamic allocation and operator structure:

| Question | Candidate | Control |
| --- | --- | --- |
| Risk preference | Hepta dynamic risk | Hepta dynamic mean |
| Dynamic allocation | Hepta dynamic risk | Hepta fixed risk |
| Operator structure | Hepta dynamic risk | Ordinary dynamic risk |
| Joint training | Hepta dynamic risk | Hepta dynamic risk actor-only |

Joint training still includes the declared supervised anchor and critic fitting;
this comparison cannot isolate a pure reward-gradient effect. Parameter counts,
physical compute and real emitted contents require their separate measured
records. Nonzero gradients alone do not pass any comparative gate.

## Paired statistics and complete costs

`analyse_panel(plan, rows, lifecycle_costs=None)` accepts actual compact trajectory
rows with the original `source`, `draw`, `net_with_audit_close`, `utility`,
`failure` and `profile_sha256`, plus `seed`, `width`, `arm` and
`source_namespace`. Every registered seed/width/source/draw/arm cell must occur
exactly once. Missing rows, duplicate rows, different profiles, NaN, unexpected
sources and optimistic failed-episode utilities are errors. Failures remain in
the denominator with their registered utility and measured cost.

Each bootstrap replicate independently resamples training-seed clusters and
source clusters. The same source weights apply across seeds, widths and arms;
the same seed weights apply across sources, widths and arms. Draws stay inside
their source/seed cell. This respects the crossed experiment and avoids treating
reused test sources as new independent replications. Each seed's population CE
is computed first, and the paired CE differences are averaged across seeds.
Training-seed randomness is an inference axis, not an extra random variable
inside the original entropic utility. This estimand is explicit in the plan.
Both ordinary intervals and
Bonferroni-adjusted intervals for all registered comparison/width pairs are
reported. These are approximate bootstrap intervals, not exact coverage bounds.
At least ten expected bootstrap samples per adjusted tail are required. Every
seed must also show the registered direction by default. Two or three training
seeds still give limited information about the population of trained models.

Development reports audit-inclusive serving CE and cannot set
`research_qualified=true`. Confirmation additionally requires an explicit
one-time cost ledger per seed/width/arm with all six fields: common training,
candidate training, candidate selection, distillation, process startup, and model
loading. Each field must use the same registered cost units as serving costs.
No double counting is permitted: phases are mutually exclusive. Zero is valid
only when a phase is genuinely absent, with the external measurement receipt
explaining it. Whole-process total cost must be reconciled with its phase ledger;
an unassigned residual remains a blocker, not an inferred zero.

The frozen deployment volume `N` is used as `R = utility - actual_serving_cost -
one_time_cost/N`. Training/evaluation batch cost cannot be relabeled as serving
cost or divided by whichever denominator yields a positive result. The engine
checks ledger completeness and arithmetic; it does not authenticate timing.
Independent trajectory/receipt audit remains necessary. Cross-host timing
uncertainty and uncertain deployment volume need separate sensitivity analysis.

A distilled candidate needs separate, predeclared comparisons for quality
noninferiority (`utility_ce`, threshold `-delta`), positive complete-cost benefit
(`net_ce`, threshold zero), and cost reduction (`cost_saving`, threshold zero).
No default `delta` is silently imposed. A confidence interval crossing zero is
not evidence of noninferiority. There is no post-hoc cost-only promotion rule.

The separately sealed `development_plan_distillation_v2.json` uses the teacher
and student labels `hepta_teacher` / `hepta_student`. Its development admission
criteria are utility CE noninferiority at -0.005, audit-inclusive net CE
noninferiority at -0.005, and positive serving-cost savings. The 0.005 margins
are this iteration's design decisions, not established field standards. All
three comparisons apply at both widths and both development seeds. Confirmation
keeps the utility margin but tightens net CE to positive **full-lifecycle**
benefit at the already fixed deployment volume of 10,000 episodes. Development
noninferiority by itself cannot establish that positive benefit.

## Confirmation access

`default_plan("confirmation")` proposes new training seeds 101/211/307 and
namespace `joint-confirmation-v2-20261030-v1`. It is a template until published
and sealed. Confirmation starts only after the development gate passes, selected
settings are frozen, all confirmation candidate hashes are available, and the
required measurement/provenance checks pass. It must keep the selected comparison
family and widths; a confirmation threshold may be stricter but cannot be relaxed.
New questions require a new independently registered study.

`claim_confirmation` checks both plan seals, binds the passing development report
and every candidate hash, and creates an exclusive marker **before any source is
generated or read**. A failure does not make consumed data fresh again. The
confirmation runner must enforce that its loaded model hashes match the receipt;
the helper does not itself execute a model. A resumed interrupted study may finish
its original fixed panel under an explicit checkpoint audit, but may not open a
second claim or change settings after seeing partial results.

Natural semantic qualification stays false in this module. That claim requires a
separate reliable observer, held-out original-media calibration, generated-output
calibration including degraded/counterfactual controls, and a frozen natural
source allocation. Passing a synthetic mechanism experiment never substitutes
for those gates. A failed development study is an admissible result and leaves
the reserved confirmation cohorts untouched.
