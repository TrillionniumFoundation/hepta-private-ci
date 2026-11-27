# Real BANKING77 Encoder evidence vs. 32D Q24 Cell research — admission boundary

**Status:** READ-ONLY RESEARCH / DRAFT / `DENY_ALL`; no selected model, no
source rewriting, no `main` merge, and no NDU/Final-use/CNS effect.

## Two original hosted physical research records

1. [Public pretrained Encoder / Cell bank Actions run 38523539731](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38523539731),
   [PR #1825](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1825),
   artifact `11877613315`, original ZIP SHA-256
   `fd89f174057d98bd2d4f03447d5d5dd9372723e70128ccdf2dcbe73f67a0a03a`.
   The pinned source is PolyAI BANKING77 `57ec275d8078af65b7731c2a98be812d844a6d6b`,
   CC-BY-4.0, four intents only; 64 fit and 32 heldout public text cases.
   Frozen ModernBERT checkpoint / tokenizer revision is in the original archive;
   actual complete Encoder was executed and accounted only once across both
   Cell-bank arms (shared Encoder record SHA-256
   `596dc30ec273f2043c9780c1484b7640b69a7e95f0264afb90030220b331b216`).

2. [Q24 actual trained Adapter/Head hosted run 38888708544](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38888708544),
   [PR #2426](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2426),
   artifact `12042181896`, original ZIP SHA-256
   `fc74e1720fc104ccbd573808c1ed9c6714a3a15b486410351065021dbe82b0ed`.
   Its input is a **synthetic 32D Q24 sequence**, *not* real BANKING77.
   Eight 2K/8K private-parameter candidate weights and eight 8KiB/32KiB
   serialized-byte candidate weights are distinct. Each arm was physically
   trained and invoked twice in a fresh Rust process, 32 total native process
   receipts; independent Python Q24 Adapter/Head integer parity only.

## Original public heldout descriptive results (NOT Q24)

| Public Cell-bank arm | Before accuracy | After accuracy | Heldout n | Model |
| --- | ---: | ---: | ---: | --- |
| Dense 16 cells | 0.25000 | 0.71875 | 32 | Shared ModernBERT + 16-cell bank |
| Sparse Top-2 of 16 cells | 0.28125 | 0.53125 | 32 | Same shared ModernBERT + 16-cell bank |

The archived physical `bank.safetensors`, execution JSON, prediction JSON
and commit seal SHA match for both arms; their 32 heldout prediction IDs match
the preregistered test ID set, disjoint from the 64 fit IDs. Training was 64
steps per arm, but CPU time/FLOPs are **not** matched, observer independently
verified labels are not present in this ZIP, and production efficacy is not
established. This is one small real-data canary, not a decisive quality ranking.

## Executable independent bridge

`real_public_q24_evidence_bridge.py` reopens *both original ZIP byte streams*,
pins their outer SHA-256 and complete member sets, checks source/license/
selected-case/Encoder/terminal/model-weight/prediction/execution SHA, and
separately rechecks the Q24 synthetic fixture, model identities, producer/
consumer SHA and 32 native process/eight-event-per-candidate receipts.

For an operator with the two archived ZIPs:

```sh
python qualification/neuron-gated-sparse-v3/real_public_q24_evidence_bridge.py \
  --public-zip /path/to/original-public-artifact.zip \
  --q24-zip /path/to/original-synthetic-q24-artifact.zip \
  --output /path/to/new-create-once-evidence-join.json
```

The script always returns `NO_CROSS_STUDY_MODEL_SELECTION`, never a winner.
The unit regression suite uses synthetic protocol data. Its full actual-hosted
ZIP replay is opt-in with `HEPTA_PUBLIC_BANK_ARCHIVE` and
`HEPTA_BYTE_Q24_ARCHIVE`, and **must not** be cited as a hosted execution
unless the exact files were provided and the test actually ran.

## The production research path that remains necessary

The public Encoder's genuine token/pooled 768D features were **not archived
as signed, frozen 32D Q24 feature vectors**, so no real-data input can be
claimed for the new Cell-native Q24 models. A bridge must first produce an
immutable *genuine* public feature snapshot with independently attested
Encoder/tokenizer/projection code identity and training-only fitted
projection. It must bind public source case IDs, labels, group/time split,
fit versus heldout, no-change original V1 and exact pretrained weights.

Then physically train the four native Q24 Cell candidates and native V1 on
the identical permitted train split and compare original heldout plus genuinely
later labeled future windows, negative transfer, cost, cache reuse, and
64/256/1024/4096 target-host full lifecycle. Evaluator, selector, executor,
signed A0, generation/fence, durable artifacts and NDU final-use remain
separate. Neither this archived bridge nor synthetic CI is a promotion gate.

**No production model promotion, CAS/CNS cutover or physical Cell split.**
