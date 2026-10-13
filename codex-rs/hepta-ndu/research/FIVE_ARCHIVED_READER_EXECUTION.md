# Executed historical Reader reference and verified model staging

Date: 2026-10-13. Source-overlay parent: `8b782dc41de3abfe4547d179a8c63189b12a3815`.
Related PR: #1697. This is additive diagnostic work: no production switch, no
replacement of `five_causal_native`, and no weakening of independent Reader,
Group, NDU, modality, or frozen-cohort admission. The five requested independent
natural-task experiments are NOT complete.

## Actual progress

The model/data archive `11586991191`, 376,363,859 bytes, was locally verified
against external SHA256
`07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`.
Original Reader and Encoder inventories were also verified. The source has
17 Reader and 13 Encoder Hub-cache metadata files. This is a real conflict with
the strict native smoke's no-cache-directory precondition, not a neural failure.
`stage_clean` COPIES the eight Reader and six Encoder model/tokenizer/config
files into new clean directories. It records every excluded metadata hash,
checks the original and copied inventories, and retains the original archive
and metadata. It does not silently delete source material or admit arbitrary
missing/changed weights. The existing native smoke caller still needs to use
the prepared directories; that caller is not rewritten in this increment.

The local environment still lacks Transformers/tokenizers, and external DNS/
package acquisition failed. Rather than relabel fixtures as model outputs, a
separately named, bounded CPU reference runs the ACTUAL pinned historical
Llama Reader and BERT Encoder tensors using PyTorch. It is NOT an automatic
fallback, a new default backend, or a generally qualified Transformers replacement.
It interprets the pinned tokenizer.json, including individual-digit splitting
before byte-level BPE, fixed chat template, WordPiece normalization, and the
explicit archived tensor geometries. All weights come from safetensors.

Equation/source references (Apache-2.0):
- https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/models/llama/modeling_llama.py
- https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/models/bert/modeling_bert.py

## Completed measurements, not CI forecasts

The separate original native-run archive `11703482865` was verified against
external SHA256
`80037375c44927f71e15dea508abb6ac3a2d5ccd03cefe2a5c21beedad37247e`,
and every inner manifest member was checked. No archived Python was executed.

1. All **64/64** successful historical control prompts reproduce the original
   Hugging Face input-token SHA256s. These are token-equivalence checks on the
   fixed archived material, not 64 new independent model evaluations.
2. A completed local resident-Reader diagnostic made **16/16 successful calls**,
   with **404 actual decoder forwards**. Eight no-evidence/retrieval outputs
   reproduce original generated-token SHA256s **8/8**, not just answer strings.
3. The other eight calls compare oracle source-support-plus-distractors against
   removing all annotated support while retaining distractors. Oracle support
   is NOT independent semantic sufficiency; provided captions are NOT pixels.
4. The four actual questions are `locomo:conv-42/q188`, `q139`, `q28`, `q226`.
   They are four exposed historical questions from ONE conversation family,
   not sixteen independent tasks or an untouched confirmation cohort.
5. All four no-evidence calls returned substantive answers rather than the
   prescribed refusal: **0/4 exact refusals**. The removed-support condition
   also has **0/4 exact refusals**, but necessity/sufficiency was not independently
   reviewed, so no semantic false-positive rate is inferred for that condition.
   No grounded-answer accuracy or reasoning gain is manufactured.
6. **23/23 final-source local tests passed, zero skipped**. These include actual
   archived BERT forwards, Llama full-prefix/KV and eager/SDPA comparisons,
   tokenizer checks, verified copy/metadata behavior and resident-driver fault
   tests. They are not a full-repository regression or hosted-CI pass.

The BERT reference was executed in tests but has not been compared against a
fresh official HF runtime. The Reader's eight exact output matches establish
only those sampled trajectories. General HF equivalence remains false.

## Failure and resource accounting

Two earlier process-batch attempts were interrupted by the local command host.
Their raw files remain in the delivery: together **three completed calls / 94
observed decoder forwards**, plus **two started calls with unknown completion
and unknown cost**. A later explicit diagnostic rerun used the SAME frozen input
packets and one Reader in the resident Python kernel. It did not turn repeated
work into new samples or relabel the interrupted runs as successful.

404 forwards describes the complete run ONLY. It excludes the 94 known earlier
forwards, the two unknown attempts, and separate arithmetic/token/model probes
and tests. No total-cost, matched-compute, throughput, energy or speedup claim is
made. The initial environment/probe failures and final raw seals are retained.

The delivered source provenance records the actual loaded generation class:
its methods' bytecode matched the retained generation source. The final source
adds only pre-forward token-ID rejection to that model arithmetic. The resident
CLI is the tested executable counterpart of the kernel driver; the recorded
16-call result is NOT described as a completed run of that CLI. All three final
source Git blob IDs were matched to the locally tested bytes.

## Reproduction

With the already verified material archive extracted into `MATERIALS` and the
original native-run archive available, create clean snapshots explicitly:

```sh
export PYTHONPATH=scripts/memory_cell
python - <<'PY'
from pathlib import Path
from five_archived_torch_reference import stage_clean
# Supply operator-owned paths; do not overwrite an earlier output directory.
for kind in ('reader', 'encoder'):
    stage_clean(Path('/approved/memory-inputs')/kind,
                Path('/new/clean')/kind, kind)
PY
export HEPTA_ARCHIVED_REFERENCE_ROOT=/new/clean
python -m unittest discover -s scripts/memory_cell -p test_five_archived_reference.py -v
python scripts/memory_cell/five_archived_reference_trial.py prepare \
  --materials /approved/memory-inputs --clean /new/clean \
  --archive /approved/system2-original.zip --output /new/reader-reference
python scripts/memory_cell/five_archived_reference_trial.py generate-resident \
  --clean /new/clean --output /new/reader-reference
python scripts/memory_cell/five_archived_reference_trial.py score \
  --output /new/reader-reference
```

Missing actual assets fail in the asset-required lane. Source-only unit runs may
skip the real-asset class only when its explicit root is absent; such skips are
not model validation. Existing raw outputs cannot be silently retried/overwritten.
The new hosted lane is additional and read-only; all existing repository gates
remain unchanged and a queued job is not evidence.

## Remaining scientific and engineering work

The real historical Reader can now be independently replayed instead of being
assumed unavailable. It still fails the observed no-evidence refusal control.
Stronger/further-trained fixed Reader comparisons, independent sufficient-evidence
reviews, meaningful Group action outcomes, calibrated NDU allocation, real media
and split transfer, native serving and full lifecycle accounting remain open.
This result does not reject shared Encoder/Cell learning. It does not qualify
the earlier Group/NDU source, supply its training outcomes, or activate its policy.
