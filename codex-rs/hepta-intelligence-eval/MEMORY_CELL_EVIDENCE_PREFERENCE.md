# Reference-anchored evidence preference

This opt-in development continuation builds on the inherited balanced reader and
signed citation-confidence owner. It does not select a production adapter, waive
any qualification gate, issue an independent judgement, or alter historical output.

## New training hypothesis

`evidence_preference.py` compares the SAME supported question in its original
admitted context and with that context removed. Each has both its external TRAIN
answer completion and a refusal completion. The four detached reference NLLs
come from the same frozen reader with adapters disabled. Actor support odds should
increase relative to that reference; empty-context answer odds should decrease.
A separate context-gap term discourages a context-insensitive prior change.

The preregistered coefficients are beta 2, relative-preference weight 0.5,
context-gap weight 0.25 and margin 1. Completion-only SFT weights are 0.8 for the
supported answer, 0.1 for paired empty refusal, and 0.1 for a separately annotated
unanswerable example. These are hypotheses, not validated optimum settings.
Mean completion NLL is used; this is not an exact sequence-probability DPO claim.

All samples use the existing external training cut and source bindings. Unknown
windows do not become negatives. Same-question duplicates cannot increase family
weight. Up to 64 complete optimizer updates and 131,072 input tokens are allowed.
All five actor forwards and every uncached reference forward count. The frozen
reference cache is keyed by exact prompt/target token identity. Incomplete macro
steps are not executed; failures quarantine the candidate. Both actor and reference
consume sources whose lineage must remain current. Reference work is not free.

## Matched execution

`balanced_reader_trial.py --candidate preference` runs base, legacy and preference
readers on the unchanged native-selected, token-selected and empty contexts:
32 original public development questions, nine arms, 288 planned NEW generations.
The default balanced candidate remains available. Schema v2 records each exact
objective and its budget. No local weights, refusal threshold or serving adapter
are selected using the final test scores. Learned adapters are saved/reset/reloaded
through the existing immutable artifact contract before evaluation.

The old legacy control retains its original 192-step / 65,536-token budget. The
reference-inclusive candidate ceiling is larger and actual costs are reported;
this experiment cannot establish an equal-compute objective-only improvement.
Ranking, question identities, candidates, base, prompt and decoder remain fixed.
Changing the candidate objective does not change those model inputs.

The report separates answerable/nonanswerable denominators, trained-vs-base answer
scores, and SAME-reader evidence-vs-empty effects. These last effects are diagnostic,
not semantic certification; mere response changes do not prove evidence usefulness.
Failures invalidate the observed nonregression screen and widen paired uncertainty.
An authentic signature cannot compensate for missing/poor task or citation quality.

## Validation and limits

The inherited public cases have been exposed before this work. They are not new
prospective windows, independent production observations, or a complete new native
benchmark run. Exact source and pretrained/data inventories are retained by the
read-only `hepta-memory-evidence-preference.yml` workflow, including failed runs.
The full Python regression suite is separate from the actual model process.

The existing Rust citation gate still requires signed complete inputs, current
trust/revocations, independent snapshots/windows and its source-group confidence
floor. This development module cannot issue that evidence or install an adapter.
An independent human or authorized reviewer still needs to adjudicate actual
claims against actually delivered sources. No >=99% semantic result is presumed.
