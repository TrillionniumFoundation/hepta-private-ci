# Complete Encoder checkpoint / real-HF canary handoff

Parent: `5688818fa83f2fb16c4d42753a7c744a1420be22` (PR #1713).
Code candidate: `0e8eb4f636cd7b745c219c991ceae9e790981559`.
Branch: `research/shared-stem-complete-encoder-20261013`.
Qualification/research only; no original branch rewrite, main merge, production
selection, deployment or independent model-efficacy claim.

## Implementation

The previous exact-key verifier accepts a base-only Encoder checkpoint. A full
masked-language-model (MLM) checkpoint has prediction-head tensors and may omit
its tied decoder alias when serialized. Loading a base class and simply ignoring
those keys would conceal a real model-interface mismatch.

`hf_complete_checkpoint.py` adds the explicitly selected
`modernbert_mlm_full_eager_v1` profile. Bound configuration V3 retains the full
stock `ModernBertForMaskedLM`, verifies every serialized tensor and accounts for
all omitted keys. The only architecture alias is `decoder.weight` to
`model.embeddings.tok_embeddings.weight`. An omission is allowed only if the target
was serialized AND both loaded tensors have the same physical view: device,
dtype, shape, stride, storage offset and pointer. Equal copied values are not a
tie. Missing prediction-head weights, unexpected keys, alias chains, bad geometry
and mismatched values reject. Loader missing-key reconciliation happens after
this physical proof, not before it. The default verifier remains strict.

The full frozen checkpoint remains resident and is counted once per unique
storage. Feature inference calls only its base Encoder; the MLM head is retained
but not executed. All full-checkpoint weights are rechecked afterward. The profile
pins Transformers 4.57.1, CPU FP32, eager attention and reference_compile=False.
Configuration and safetensors sizes are bounded before model construction.
It never loads/converts `.bin`, downloads models or executes remote model code.
Existing bound-config V1/V2 behavior and historical material are preserved.
This does not change the five supported non-split/non-NDU execution arms.

`transformer_work.py` adds a separate formula-work V2, selected by measurement
policy V2. It covers eager LayerNorm, rotary primitives and relevant embedding/
mask/view operations. V1 counts are not silently redefined. Centered LayerNorm
costs 5N+3G plus affine scaling/bias, under the declared primitive convention.
Data movement is zero floating arithmetic, not zero runtime cost. Unsupported
fused attention remains unknown. These are not hardware instruction, complete
system FLOP, energy or general HF-model coverage certificates.

## Two different hosted checks

`hf_profile_checks.py` defines three REQUIRED installed-Transformers checks:
full stock architecture save/load/tie parity, actual encoded-feature metering,
and the existing bound runtime with a real 16-Cell bank. Its miniature weights are
locally initialized architecture fixtures, NOT pretrained or efficacy evidence.
This file is a separate entry point and fails at import if dependencies are absent;
it is not a silently skipped subset of the passing local suite.

`public_encoder_probe.py` separates explicit acquisition from local-only inference.
The only acquisition target is `answerdotai/ModernBERT-base`; the immutable Hub
commit and exact file-size inventory are persisted BEFORE transfer. Only five
stock JSON/safetensors filenames are allowed, at most 800 MB in total. No token
is requested. Downloaded files are copied into a stable snapshot without Hub
cache metadata, hashed, and then loaded through the complete-checkpoint profile.
This public diagnostic neither mints independent material approval nor replaces
operator-approved study materials. The model choice is an interface canary, not
selection of an optimal Hepta stem. The mmBERT conversion path on the separate
research branch is not duplicated or silently imported.

The canary executes three label-free feature calls, checks exact repeatability
and different-input distinctions, prevents MLM-head execution with a hook,
reverifies the checkpoint and retains operator coverage/missingness. It performs
no parameter training, benchmark scoring, paired efficacy or production selection.
A successful canary alone would NOT close P1-P5 scientific acceptance.

The EXISTING workflow retains both prior jobs and adds installed-HF compatibility
plus a dependent public-weight canary. Permissions stay contents:read. Source SHA,
package versions, raw logs, source lock and observed probe/failure JSON are retained;
model weights are never uploaded as CI artifacts. Public acquisition is restricted
to same-repository pull requests and does not run before compatibility succeeds.
No hosted result was used to manufacture a local pass claim.

## Verification actually observed

The original 95 tests passed before editing. The final exact Python files passed
120 tests twice, zero failures/errors/skips: 95 retained + 12 checkpoint/tie +
8 Transformer-formula + 5 public-acquisition/CLI regressions. Serialization and
operations are real PyTorch; loader/network interfaces in local tests are explicit
fixtures. All eleven changed/new Python blobs and the workflow blob match the
remote Git objects. Compileall and workflow YAML parsing passed.

The local installed-HF attempt failed with `ModuleNotFoundError: transformers`;
zero of its three tests ran. Its raw failure is retained separately. Direct local
model-site DNS/download access also failed. No pretrained weights were executed
locally, and no project-cloud, native GPU, Rust/full-repository or merge-candidate
qualification is inferred. The CPU source mirror is not a complete checkout.

`COMPLETE_ENCODER_TEST_RECEIPT_20261013.json` retains exact source hashes and run
observations. Both full 120-test logs are in the downloadable source package,
with their hashes in that receipt. `HF_PROFILE_LOCAL_FAILURE_20261013.txt` records
the actual dependency failure, not a skipped or passing HF test.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_*.py' -v
# Requires the pinned Transformers dependencies; no automatic downloads:
python qualification/stem-cell-v1/hf_profile_checks.py -v
# Explicit public acquisition; never an automatic inference fallback:
python qualification/stem-cell-v1/public_encoder_probe.py \
  --acquire-public --output new-public-probe-directory
```

## Remaining acceptance

Obtain actual installed-HF and public-weight job observations; fix any genuine
loader/operator coverage failures before a measured study run. Then run approved
V2-plan workloads with complete observer costs, independent outcomes and suitable
host energy/memory attribution. Joint/cached/conditional representations, adaptive
split and NDU/System2 owner integration, consolidation/retention, multimodal
training/generation and native 1024/4096-Cell service/recovery remain open.
No efficiency, quality or 10T/100T-equivalence conclusion follows from this increment.

Primary interface references inspected:
- https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/models/modernbert/modeling_modernbert.py
- https://huggingface.co/answerdotai/ModernBERT-base
