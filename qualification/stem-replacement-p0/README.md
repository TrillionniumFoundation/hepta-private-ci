# Hepta DecisionCell equal-size Encoder replacement — P0 source gate

**Status: DRAFT / RESEARCH_ONLY / DENY_ALL / HOLD_NO_GO. No selected model, release,
NDU training, CAS/CNS/FinalUse, online Cell Split, or changes to production Worker.**

This additive research slice starts from main's backend-neutral Neuron contract.
It prevents an apparently impressive public checkpoint benchmark (different data,
training or token budget) from being mistaken for a controlled Hepta decision result.
It does **not** download or load 400–434M pretrained models or certify performance.

## Immutable public candidate identities (not trusted model signatures)

| Arm | Hub repository | Proposed model size (approx.) | Fixed revision | Comparison regime |
| --- | --- | ---: | --- | --- |
| `laya421` | `convaiinnovations/laya` | 421M | `c5d78730f3493e4fe16d61507ef4b78eef7318cf` | Native frozen/no-change |
| `laya_typed421` | `convaiinnovations/laya-typed-decisions` | 421M | `cff2845e45c4e04b89fe1b6bd5eb5b6cac56bcb4` | Native pre-trained specialist |
| `ettin400` | `jhu-clsp/ettin-encoder-400m` | 400M | `7662476d60abb071a5bd319c9f3074f3072c062d` | Frozen Encoder + fixed-budget trained Head |
| `openjev434` | `com-kotobalabs/open-jev-deberta-v3-large` | ~434M | `188ee67a5c93122b916e5acd5bdb0cb3623e380a` | Native decision classifier |

**Caveat:** nominal model class size is not an independently counted parameter inventory.
A native tuned checkpoint is **not** the same intervention as a newly trained 4,161-parameter Head.
Native-vs-new-head scores can be descriptive but **cannot establish a same-budget
winner**, even if all four scores and source hashes are present. Laya Typed is
specialized to synthetic workflow training distributions; a score from that
benchmark is not independent Hepta quality. Ettin's published main tree contains
`pytorch_model.bin` rather than a native safetensors checkpoint: any real loader
must use SHA/LFS-attested material and a deliberately reviewed safe `weights_only`
load/conversion path. Do not silently set `trust_remote_code=True`, load a
mutable revision or downgrade full-tensor checks just to obtain a score.

## P0 sequence (blocking, in dependency order)

1. **Freeze original source and no-change.** Reuse the upstream original-human
   MultiRC source owner or another independently published original-label task.
   Seal the complete question + all ordered options + supplied evidence bytes;
   ensure fit/cal/test source-group isolation and a **separate** original human
   gold owner. No fabricated no-evidence labels or future dates. The source owner
   must emit an actual `panel` matching the checked schema and per-run identity.
2. **Pin and physically validate all checkpoints.** Require exact immutable
   upstream revision, **every model weight file** and tokenizer/preprocessor
   source byte hash, security-reviewed loader, true loaded-tensor census, real
   model forward and actual tokenization/truncation accounting. A digest in a
   request is not a source publisher signature; even a passing local gate does
   not authenticate model issuance or allow production use.
3. **Create comparable arms.** Run native Laya, specialized Laya, and OpenJev
   with their actual decision API; run a trained frozen-Ettin Head only after its
   projection/head parameter count, 40-step SGD, fit labels, calibration and
   original feature materialization are independently checked. For a **strict
   same-train-budget claim**, a second experiment must expose frozen Encoder
   features from all four models, train the **identical** 4,161-parameter Head
   using the same objective, seeds and fit groups, and separately charge any
   projection cost. Until then, report regimes separately, never one league table.
4. **Seal before original truth.** Write create-once, source-bound prediction
   files containing **no test labels**. Independently retrieve original test
   labels only after *all* four immutable seals exist. `gate.py` rejects partial
   arms, swapped IDs, relabeled source-groups, unsealed scores, fake model IDs,
   stolen budgets and missing actual resource observations.
5. **Evaluate in the observer process.** `gate.py` emits only descriptive
   accuracy/Brier, original test count and self-reported runtime, permanently
   `HOLD_NO_GO`. An actual unbiased candidate selection requires additional
   controlled follow-up with genuine equal Head FLOPs/params, calibration/OOD,
   independently sourced future windows, negative transfer, NDU utility, target
   host RSS/CPU/GPU/p95/p99 and independently authorized final-use/CNS.

## Read-only executable gate

```bash
cd qualification/stem-replacement-p0
python3 -m unittest -q test_gate
python3 -O -m unittest -q test_gate
python3 gate.py --panel /secure/source/panel.json \
  --sealed /secure/research/sealed_predictions.json \
  --gold /secure/observer/original_gold.json \
  --out /secure/observer/descriptive_no_go.json
```

Inputs must be regular, non-symlinked local files. JSON refuses duplicate keys
and NaN/Infinity. Output uses create-only, `0600` file permissions and fsync.
The result never names a selected model, never authorizes a Cell Split and never
calls production APIs. Tests explicitly use **synthetic receipt fixtures only**,
not pretrained model inference, issuer evidence or observed external efficacy.

**Existing research that remains independently binding:** P0 four-model loader
`#2419`, 4,145-param matched Head `#2257`, ModernBERT original CellBank `#2490`,
shared-feature native Worker `#1498`, and all security/FinalUse/Artifact/CNS owners.
These research lines are independent drafts rather than automatically selected
main artifacts. Read new P0 observations only after checking each source HEAD,
actual GitHub Actions outcome and the original content hashes.
