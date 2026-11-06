# Two strict-as-of native matrix runs: exact policy reproducibility

**Research-only, independently byte-pinned comparison.** This checks whether
new diagnostic instrumentation changed model behavior. It does *not* establish
Cell learning, independently judged semantic citation quality, or production
readiness.

| Source | Workflow | Immutable ZIP SHA-256 | Manifest |
|---|---|---|---:|
| `675970bb610c70bb0ec30a2dee05c025440510e6` | [38114716982](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38114716982) | `1db7f8f7c13a1f718d5065956f14d554d3fe328c415fac4bb145d1eaf9d913c8` | 130 |
| `95a20c4287bd6e9ab3fefd95774a2d9c8212d73f` | [38116089672](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38116089672) | `a3322c5dec5f0d2a7453e90a97095e746e206a01c102749b458e3ed816573cc6` | 133 |

The second source additionally recorded a **label-free zero-offset null-choice
counterfactual** and corrected a later, post-policy answerable/abstention
*diagnostic* categorization. It did **not** recalibrate the original forced
top-1 selector or make additional policy Reader calls.

## Confirmed on the downloaded original bytes

- **576 of 576 matched original source choices and raw answer strings**.
  Original Reader input-token, output-token and request digests, delivered
  excerpts, model/prompt identities, selected pool/feature/Head identities
  and actual cache-reuse links are identical.
- **36 of 36** persisted Head checkpoint JSON artifacts are **byte-identical**.
- **3 of 3** LoRA Adapter `.safetensors` payloads are **byte-identical**.
- TRAIN omission/admission records, exact strict-as-of source-index receipts,
  30 Head pre/post fitting observations, candidate source coverage, no-evidence
  Reader report and original no-evidence/frozen paired report are unchanged.
- Both runs logged the same **44 actual main Reader calls** and **543 original
  policy-cache hits**. Wall-clock durations differ and must not be falsely
  treated as altered model predictions.
- The immutable LoRA journals differ only by elapsed times and the
  generating-commit-bound admission digest. Their actual prepared examples,
  tensor deltas and reload identities remain identical.
- At the native-development level, four learned arms changed **0/96**
  selected candidates relative to frozen; lineage LoRA changed **1/96**
  (checkpoint 48, retention), with **no correct support or answer gain**.
  Across all original policy outputs, citation markers = **0**.

### Original frozen source coverage remains the limiting factor

Among the **25/32** answerable, native-document-supported registered
evaluation questions: **8** had no labelled source window in the selected
candidate pool; of the 17 with one available, **4** were missed by the
frozen top-1. These are document-support labels, not independently reviewed
window entailment. The seven native-unanswerable questions remain separate.

At the original final TRAIN cut, **28** questions had positive and negative
candidate windows. Only **10 distinct pair-eligible questions** were
available to the lineage Adapter in its warm-start prefix. All 30 Head
TRAIN source top-1 change counts were zero despite measurable losses.

## Auditable code and CI

`scripts/memory_cell/stem_strict_repeatability.py` compares both archives
with the pre-existing, bounded `PinnedArchive` SHA-256/SHA256SUMS reader.
It rejects model, Reader prompt, source, task cohort, Head artifact, Adapter
tensor, selected source, original answer and generated-token drift, while
allowing only elapsed time and the explicitly labelled new null observation.
`test_stem_strict_repeatability.py` contains adversarial synthetic
tampering tests. The separate
`.github/workflows/hepta-memory-stem-repeatability.yml` fetches exact
private workflow artifact IDs `11693693993` and `11695042414`, checks
their independently pinned ZIP hashes and runs the **full original 576-row
comparison without any new model execution**.

The source-only local reproduction passed the actual two-ZIP comparison and
seven synthetic contract tests (one hosted-only integration test was skipped
locally). Its results are preliminary until this exact-source GitHub workflow
repeats the audit. The successful historical model runs themselves do not
qualify the current branch, prospective source families, semantic citation
precision, p95/end-to-end TCO or signed production admission.

**Disposition:** `production_accepted=false`; no main merge, no serving
cutover, no expansion of Cell count solely because 576 policy calls completed.
