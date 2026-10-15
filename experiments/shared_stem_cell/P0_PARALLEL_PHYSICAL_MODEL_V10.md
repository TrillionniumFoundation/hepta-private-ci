# P0 V10 — four independent original pretrained physical model attempts

**Status: research / Draft / DENY_ALL.** This is a CI *execution-topology* change
stacked on exact PR #2203 `d3f3f3c29f696851567e8f8ac3a5393597a48947`.
No `main`, model selector, Neuron, System 2/NDU, Q24, Worker, Artifact CAS,
Evidence WAL, FinalUse or physical tool-effect capability is changed.

## Failure we are actually addressing

Earlier P0 V9 still ran all four original pretrained candidates sequentially in
one expensive Runner. A broken checkpoint, incompatible package, OOM or timeout
could prevent later models from running and from yielding ANY original numerical
receipt, even when their sources were fine. V8 could preserve a partial receipt,
but V9 could not offer one Runner failure domain per checkpoint.

V10 replaces **only** that old serial stage with:

1. `physical-single-model` — exact four-item GitHub Actions matrix with
   `fail-fast: false`: Granite R2 97M, mmBERT-small, EmbeddingGemma 2 text,
   and frozen-native Laya421. Each gets its own isolated Runner, pinned source
   checkouts, pinned runtime, exact original immutable revision and candidate
   input, single original model program, create-only completion-or-failure
   receipt, and named artifact. There is **no** random/untrusted model fallback.
   No held human labels are downloaded. A failed setup stage is also retained
   as an explicitly unavailable model, not silently converted to success.
2. `physical-four-models` — a separate **fail-closed** collector. After all
   four independent Runner outcomes have been gathered, it validates a
   distinct `attempt-${model}.json` for each registered candidate and invokes
   the unchanged V8 independent *numerical* replay/identity check on every
   original report. It always writes an advisory nonauthorizing population
   status; then **exits nonzero** unless all four model slots are complete
   and their original artifacts survive the V8 checks.
3. The existing partial diagnosis still operates after failure, because the
   collector uploads its original result/failure artifacts even if the complete
   gate fails. Only `physical-four-models` success unlocks V5's separate
   original Head numeric replay, V6's cold source re-forward, V7's entire
   40-step original-label independent SGD refit and independent original
   human-label evaluation. The partial diagnostic is NEVER a replacement
   scientific success or model-selection owner.

## Original source/model/runtime locks

- Granite `835ad14087e140460703cf0fae09f97d469d65c2`;
  mmBERT `0eb3d056ec1d6333cf4e19b0966dfde342a41a3a`;
  EmbeddingGemma 2 `914f7f89142e33e77833254d9c9b90c3cef7303b`;
  Laya421 `c5d78730f3493e4fe16d61507ef4b78eef7318cf`.
- Original compact source `e05f939f65fb76f6bdbf7470eef7e63b77284dcd`,
  original Gemma source `f8d168a7689eb3624d97c44751791badd069e521`.
- Torch CPU 2.10.0; Transformers 5.19.0; pinned NumPy 2.2.6 and safe
  serializers. Original Laya Python wheel 0.3.20 and its typed `noul` mode.
- Source dataset is original fixed-revision human-annotated MultiRC; fit labels
  are allowed to train. Test labels are isolated to the **later** score-only
  process; naturally false candidates are not fabricated and no-evidence
  views have no new entailment labels.

V9 preflight now accepts a **single explicitly enumerated compact model** via
`--model`. It records exact coverage: a single valid Granite source cannot be
reported as having verified both compact snapshots. Parent combined mode
continues working for old original source tests.

## Physical accounting and negatives

Each isolated model records its own genuine download/preflight failure status,
input-to-prediction request costs, training workload and replay archive when
available. A failed model is *unavailable*, not an accuracy zero or a hidden
winner. The collector's V8 consistency check does **not** prove that the
producer genuinely loaded source checkpoint bytes; V6's independent cold model
reload is a separate later gate. Four per-model Runner records are still
software self-reports, not publisher signatures or physically independent
human adjudication.

A deterministic offline adversarial suite checks all-four original result
census, incomplete single-model and total failures, missing attempts, label
leakage, symlinks, switched model identity, forged authority, fake Laya Head,
source/Head tampering and required downstream dependencies. Real CPU PyTorch
training in these tests uses **synthetic** Q24-shaped features, not pretrained
Granite/mmBERT/Gemma/Laya. Hosted real model pass is NOT claimed until its
exact SHA run completes with full original artifacts and independent review.

## Required launch / scientific acceptance

A real physical hosted success must include four original candidate artifacts
and original model validation, V5/V6/V7 independent checks, unaltered human
labels, a cost-quality frontier on sufficiently independent source groups, and
all original required blocking CI/security/FinalUse checks. No real P0 semantic
superiority, 4096-Cell continual learning, P1–P5 qualification, or release is
proven by this workflow refactor.

**Always: `DENY_ALL`, `model_winner_selected=false`,
`production_promotion_permitted=false`; Draft / no `main` merge.**
