# Versioned ATen coverage on a fixed public Encoder

Parent: `be511bd63aaae8813c415a116d50f01fe54baba5` (PR #1785).
Tested complete code: `ac445d2ccf082af92ccd2c6af9fd825bc5147192`.
Branch: `research/shared-stem-complete-aten-coverage-20261014` (PR #1804).
No main merge, model selection, production activation or historical-record rewrite.

## Four actual missing overloads, not a blanket whitelist

The predecessor's real public ModernBERT probe recorded 747 unknown calls:
matmul.default 198, numpy_T.default 3, to.dtype 474, to.dtype_layout 72.
Its 27,647,347,432 counted operations were explicitly PARTIAL. Those historical
bytes and V1/V2 formula definitions are unchanged.

`transformer_work_v3.py` supplies an opt-in V3 profile. Policy V3 requires this
profile; mixing policy and arithmetic versions rejects. Dense CPU FP32 matmul
uses 2*B*M*N*K in the declared multiply-accumulate convention. Vector promotion,
right-aligned batch broadcasting, noncontiguous/expanded tensors and empty
contractions are handled from tensor geometry. A broadcast of zero with one has
size zero, not max(0,1). Scalars, incompatible shapes, unsupported dtypes/devices,
sparse layouts, unregistered overloads and extra arguments remain unsupported.

Explicit CPU to.dtype/to.dtype_layout conversions and numpy_T views contribute
zero *floating arithmetic* under this profile. This does not mean zero instructions,
bandwidth, allocations, latency or energy. Destination precision, layout, device,
copy options and memory format are checked. Known formulas are reserved against
the original phase cap before dispatch. Unknown work still makes a full phase
count null in observe mode and stops strict mode; there is no generic prefix
whitelist, sample-based cost guess or acceptance threshold relaxation.

The formulas use the public PyTorch matmul promotion/broadcast semantics and
Tensor.to copy/conversion semantics. The installed PyTorch 2.10 overloads and
actual execution are tested; a future overload is not automatically admitted.
References: https://docs.pytorch.org/docs/stable/generated/torch.matmul.html
and https://docs.pytorch.org/docs/stable/generated/torch.Tensor.to.html .

## Same loaded model, two observed accounting passes

The existing public probe accepts an explicit immutable upstream revision and an
opt-in arithmetic comparison. CI now pins the already observed public revision
`8949b909ec900327062f0ebf497f51aef5e6f0c8` before transfer. Source inventory,
safetensors-only loading, physical tied-weight verification and post-execution
material checks remain in place. No second Encoder copy is created.

Three original inputs run with old V2/observe, then the same inputs run with
V3/strict on the same loaded frozen model. Token counts, all feature values and
feature byte digests must agree exactly. Both observations are retained. The
strict pass must have no unknown operators or stop and a non-null inference
formula count. A failure preserves the work observation in FAILED.json rather
than publishing a successful probe. The retained MLM head remains counted but
cannot execute for features. Legacy probe behavior stays available without the
new flag.

These sequential passes are an accounting/parity check, not a paired performance,
learning or statistical efficacy trial. Complete observed eager ATen formula work
is NOT complete system cost: CPU instructions, Python/scoring/publication work,
per-request peak memory and attributable energy remain separate. The arithmetic
profile does not prove coverage of arbitrary compiled/custom/GPU backends.

The same new profile is bound into existing matrix/capture source fingerprints.
Captured critic artifacts may carry V3 units, but existing frozen-critic checks
still reject a different runtime arithmetic profile. No nine-arm NDU branch is
silently enabled and no calibrated critic, model-selection or native owner is
introduced by these mechanical bindings.

## Verified local source and geometry

Final source ran twice through run_checked_tests.py: 421 distinct planned and
executed IDs, all complete, zero failures/errors/skips/expected failures, both
process exit codes zero. The full logs report 143.042 and 146.675 seconds. This is
398 predecessor tests plus 16 formula tests and seven integration tests. All ten
uploaded code/workflow blob IDs match the exact tested local bytes (nine Python
files plus one YAML). Compileall, diff whitespace and workflow parsing passed.
Earlier foreground baseline/partition commands timed out; their raw logs remain
in the package and are not claimed as completed baseline or extra successful runs.

An additional diagnostic enumerated all 14,400 pairs of 120 dense shapes, ranks
one through four and dimensions 0/1/2. All 3,558 legal pairs matched the actual
PyTorch output-size-derived formula; all 10,842 illegal pairs returned unsupported.
Of legal pairs, 3,108 had zero arithmetic and 450 had positive arithmetic. This
checks shape rules, not the coverage of every possible matmul dispatch lowering.
The diagnostic script, complete summary and exact source digest are retained.

The ordinary local source slice has no Transformers or tokenizers. Separate HF
attempts failed at import, so zero actual stock checks ran locally and none is
included in the 421 source tests. DNS queries to PyPI and Hugging Face also failed.
Do not conflate that local limitation with separately observed hosted runs.

## Observed hosted execution

The first two code stages, head `56a575947b781618d249809eeb74d721f4e72a3a`, ran
stock compatibility under workflow 38517732944 / job 115700218385 at prospective
merge `b7875e39fc5c06feac280a44716805ec13dfb7b6`. Four actual ModernBERT checks
and two GPT2 loading/cache checks passed with complete planned/executed inventories.
That includes the new V3 strict accounting and same-feature check. These stock
checks use randomly initialized small architectures, not pretrained task evidence.
The downloaded original artifact hash was checked against GitHub's artifact digest.

The same first-stage checkout completed 414 planned/executed source tests in
31.936 seconds, zero errors/failures/skips. Its 39 test-file hashes match current
local bytes and its IDs equal the complete local inventory minus the seven later
binding tests. These are results for head 56a5759, not a claim that head ac445d2
has passed hosted CI.

At the final evidence preparation check, that run's pinned public model comparison
(job 115703635905) remained queued. The complete-code run 38518475547, head
ac445d2, also remained queued. No new pretrained arithmetic comparison result was
obtained in this session. The earlier public V2 probe is unchanged historical
evidence and is not relabeled as V3. A new source or evidence commit does not
inherit an unrelated all-repository CI pass.

## Reproduce

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python qualification/stem-cell-v1/run_checked_tests.py \
  --output /new/nonexisting/source-tests.json
python qualification/stem-cell-v1/public_encoder_probe.py --acquire-public \
  --upstream-revision 8949b909ec900327062f0ebf497f51aef5e6f0c8 \
  --compare-arithmetic --output /new/nonexisting/public-probe
```

The second command deliberately acquires the named public checkpoint; it requires
reviewed compatible dependencies/network access. The first does not download any
model. Neither command deploys, approves independent material/observer provenance,
or establishes shared/split/NDU learning benefit. No full-repository Rust/native/GPU,
1024/4096-Cell, multimodal-generation or 10T/100T equivalence claim follows.
