# Hepta DecisionCell equal-size Encoder replacement — P0 source gate

**Status: DRAFT / RESEARCH_ONLY / DENY_ALL / HOLD_NO_GO. No selected model, release,
NDU training, CAS/CNS/FinalUse, online Cell Split, or changes to production Worker.**

This additive research slice starts from main's backend-neutral Neuron contract.
It prevents an apparently impressive public checkpoint benchmark (different data,
training or token budget) from being mistaken for a controlled Hepta decision result.
The P0 source gate alone does **not** download or load 400–434M pretrained
models or certify performance. The separate opt-in P1.5 workflow attempts real
model loading only after source-byte and independent rehash gates have passed.

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

### Source metadata preflight

`preflight.py` calls the pinned immutable HF revisions via `HfApi.model_info`
and requires the advertised checkpoint and tokenizer inventory plus LFS metadata.
It **never downloads checkpoint weights or creates a valid model loader receipt**.
It rejects missing/oversized files and records Ettin's `.bin` conversion risk.
A dedicated non-PR GitHub CI job performs the real upstream **metadata-only**
lookup; source tests use mock metadata and cannot be treated as a Hub success.
Network/Hub failure is a blocked candidate, not permission to use a mutable repo.

## Read-only executable gate

```bash
cd qualification/stem-replacement-p0
python3 -m unittest -q test_gate test_preflight
python3 -O -m unittest -q test_gate test_preflight
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

## P1 continuation: exact physical source bytes (2026-10-17)

`preflight.py` now separates the **entire upstream repository inventory** from
**only the actually selected candidate source files**. A Laya repository may
bundle multilingual and typed-decisions sibling checkpoint weights; those other
weights **are not** Laya421 input bytes and cannot be charged or automatically
loaded for this selected Cell. Model tensor files must expose exact pinned
LFS/Xet-compatible SHA-256 hashes; selected JSON/tokenizer files must expose
original LFS SHA-256 or Git blob SHA-1 from the pinned immutable source commit.
Both actual sha256 and original Git-blob ID are checked, not self-declared digests.

`source_bytes.py` uses only the fixed Hub transport API and an exact commit
revision, requests exact selected filenames in a private new local staging root,
and re-hashes every downloaded byte (including nonweight tokenizer/config
material). It rejects partial material, aliases/symlinks, nonregular or changed
files, unselected extra files and excess byte budgets. An Ettin `.bin` is **not
unpickled**, not imported by Torch, and not interpreted as a verified tensor
checkpoint: this stage checks content only. Running a trusted
`torch.load(weights_only=True)` conversion requires a separate, explicit loader
qualification with frozen package versions, tensor-key/shape/value review,
independent backends and actual forward parity. Xet/Git LFS byte hashes are not
independent source-issuer signatures.

`review_bytes.py` is a different Python process and implementation; it rereads
all original staged bytes independently against the pinned source SHA256/Git
objects, rejects altered original producer receipts and emits only a no-authority
summary. The source files remain private in runner temp and are not uploaded.
This does **not** create a production artifact or a real Encoder inference result.

A separate push/dispatch-only GitHub workflow first checks all four *real upstream
metadata inventories*, then physically downloads and checks only the two
primary candidates, Laya421 and Ettin400, **after** the source-only tests and
metadata gates succeed. It has finite time and byte budgets; a remote failure is
a failed gate rather than permission to use an unpinned checkpoint. Typed421 and
OpenJev434 remain metadata-only controls pending the primary physical evidence.
No claim of actual completion is made until each named exact-head hosted job is
observed terminal-success and its original log/result is inspected.

Locally, the new tests exercise short mocked files and independent replay; not
one external checkpoint is retrieved or forwarded. **All four model arm efficacy,
matched actual 4,161-parameter training, original human-label observer,
prospective/source-independent future test, negative-transfer and target host
benchmark remain BLOCKED / HOLD_NO_GO.**

## P1.5 physically loaded CPU-forward smoke (2026-10-17 candidate)

`physical_forward.py` is a read-only, offline, exact-byte-bound experiment for
**Laya 421M** and **Ettin 400M**. It runs only after `source_bytes.py` has
created a physical source receipt and `review_bytes.py` has reread the actual
stage in a separate process. A second independent rehash is enforced inside
`physical_forward.checked_receipt` before importing any model library.

- Ettin's immutable `pytorch_model.bin` is opened **only** with
  `torch.load(..., weights_only=True, map_location="cpu")` on the pinned
  `torch==2.10.0` CPU runtime. The complete named tensor inventory, shapes,
  dtypes and byte-bounded source identity (including native Torch OrderedDict
  state dictionaries) must match an explicitly constructed
  original `AutoModelForMaskedLM` architecture; any mismatch stops the run.
  `trust_remote_code` is always false. The output is one real encoder CLS
  feature digest, **not** a binary support probability.
- Laya uses `laya==0.3.20` on a separate private **copy** of the previously
  verified source directory. The native loader may normalize the local tokenizer
  config; the source remains unchanged, and the effective runtime tokenizer
  config digest and modification flag are reported. A CPU forward hook requires
  one actual local encoder invocation and typed bounded noul output. This is
  **not** calibrated task success.
- The probes are unlabeled, bounded to 128 tokens, and do not provide private
  data or production capability. No original model checkpoint, text or secret
  is uploaded. Model import/load CPU, measured process RSS, observed parameter
  tensors, actual tokens and typed output are accounted separately from the
  previously paid download/rehash work. Timers and RSS are **self-reported** on
  the runner, not independently signed SLO or end-to-end task economics.
- The two outputs have different semantics; there is intentionally no winner,
  native-vs-Head equivalence, calibrator, training, meaningful held task score,
  future window, NDU uplift, final-use authorization or physical Cell Split.
  A future matched frozen-Encoder + identical trainable Head experiment must
  own all of those independent gates.

A dedicated read-only GitHub workflow has 81 fixture-based source/authority
unit tests (normal and optimized Python). Genuine checkpoint download and
physical CPU smoke run **only** on the named research branch push or an
explicit workflow dispatch, not on a fork PR. A green source-only PR job does
**not** mean either original checkpoint loaded. A failed, queued or skipped
physical job is `HOLD_NO_GO` rather than a partially promoted model.

Example operator-only use, after the exact model source has already passed the
full physical preflight and all byte verification:

```bash
cd qualification/stem-replacement-p0
python physical_forward.py --model ettin400 \
  --receipt /secure/research/hepta-producer-ettin400.json \
  --stage /secure/research/hepta-source-ettin400 \
  --out /secure/research/hepta-forward-ettin400.json
