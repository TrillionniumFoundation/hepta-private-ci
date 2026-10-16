# HDCF shadow qualification: Stem economics, graph consistency and trained Cells

**Status: RESEARCH_ONLY / DENY_ALL / NO MODEL SELECTION / NO CODE EXECUTION.**

This standalone Python standard-library experiment changes no live Neuron,
NDU, CellSplit, CAS, CNS, TaskFlow, FinalUse, Agentd, GPU or OS effect owner.
It is a *separate* research layer, not a second runtime or production solver.

## Scope

1. `hdcf_gates.py`: weight-only shared-vs-replicated Stem accounting, and
   numeric forward/backward interface, terminal and budget checks in a finite
   topologically ordered reasoning graph. These checks are **not** a global
   stochastic FBSDE theorem, an NDU proof or a performance comparison.
2. `physical_bank.py`: actual CPU float64 SGD for two Cell-type-specific Heads
   under the same physical **2*(dimension+1)** parameter inventory.
   Frozen, equal-step shared-dense, equal-step/equal-touch shared-one-touch,
   split, and wrong-type-routing controls are predeclared. Shared and split
   use the same initial weights, training example ordering and update count.
   Per-arm actual CPU/wall nanoseconds and estimated parameter touches are
   recorded separately. **SGD steps do not imply equal FLOPs, tensor RAM,
   training power or full lifecycle cost.**
3. `physical_cli.py`: two-process training/review entrypoints. Training
   requires `fit` target labels, and rejects *any* target field in held rows.
   The review process alone reads blind held targets; exact case IDs,
   families, Cell types and prediction census must match. No model weights,
   source text, secret or privileged executable is written to research outputs.

## Reproduce standard-library regressions

```sh
cd qualification/hdcf-research
python3 -m py_compile hdcf_gates.py physical_bank.py physical_cli.py test_*.py
python3 -m unittest -v test_hdcf_gates test_physical_bank test_physical_cli
python3 -O -m unittest -v test_hdcf_gates test_physical_bank test_physical_cli
```

## Physical original-input protocol

Construct an original bounded `hepta.hdcf.frozen-feature-bank.v1` JSON file:

- `producer`: asserted SHA-256 identities for Encoder, preprocessing and
  original source; generation and principal. This is NOT a trusted signature.
- `types`: exactly two declared Cell categories; `dimension`: 1–256.
- `fit`: 8–2048 rows, each with unique `id`, `family`, declared `type`,
  finite float vector and binary `target`; each Cell type contains both labels.
- `held`: 4–1024 rows with unique `id`, `family`, `type` and finite vector,
  **without target**. Family identities must not intersect training families.
- Independently hold a second `hepta.hdcf.blind-targets.v1` JSON file with
  the same bundle digest and exactly all held `id/family/type/target` rows.

Run producer and reviewer as **different OS processes**, using distinct inputs:

```sh
python3 physical_cli.py train --features frozen-features.json --out trial.json
python3 physical_cli.py review --predictions trial.json --targets held-private.json --out review.json
```

Both inputs reject symbolic links and ambiguous JSON keys; outputs are
create-only regular files with 0600 permissions and fsync. This is not a
sandbox, cryptographic source custody or a durable production transaction.

## What the included synthetic fixture demonstrates—and does not

`test_physical_bank.original()` creates a **deliberately conflicting linear
classification problem**. Equal-parameter Cell-type-specialized linear Heads
are mathematically suited to that fixture. The observed local 32-case review
was **frozen 16/32, shared dense 16/32, shared one-touch 16/32, split 32/32,
wrong-type route 0/32**, under 256 actual training steps per trained arm.
This is deterministic CPU scalar mechanics and a useful negative routing
control, **not** genuine pretrained Encoder features, native Transformer
forwards, general semantic reasoning, independent out-of-family human task
results, future windows or statistically generalizable superiority.

To qualify a real Stem, export features from a physically executed and
immutable approved pretrained Encoder, preserve real source/publisher and
case family IDs, isolate held labels in a different owner, and compare
same-source, same-Reader complete task outcomes with authentic cost receipts.
See original public Encoder research PR #1825 and follow-up provenance
boundary #2462. Full Encoder work, training, reading, evaluation, cache reuse,
optimizer state, resident memory and rollback must all enter real TCO.

## Hard nonclaims and future owners

No automatic Cell Split; no System2 reasoning efficacy; no general FBSDE
existence/uniqueness; no 10T equivalence; no multiple-modal generator; no
native executable memory, GPU launch, OS UI action, FinalUse or effect grant.
Never treat a `True` field, task score, model hash or graph continuity result
as independently signed source truth or task authorization. Unverified
source provenance stays `false`; production and external effect authority
always stay `false`.

The authoritative repository boundaries are `docs/DEVELOPMENT.md`,
`docs/learning/NDU_FBSDE_SPEC.md`, `docs/cns/TECHNICAL.md` and
`docs/hnmf/TECHNICAL.md`. Subsequent real deployments belong inside
existing owners, not this research folder.
