# MemoryCell: three completed strict-as-of model runs (October 13, 2026)

Status: **historical, research-only, not production acceptance**. This document
reconciles independently stored, successful CPU-run artifacts, not newly executed
model calls. No 99% citation accuracy or superior learned Reader behavior is claimed.

## Immutable inputs

| Original Actions run | Generating source commit | ZIP SHA-256 | Manifest files |
|---|---|---|---:|
| 38114107704 | 434581a0e2475341253c74dcfa7c609dd8fd6492 | a45c4b397b573662715a45f80bfc118446e41f6ceedf88052188bbfd9d131ca5 | 127 |
| 38114504922 | d2c2f97568b6e6d075011cb52acbef9f659837bc | 2728ff0f9ef7eef01cf8a3d8ee99dc16600265ffd7ac5a4740baebe46d874ec5 | 130 |
| 38114716982 | 675970bb610c70bb0ec30a2dee05c025440510e6 | 1db7f8f7c13a1f718d5065956f14d554d3fe328c415fac4bb145d1eaf9d913c8 | 130 |

All three artifacts passed external SHA-256 verification and every internal
manifest member. The predeclared 80 questions, six arms, frozen source/Reader
policy, selected candidate pools and actual Reader contract match.

## What the original 1,728 model-policy records actually show

- **576/576 successful policies in each of three runs**, with exactly matching
  raw answer bytes, selected source indices, delivered original excerpts, prompt
  and Reader identities, and real input/output token digests. This is answer
  repeatability, not 1,728 independent Reader calls.
- The main Reader session logged **44 real calls** (including privileged,
  post-policy oracle diagnostics) and **543 exact request-cache hits** in each
  run; a second isolated copy executed **32 real no-evidence controls**.
  Cache reuse and privileged oracles must not be counted as fresh policy calls.
- The first two runs had identical cached feature seals and 36 Head artifact
  bytes. The third run's source feature seals changed on **576/576 records**;
  some learned Head state bytes changed, with the largest absolute saved tensor
  difference **7.62939453125e-6**. Frozen input/output answer bytes remained
  identical. **Do not claim bit-for-bit numerical model reproducibility.**
- Final admitted TRAIN cut: **40/48**, with a genuine positive/negative source
  pair in **28/48**; earlier cut pair counts were **10/16** and **17/32**.
  Across all Head arms/checkpoints, the within-TRAIN evidence **top-1 never
  changed**, despite some weak cross-entropy reductions.
- At the final checkpoint the General Cell's matched SGD loss rose, while
  Temporal's fell, giving a slight positive combined final loss delta for
  linear/gated/LoRA Heads. This is *not* a consistent model improvement.
- On the same actual test/transfer cohort, the completed post-policy bridge
  showed **zero net labelled native-source gain** for every learned arm.
  One retained old-task selection can change without satisfying unseen-task
  improvement.
- Under the fixed retrieval candidate budget, **2 of 6 test questions with
  resolved native supporting sources missed those sources entirely**. Another
  one had support in the pool but the frozen top-1 missed it. Better Head
  learning cannot recover support that was never retrieved.
- None of the original 576-policy models emitted a structural `[E...]` citation.
  Independent semantic citation precision is therefore **undefined**, never
  automatically 100% or 99%.

## Reproducible controls

`scripts/memory_cell/stem_strict_three_success.py` is a bounded, read-only
artifact verifier. It fails closed on external ZIP digest or internal SHA256SUMS
drift, missing/duplicate policy attempts, Reader model/prompt/token differences,
candidate-pool changes, and any unsupported production qualification.

`.github/workflows/hepta-memory-stem-three-success-audit.yml` downloads all
three original artifacts using the repository's own GitHub Actions token, runs
nine receipt-tampering regressions, produces a new SHA256-pinned comparison
report, and retains exact tested source/logs. No Encoder/Head/Reader is loaded.

The persisted outputs are **development evidence**, not blinded future-calendar
evaluation, independent sufficient-source adjudication, production SLA/TCO, or
permission to merge or switch production. **`production_accepted=false`**.

## Causal next experiment

Prefer a frozen-model, budget-matched retrieval contrast that can actually add
missing legitimate source documents to the candidate set *without reading
held-out answer labels during selection*. Compare improved retrieval,
top-1 source decision, answer quality, and citation support separately.
Do not increase the number of Cells or claim learned superiority merely
because SGD parameters changed or a cached Reader answered successfully.
