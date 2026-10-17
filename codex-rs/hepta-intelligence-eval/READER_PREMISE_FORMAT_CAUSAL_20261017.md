# MemoryCell original Reader: publisher-premise and evidence-format diagnostic

**Status:** RESEARCH / SHADOW_ONLY / DENY_ALL. This additive study is based on
PR #2639, after the actual frozen MiniLM+small MemoryCell+SmolLM2 experiment.
It neither installs a MemoryCell nor substitutes a new source authority,
registered HF/BF16 model, production Reader, NDU/FBSDE solver or FinalUse.

## Why this experiment exists

PR #2639 observed 0/50 emitted evidence labels. Only four of ten fixed
questions had all publisher-annotated evidence in temporal/RRF Top-8, while
trained parametric Cell achieved zero of ten. The next counterfactual must
first distinguish missing selected evidence, fixed Reader capacity and
presentation effects **without silently replacing Reader weights**.

This is a *privileged source diagnostic*, NOT an eligible retrieval policy.
A trusted original-source preparer reopens the exact published LoCoMo JSON
(SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`),
uses **only** the publisher-annotated source IDs for the same ten questions
precommitted in the previous Reader study, and exports the bounded original
speaker/text excerpt. It **never exports publisher answer strings**, but the
source IDs are explicitly oracle-selected using annotations. Publisher sources
are neither independently authenticated nor certified semantically sufficient.
Each full-source trial includes the complete set of distinct publisher IDs;
this can include sources beyond the earlier 512-turn retrieval prefix.

## Fixed 4-arm causal design

| Arm | Reader evidence | Prompt format |
| --- | --- | --- |
| `annotated_json` | All distinct publisher-annotated sources | Same JSON system/user as the inherited original Reader |
| `removed_json` | Deterministically remove exactly one publisher source | Same JSON system/user |
| `annotated_lines` | Exactly the same complete source set | Explicit `[E1] source text` lines |
| `removed_lines` | Exactly the same premise ablation as removed JSON | Explicit source-label lines |

All 40 model attempts use the **same original immutable SmolLM2-135M FP32
weights**, system instruction, maximum 48 generated tokens and input-token
limit 2,048. Changed line format is a separately versioned diagnostic,
not an identity-preserving replay of the original production prompt.
Source excerpts are bounded to the same first 300 characters. For each
question, removal is SHA-256 over the frozen question/source IDs, never
chosen after seeing a prediction or answer. Remaining labels are rebound
canonically. Duplicated publisher IDs are deduplicated.

Original fixed ten-question sample contains **nine** cases with one distinct
annotated source (so removal leaves no evidence), and **one** case with two
distinct sources (so removal leaves one). A positive delta does not prove
multi-hop reasoning or independent necessity of the deleted source.

## Ownership and verification boundaries

- Job A: original-source admission and signed-by-nobody SHA receipts;
  prepares `plan.json`, `seal.json`. Only this job can see the publisher
  annotations. It also reexecutes the source-only frozen MiniLM/Cell rankings.
- Job B: different runner consumes **only** two plan files and eight
  registered original Reader weight files plus non-self-referential SHA256SUMS;
  it must not receive raw publisher `locomo.json` or answer labels. It freezes
  original answer text and token hashes before any review.
- Job C: different verifier recreates every planned source excerpt and its
  source-ID inclusion/ablation **from exact original bytes**, verifies all
  40 journal identities, then independently **reexecutes all 40 original
  Reader generations** and compares actual unmodified token-level results,
  excluding nondeterministic wall-clock timing. Only afterward does it score
  publisher answer strings. Self-computed SHA seals are not external signatures.
- All test, model and reference result sets retain the complete denominator.
  `failed` and `unavailable` never become successful answers. Source-ID
  citations are counted as emitted or not, and invalid label references are
  explicitly counted; **semantic citation entailment remains unassessed**.

This experiment must report `production_accepted=false`,
`statistical_superiority=false`, and HF/BF16 Reader parity unverified.
Do not make a “general memory”, actual FBSDE well-posedness, or distributed
emergence claim. Neither synthetic fixtures nor developer-visible LoCoMo
questions provide >=200 independently sourced prospective future families.

## Reproduce

With the original published LoCoMo, public source view, pinned source-only
parametric rankings, and eight-file registered original Reader transport:

```sh
export PYTHONPATH=scripts/memory_cell
python3 -m unittest discover -s scripts/memory_cell \
  -p 'test_reader_premise_format.py' -v
python3 scripts/memory_cell/reader_premise_format.py prepare \
  PUBLIC_ORIGINAL RANK_ORIGINAL ORIGINAL_LOCOMO NEW_PLAN
python3 scripts/memory_cell/reader_premise_format.py run \
  NEW_PLAN ORIGINAL_READER NEW_UNSCORED_READER
python3 scripts/memory_cell/reader_premise_format.py review \
  PUBLIC_ORIGINAL RANK_ORIGINAL ORIGINAL_LOCOMO NEW_PLAN \
  NEW_UNSCORED_READER ORIGINAL_READER NEW_POSTSEAL_REPORT
```

Every destination must not already exist. Never commit original source text,
benchmark answer labels, model weights, or generated original user content.

## Original 40-call local execution and independent replay, 2026-10-17

This is a **completed local original-weight execution**, not a hosted exact-HEAD
CI pass, independent human semantic evaluation, or future-family study. The
original plan SHA256 is
`d71f38bdc0667b465ed23fcfd3e7e057547e5ea48c18e3c27345ab4a15f6a5bc`.
All 40/40 original SmolLM2 model calls succeeded and generated unmodified
language; a separate process independently replayed **40/40** original token
generations against the exact original source plan. The original model answer
journal SHA256 is
`9d5644e3701d149c1b758555d86071d44d7b022b594b553dc740af133f426e9b`.
Review JSON SHA256:
`77f6993a97d803d87dce170c950a8e8422d9c3b6aa214bf789fc201e3310bdbf`.
Only sanitized diagnostics and original output identities are committed.

| Published source conditions | String token-F1 (8 scorable each) | Responses with [E] markers / 10 |
| --- | ---: | ---: |
| Full annotated, JSON | **0.168482** | 0 |
| One source removed, JSON | 0.079621 | 0 |
| Full annotated, explicit labeled lines | 0.147397 | 2 (both existing labels) |
| One source removed, explicit labeled lines | 0.069623 | 2 (**both invalid** labels) |

Paired full-minus-removed, JSON: **4 gain / 0 loss / 4 tie**,
mean token-F1 +0.088861. Labeled lines: **4 gain / 1 loss / 3 tie**,
mean +0.077775. Nine of ten original question evidence sets contain just one
distinct annotation; removal in those cases means zero sources. The final
case has two distinct references and removal keeps one. Thus the observed
difference is evidence-access sensitivity, **not** a general causal theorem
for multi-hop reasoning.

The line profile occasionally elicits a citation-looking token, but it also
elicits invalid labels when no corresponding source is delivered. Emission
or label-ID presence is **not** semantic entailment or citation correctness.
Source annotations are not independent sufficiency judgments. There is
no qualified Reader capacity claim, statistical superiority, automatic
Cell fission, NDU parameter change, or production promotion. Continue
with higher-capacity paired sufficient-evidence/removed-premise Readers and
independent semantic citation assessment before changing memory learning.