```

## P1.6: runtime input isolation after verified physical bytes (2026-10-17)

The optional physical CPU-forward lane now passes **only a clean, temporary,
private, allowlist-only model runtime tree** to the Laya or Ettin loader.
`runtime_snapshot.isolated_verified_runtime` independently reopens the
pinned original-byte receipt, copies each registered source file with
no-follow/regular-file checks, recomputes the original LFS SHA-256 or Git blob
identity while copying, and independently rehashes the new runtime tree.
No Hugging Face downloader cache or unregistered model/tokenizer/config file
enters that runtime tree. It is removed on exit. Laya's known tokenizer
normalization is confined to private runtime copies, not the staged original.

This closes the ordinary downloader-directory drift gap between source-byte
review and model import. It does **not** establish a hostile same-UID process
sandbox, a publisher signature, a final-use grant, or any scientific utility.
The native forward receipt records
`isolated_allowlist_runtime_snapshot_verified=true` only after this path.
Missing/tampered files or refused runtime copies fail before model import;
the source tests use tiny *synthetic* mock checkpoints. In the bounded source
suite, seven added snapshot-specific tests cover exact-copy/reopen, tampering,
late-added config, downloader cache exclusion, original-file preservation,
symlinks and missing checkpoint bytes. Both normal and optimized local
Python runs complete 84 tests; exact-HEAD hosted CI, original 400M/421M
CPU-forward and full blocking-ci outcomes remain independently unverified.

The additional snapshot copy counts toward physical wall/CPU/RSS/disk
resource cost; zero-cost reuse and 4096-Cell target-host claims are forbidden.
This PR stays DRAFT / RESEARCH_ONLY / DENY_ALL / HOLD_NO_GO. No main merge,
model selection, CNS cutover, FinalUse or physical Cell Split.
