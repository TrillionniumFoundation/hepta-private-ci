# Balanced answering and citation-confidence qualification

This continuation starts at `72a5d87e1594e1329c58d956cb18f408b224fc8a`.
It does not activate a model, replace an independent reviewer, relabel old runs,
or claim new prospective observations. Existing signed learning.eval owners
remain the sole production admission boundary.

## Reader objective

`balanced_answer_learning.py` is opt-in. Each complete optimizer update has:
- 0.6 completion-only loss for a source-supported external TRAIN answer;
- 0.2 for a separately annotated unanswerable TRAIN question;
- 0.2 for the SAME supported question with all evidence removed;
- 0.1 softplus(1 + answer NLL - refusal NLL) on the supported context.

All completion likelihoods are length-normalized. Prompt tokens remain masked.
All four forward passes count against 65,536 input-training tokens; a partial
macro step is not executed. At most 64 optimizer updates occur. The preserved
legacy arm has at most 192 updates and the same input-token ceiling. Neither
identical step counts nor identical FLOPs are claimed. Weights/margin are a new
predeclared hypothesis, not an established optimal choice. Duplicate question
variants reject rather than increase training weight. Every row is admitted
before update, both semantic classes must exist, and training keeps ancestor roots.

`balanced_reader_trial.py` reconstructs previous candidate windows from original
pinned data and uses only the immutable native/token choices from generator
`71c6329b4bcf7febdfd6d97db1557f605ad1f0e1`. It does not relearn ranking, tune on
held-out labels, or call the old answers new generation. Each of three reader
states (disabled adapter, retrained legacy, new balanced) answers the same native,
token and empty evidence inputs. All 32 exposed development cases remain in all
nine arms: 288 planned fresh calls. All raw answers and unsigned citation requests
are synced before QA scoring. Test refusals are never filled in by the evaluator.
Adapters are saved and reloaded through the existing tensor/lineage contract.

Answerable and unanswerable results have separate denominators. A candidate whose
answerable F1 drops more than 2% relative to baseline fails the observed
nonregression screen even if total F1 rises through refusals. The fixed-horizon
family-based comparison reports uncertainty and missing pairs. This is diagnostic
QA, NOT an independent semantic judgement or production noninferiority proof.
No test result automatically selects a new serving adapter. Deployment fallback
remains unchanged. Every successful answer has an exact, unsigned citation queue
for the existing signing/adjudication path; missing independent actors stay missing.

## Signed citation owner

`memory_citation_gate.rs` retains its exact signed generator/evaluator/observer
separation, complete census, current trust/revocations, three snapshots, two real
window requirements and micro precision >=99%. An additional check coalesces the
ALREADY source/family-unioned audits: a group is good only if ALL of its emitted
citations are entailed. Repeated citations cannot offset one error in that group.

A fixed-horizon one-sided exact binomial test at p=0.99 and alpha=0.05 now applies
to these binary group outcomes. 200 perfect groups fail; 298 fail; 299 pass the
statistical component. Authentic signatures and 360/363 supported citation
occurrences are still insufficient when three source groups contain errors.
The policy tag is bound into the output gate digest so the strengthened proof is
not confused with an older point-estimate receipt. There are no new dependencies
or changes to the signed census wire bytes or authority posture.

The confidence target is **family-complete reliability**, not citation-count-
weighted micro precision. Source grouping alone does not prove independence,
exchangeability, truthful judgements, a fixed sampling horizon, or representative
production data. Those remain external qualifications of the existing owners.
Repeated CI, duplicated families and optional stopping do not create that evidence.
Tests use fixture keys and virtual time ONLY; they are not production observations.

## Validation

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_*.py' -v
just test -p codex-hepta-intelligence-eval --lib
just fix -p codex-hepta-intelligence-eval --lib
just fmt --check
```

`.github/workflows/hepta-memory-balanced-quality.yml` tests the actual owner,
retains formatter diagnostics, and runs a locked real-model reader experiment.
It has read-only repository permissions. Inspect each tested commit, model run,
raw record and final conclusion; a successful execution is not an effect claim.
