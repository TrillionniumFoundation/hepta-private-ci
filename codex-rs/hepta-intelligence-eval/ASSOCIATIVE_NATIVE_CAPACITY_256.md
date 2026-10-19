# Follow-on MemoryCell admission: native publisher view + LoCoMo 256-source shadow

**Research-only.** This is a follow-on to PR #2365 at the fixed previous head
`6ab0572a87b199a38da9664dbb1a9fd3222dec4b`. It does not affect the selected
production MemoryCell, owner stores, memory retrieval defaults, contracts, final-use,
or the original 128-source LoCoMo run. It adds independent test/CI gates.

## 1. Fix the failed grounded bridge without weakening the identity gate

The original source-observation / pretrained-bridge run `38759552155` failed
in the native MiniLM setup **before model execution**: its pinned model publisher
staged 11 files, whereas the native MiniLM closed-world implementation expects
exactly six registered files. The existing LoCoMo run `38759552722` succeeded
with a six-file archive extract and confirmed Transformers parity: all five
token sequences matched, maximum absolute latent difference `1.974403858e-7`,
minimum cosine `1.0`. Neither means the *failed* grounded bridge passed.

`stage_native_view(publisher, new_directory)` first hashes the six specifically
registered files, demands the exact registered six-file inventory digest
`5afecdd6098fec07380bc10a30fd8debcffcd147274b3ffd18143f1fa86dc12a`,
then physically copies precisely those bytes into a new directory and checks
post-copy integrity. It rejects source symlinks, mutation, missing bytes, wrong
weights and existing destinations. It permits *ancillary publisher metadata*
only in the original publisher directory, not in the native view. The existing
full publisher remains the input to the genuine HF reference and event bridge;
no extra file is accepted by `MiniLMOfflineEncoder`. Hosted mandatory parity
remains a required step, not an optional smoke test.

Regression tests (fake bytes are **not** a genuine model):

```sh
PYTHONPATH=scripts/memory_cell python -m unittest discover \
  -s scripts/memory_cell -p 'test_associative_native_stage.py' -v
```

## 2. 256-source capacity as a separate prospective execution

The earlier 128-source run was frozen and reviewed on 240 real LoCoMo benchmark
questions across ten authored dialogue groups. Only 38 of 238 canonical
reference-bearing questions had every required source inside that pool; its
post-seal diagnostic predicted 84/238 at source cap 256, without running a
256-source model. **This post-hoc finding is part of the decision to test 256,
so the follow-on cannot count as unselected independent confirmation of
capacity superiority.** It can identify whether increased source availability
changes evidence coverage and where the trained Cell stands relative to retained
source retrieval.

`prepare256` takes the **same published LoCoMo input bytes**, the same 24
source-independent hash-selected questions per family, and the first 256
eligible dialogue messages rather than 128. It emits the same public/private
physical separation and strict source digest and prevents answer/evidence labels
from entering inference. No new shortcut derives candidate sources from gold
reference IDs. `run` keeps `pre_steps=128`, `continuation_steps=64`, rank and
trainable parameter count as in the 128-source experiment. Note that two
source catalogues have different encoder/index and storage costs even with the
same local update count; candidate source roots and actual train examples differ.
All eight arms (frozen, shared, split, wrong route, cosine, BM25, RRF) retain
one common 256-source catalogue per dialogue. `review` runs **after** the
complete immutable journal has been sealed and rejects reference mismatch.

Reproduce with the pinned six-file encoder and frozen dataset on the host:

```sh
export PYTHONPATH=scripts/memory_cell
python -m unittest discover -s scripts/memory_cell \
  -p 'test_associative_locomo_capacity.py' -v
python scripts/memory_cell/associative_locomo_shadow.py prepare256 \
  /path/pinned-locomo.json /tmp/new-locomo256-prepared
mkdir /tmp/new-locomo256-public
cp /tmp/new-locomo256-prepared/{public,manifest}.json /tmp/new-locomo256-public/
python scripts/memory_cell/associative_locomo_shadow.py run \
  /tmp/new-locomo256-public /path/pinned-six-file-encoder /tmp/new-locomo256-run
python scripts/memory_cell/associative_locomo_shadow.py review \
  /tmp/new-locomo256-prepared /tmp/new-locomo256-run /tmp/new-locomo256-review.json
```

Hosted research-only workflow:
`.github/workflows/hepta-associative-locomo-capacity-256.yml`.
It uses the already-known exact LoCoMo dataset digest
`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`,
registered six-file encoder, *mandatory* HF native parity, complete predictions
and separate review. Exact source commit and SHA256 artifacts are retained.

### Interpretation / remaining blockers

Evidence coverage is not semantic answer correctness or citation entailment.
This is still **ten authored dialogue families**, not 200 independent families,
not two new calendar windows, and not a trained natural-language Reader. The
retrieval arms include BM25/dense/RRF but not an independently optimized strong
RAG+Reader under matched end-to-end cost. Parameter scores rank external source
catalogue values; they are not stand-alone language answers. We must not infer
any promotion, general-memory capability, statistically significant superiority,
production deletion/unlearning or real Meta Network optimization from these
runs. Leave `production_accepted=false`, and do not waive `blocking-ci`.
