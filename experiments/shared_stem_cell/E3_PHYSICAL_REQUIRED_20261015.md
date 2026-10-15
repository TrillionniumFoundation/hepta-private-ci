# E3 original-weight ScienceQA: require physical source-to-score completion

**Status: DRAFT / SHADOW_ONLY / DENY_ALL / NO STEM SELECTION.** This is an
additive child of the frozen #2123 E3 experiment, not a production merge.
It changes the research workflow and adds an independent stdlib evidence
checker and fault tests. It does not change original model weights, Cell
interfaces, Head optimizer, Q24 journal, Worker, CNS, NDU, Artifact CAS,
FinalUse or the deployed Stem.

## Evidence defect actually observed

At original exact source b8b2f10fe38506972301e77e3836729a90200673,
Actions **run 38672948060 / job 116220031059** reported SUCCESS for a
pull_request event and passed **27/27** original synthetic mechanism tests.
However, the original workflow condition for push-only execution skipped
**all three physical phases** on that PR run:

1. Original ScienceQA image/source acquisition and held-label staging.
2. Original Granite97 and DINOv2 weight acquisition, forward, fit and sealed
   predictions.
3. Independent held-label numeric scoring.

The successful PR artifact had only environment/source/test metadata; logs
reported absent prediction seal, staged source and scorer files. Consequently
that *particular green run is not proof of an actual pretrained-model outcome*.
It does not prove that no separate push run ever executed; each distinct run
requires its own exact-SHA artifacts.

## Enforced in this child

- The original ScienceQA physical study stages now execute in both same-repo
  PR qualification and the explicit research-branch push workflow.
  Fork-origin PRs do not get this costly job. Successful synthetic tests alone
  can no longer complete the study.
- A separate stdlib-only checker (e3_physical_ci_gate.py) requires actual
  source-seal, immutable prediction SHA, expected original model identities,
  positive source/vision batch counters, **80** Head optimizer updates,
  a 96/32/64 split, all eight paired heldout arms, original score/label seals
  and exact-same-image-masked text predictions.
- The checker rejects self-asserted production authorization, fake external
  label ownership, fake visual-necessity adjudication, nonfinite probabilities,
  duplicate JSON keys, changed original revisions and false Head budgets.
  It writes a new, create-only, nonauthorizing success witness **only after**
  the full scorer completes; a failure still uploads whatever sanitized
  diagnostics exist.
- Both normal and Python -O stdlib **20/20 synthetic/fault tests** passed
  in the isolated local editing environment. These tests include no actual
  pretrained model weights, heldout accuracy or external labels. The pushed
  script/test Git blobs must independently match the locally tested bytes.
- The newest hosted workflow, source-head and blocking-ci must be checked
  afresh. A pending, skipped, cancelled or failed physical job is never
  reported as a model pass.

## Evidence hierarchy

1. Contract tests PASS: schema/code behavior, **not** pretrained execution.
2. Physical research job PASS with complete witness and archived Score:
   original model forward/fit/readout *claimed by its executing workflow*
   and source/byte/count consistency checked. Still no independent publisher
   signer, natural visual-necessity labels or prospective evidence.
3. Independent source/publisher/label-host attestations, matched native
   EmbeddingGemma 2 or 421M baseline, genuine three future windows,
   negative transfer, full model load/energy/RSS/latency costs and original
   signed Worker/FinalUse/CAS/WAL/restart evidence: **not obtained**.
4. Production selection/admission: **DENY_ALL** until independently granted.

## Local use

Run the stdlib unit checks:

~~~sh
PYTHONPATH=experiments/shared_stem_cell python3 -m unittest discover \
  -s experiments/shared_stem_cell -p test_e3_physical_ci_gate.py -v
PYTHONPATH=experiments/shared_stem_cell python3 -O -m unittest discover \
  -s experiments/shared_stem_cell -p test_e3_physical_ci_gate.py -q
~~~

For complete original-model execution use the research workflow
.github/workflows/hepta-e3-granite-dino-scienceqa.yml on the new branch.
Check its **physical required** job and the archive
physical-completed-or-absent.json (present only after full success).
Neither a source-only artifact nor a source digest authenticates model
execution on an independent host.

## Next causal experiment once real E3 scores exist

Classify each source by genuine visual necessity with independent human
review, and compare on the *same images/questions* and heldout groups:
text-only, OCR-to-text, unaligned vision, learned shared Bridge and pinned
native EmbeddingGemma 2, with label-blind predictions and matched
complete cost envelopes. Historical ScienceQA TEST is retrospective and
not a future time window. Do not select any winning Stem from this E3 step.
