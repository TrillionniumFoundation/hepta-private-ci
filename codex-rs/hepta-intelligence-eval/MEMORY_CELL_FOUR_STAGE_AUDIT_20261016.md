# MemoryCell four-stage execution audit — October 16, 2026

**Status: original historical evidence audited; NO-GO for new memory learning or
production.** This distinguishes actual prior model work, a new reproducible
receipt-consistency audit, prospective controls and work NOT performed.
No model was trained or queried by this patch.

## Actual empirical controls (not synthetic model results)

The auditor pins four existing JSON research receipts by exact Git blob identity.
Original generating artifacts and their separate verifiers remain authoritative;
an aggregate audit is not raw tensor/answer replay or independent semantic review.

1. **Reader ability.** Previously executed Qwen2.5-3B (8 authored questions)
   recorded strict success of empty 0/8, hybrid 3/8, entity_time 8/8,
   organized 8/8, author-specified program_support 8/8 and critical-premise
   lesion 4/8. SmolLM2-1.7B, with its different tokenizer and weights,
   recorded 0/8, 1/8, 2/8, 3/8, 3/8, 2/8 respectively. This is a Reader
   capacity comparison, not memory learning. Program support is authored
   Oracle evidence, not independently confirmed sufficiency. A lesion
   success can be prior guessing. Actual prompt-token costs differ.
2. **Nonparametric organization.** An actually completed Qwen 3B experiment
   comprised 40 calibration and 72 evaluation generations. On the 8 previously
   exposed development tasks, hybrid_k4 3/8, calibrated k=1 5/8,
   complete entity/time path 8/8 and correction-aware organized 8/8.
   Organized adds ZERO successes and ZERO complete citations over entity/time
   while using 573 fewer prompt tokens (5,179 vs 5,752). Both have 4/8
   complete declared citation chains; these are not human entailment judgments.
   A separate deterministic symbolic source-local Reader obtained hybrid 8/8
   and organized 8/8, zero paired task wins. Its 48 reads are NOT neural
   inference or actual multi-repository coding work.
3. **Parameter study.** Five learned read heads in TWO original
   576-logical-attempt studies had zero held-out development source-selection
   wins and zero answer changes per head. Repeated logical attempts are not
   576 independent families. The result cannot be used to claim an actual
   new experience-knowledge compression model was trained or tested.
4. **Lifetime.** No authenticated independent family cohort, two real future
   calendar windows, human-semantic 99% citation entailment, production
   cross-host revocation/restore or full workload-matched TCO was established.
   Missing measurements remain null; all promotion flags remain false.

## Prospective preregistration and experimental fairness

The executable prospective_guard checks a separately fixed task plan and the
complete attempted arm ledger. It demands **12 exact paired conditions**:
base and stronger reference Reader each on no-evidence, retrieved, sufficient,
and lesioned evidence; identical base Reader with organized evidence, learned
read policy, organized evidence PLUS parameter knowledge module, and a
knowledge-module-only control without original text.

A strong Hybrid baseline retains the SAME tools as learning candidates,
including program execution. All conditions share prompt-template identity,
task/candidate population, model token ceilings and tool authorization;
only the reference Reader may have different base weights. Organized and
knowledge-module conditions must receive identical evidence digests.
Predeclared source/snapshot freeze must occur BEFORE unseen task revelation.
One frozen execution manifest pins both Readers, prompt template, tools and
budgets for the ENTIRE source-family cohort. Learned read strategy compares
against exactly the same organized evidence, not a secretly altered retrieval.
Policy and knowledge model digests are separately bound for every task;
knowledge-only and knowledge-plus-evidence must use the identical frozen model.
Base and reference Readers must receive byte-identical evidence per regime.
The prompt digest binds the template, NOT the evidence-varying rendered prompt.
Every failed call remains in the planned denominator. Real categories include
new facts, corrected facts, cross-experience composition and executable
program tasks. Independent source-family, label-blinding and near-duplicate
reviews remain mandatory but are NOT issued by this script.

Prospective controls intentionally cannot authenticate caller-reported model
outputs, actual test-execution receipts, outside reviewers or chronology from
a local JSON file. Synthetic fixtures test rejection only, and positive toy
scores are never production evidence. A human-reviewed sufficient-context
set, a genuinely independent future cohort and a trusted task verifier
must be obtained separately before an admission claim.

## Complete amortized cost: unknown is NOT zero

For common currency, equipment, retention horizon and workload, account for:

    C_total(N) = C_extraction + C_index + C_train
               + C_source_storage + C_artifact_storage
               + C_maintenance_fixed
               + N * (C_query + C_maintenance_per_query)
               + C_revocation + C_recovery.

The executable total_cost includes all ten components, and reports a
complete cost only when none are missing. The optional break_even calculation
is conditional on equal quality/hardware/tools and fully measured costs;
it does not establish observed monetary, time or energy savings.
Retained original source bytes and snapshot/recovery copies do not vanish
when a knowledge module becomes small.

## Run

    python3 -m unittest discover -s scripts/memory_cell -p 'test_four_stage_evidence.py' -v
    python3 scripts/memory_cell/four_stage_evidence.py --output /tmp/memory-four-stage-disposition.json

The four input JSON Git blob identities are verified before aggregation.
The dedicated read-only workflow records exact HEAD and input SHA-256s.
No original model answers or private source material are committed.
No required blocking-ci, Architecture, DecisionCell or HNMF ownership is
bypassed; neither main nor production state is modified.

**Go/no-go:** first obtain independently reviewed sufficient evidence and an
unseen Reader cohort; then same-reader strong Hybrid versus organized RAG;
then pre-task frozen parameter contrasts against the best organized baseline;
only finally verify repeated-use economics, revocation, retention and qualified
production recovery. This commit itself advances only the reproducible
historical negative diagnosis and enforceable experimental controls.
