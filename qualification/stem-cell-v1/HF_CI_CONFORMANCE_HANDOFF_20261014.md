# Clean CI repair and actual HF conformance evidence

Parent: `cc8d4d844ec8bde7e9e1f161c8fc85c51e331081` (PR #1773).
Tested code: `08864e3195d4443422d5f12db157370e7c6e6314` (PR #1785).
Branch: `research/shared-stem-hf-ci-conformance-20261014`.
No runtime algorithm, model selection, native installation or deployment changed.

## Real failure, not a speculative dependency fix

Hosted run 38513037442 / job 115685624515 failed with 25 errors after reporting
295 tests. safetensors 0.7.0's torch bridge imports packaging.version, but the clean
CPU dependency step installed only numpy, safetensors and torch. The local source
container already had packaging 25.0, masking the gap. Preserve the original
failed log and environment; it was not a passing complete 393-test run.

The workflow now explicitly installs packaging==25.0 in each existing profile
and imports the actual safetensors torch bridge before tests. This does not alter
model loading, arithmetic formulas, training thresholds or scientific gates.

## Test execution must match its selected inventory

run_checked_tests.py records planned and actually started unittest IDs. It rejects
empty or duplicated inventories, loader errors, incomplete class setup/execution,
skips, expected failures and unexpected successes. A passed unittest summary alone
cannot override those checks. Output is reserved before execution to prevent an
existing report from causing another run. Failed imports are retained, not turned
into skips. The runner imports no model framework and adds no alternative learner.

This verifies the selected/discovered inventory, not that every scientifically
necessary test exists. It is not authenticated source provenance or proof of test
quality. An interrupted process can leave a partial/empty output; that is not a
successful test record. HF generation checks now run independently of the Encoder
check's outcome after dependency installation; either failure still fails the
job, and the public probe still depends on overall HF compatibility success.

## Completed local and hosted source validation

Local: one complete eight-process run covered 398 distinct tests, counts
48/48/51/51/51/47/51/51, all exit codes zero, no failures/errors/skips. This includes
393 predecessor tests and five new runner tests. A previous whole-suite command
was tool-timeout interrupted and remains in the evidence package, not claimed as
a second successful run. Compileall, diff whitespace and YAML parsing passed.

Hosted: run 38514353010 / job 115689680215 succeeded on the actual prospective
merge checkout `c203fb60959b2f6b551024cb9d7c70b082cc5533`, head 08864e3.
Its retained JSON proves 398 planned and executed IDs, no discovery errors,
failures, skips, expected failures or missing tests. IDs match the local run and
all 38 test-file hashes match local bytes. Raw log: 398 tests in 44.901 seconds,
OK. packaging==25.0 is present in the hosted environment. This is source execution
on hosted CI, not a full repository/Rust/native/GPU acceptance result.

## Stock architecture checks actually executed remotely

The predecessor's run 38513037442 / job 115685624890 succeeded on checkout
`d2166bc07391bca7703c18ed50c42a86a294d66f`. It ran three actual stock ModernBERT
checks (loading/ties, metered encoding, Cell Bank connection) and two GPT2 checks
(safe loading and six-step full-prefix/DynamicCache numerical parity). No test
substitute supplied the Transformers implementation. These use randomly
initialized small models, so this is architecture conformance, not pretraining
or task-quality evidence. Local missing dependencies did not prevent these remote
checks from executing; previous receipts are not rewritten to claim earlier success.

The repaired head also completed all five checks under run 38514353010 / job
115689680373, checkout c203fb60959b2f6b551024cb9d7c70b082cc5533. Both structured
reports show complete planned/executed inventories with zero errors or skips.
The two hosted runs are separate observed executions, not inherited success.

## Public pretrained checkpoint actually loaded and encoded

The same predecessor run's public job 115688868903 succeeded. Its downloaded
artifact pins answerdotai/ModernBERT-base revision
`8949b909ec900327062f0ebf497f51aef5e6f0c8`, snapshot SHA256
`43138a5545ce4e7996d91735f2330519a8913304d3abf257f6cfdfbe0541283d`.
All 149,655,232 retained parameters (149,014,272 in the feature backbone) are
accounted for. The omitted decoder.weight key is validated as a physical alias,
not excused as an independently missing tensor. The retained MLM head is not
executed for feature extraction and remains included in storage accounting.

Three real forwards returned 768-dimensional features at token lengths 41/43/41.
Repeated identical input was exactly consistent; different input was distinguished.
This is execution of downloaded public pretrained weights, NOT a paired learning
experiment, independent observer validation or demonstration of a best Hepta stem.
HF_PUBLIC_ENCODER_PROBE_20261014.json preserves the exact remote probe bytes.
The package also retains the source lock and downloaded-material hashes, which
were checked for linkage, and the original zipped hosted observations.

The probe reports 747 unregistered ATen calls: matmul.default (198), numpy_T.default
(3), to.dtype (474), to.dtype_layout (72). Its 27,647,347,432 known formula operations
are only a PARTIAL prefix, not complete model FLOPs. Complete inference work is
null; energy is unavailable. The lifetime RSS reading is not per-request peak.
No formula was added just to declare this probe fully cost-qualified.

## Reproduce and interpret

```sh
python -m pip install numpy==2.3.5 safetensors==0.7.0 packaging==25.0
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.10.0
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python qualification/stem-cell-v1/run_checked_tests.py \
  --output /new/nonexisting/source-tests.json
```

The local working copy is a source slice, not full GitHub ancestry. No codex-rs
checkout or just executable was available for repository-wide formatting.
The evidence commit changes only records, not the tested Python or workflow.
Record each CI result against its actual checkout; do not inherit all-CI green
from these specific jobs. Independently authenticated task outcomes, matched
shared/split/NDU learning experiments, complete target costs, native recovery,
multimodal generation and large Cell-population qualification remain open.
