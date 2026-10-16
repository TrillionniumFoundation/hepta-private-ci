# P0 V14 — original mmBERT + Laya 0.3.20 physical loader diagnostic/repair

**Research-only / DENY_ALL.** Parent P0 V13 #2378 at `89a3f1606bd0fa4d7dd8214bd4eb3c64b43c7b97`. No original four-model weight change, human-label source alteration, production FinalUse, CAS, CNS, NDU or model selection.

## Observed original hosted evidence, not speculation

Actual P0 V13 run `38744510538` succeeded in original source preparation and four **Runner jobs**. The individual sealed artifacts show Granite97 and EmbeddingGemma 2 original model reports and replay tensors; **mmBERT and Laya recorded `failed_or_incomplete`**. The four-model collector and independent scoring are NOT green. A Runner's `success` may record a caught failure and has no scientific admission authority.

- mmBERT runner `116745370539`: actual pinned 0eb3d056... safetensors weights load, then `e1_mmbert_tied_loader.py` aborts `non-tied pretrained MLM parameter initialized randomly`. Original loading-info `missing_keys` were not logged, so it is not yet scientifically valid to waive the weight-missing gate.
- Laya runner `116745370716`: native pinned `laya==0.3.20` call raised `TypeError: load() got an unexpected keyword argument 'revision'`. That distribution's actual published source `NandhaKishorM/laya@23a17522aa4942da6cce53a995a275760320b691` defines `load(model_id_or_path, device, token, subfolder, fast, ...)` without `revision` or `compile` keywords. It accepts a **local original checkpoint path**. Its Agent loads `model.safetensors` and requires `strict=True` parameter compatibility.

## V14 implementation

**Laya**: `p0_laya_snapshot_v14.load_pinned_laya` first requests exact original `convaiinnovations/laya@c5d78730f3493e4fe16d61507ef4b78eef7318cf` from `HfApi().model_info(revision, files_metadata=True)`, requires exact source revision and mandatory root checkpoint/tokenizer/encoder files, downloads only that revision and the original loader's fixed allowlist, hashes each file, and verifies the `model.safetensors` publisher LFS SHA256 and any additional LFS identities before invoking **unchanged** `laya.load(local_snapshot_path, device='cpu', fast=False)` with no unsupported keyword arguments. Missing/mismatched publisher source aborts. The report includes source/checkpoint lineage; no human labels or model weights are published. GitHub/Hub identities are NOT independent publication signatures or FinalUse.

**mmBERT**: preserve the exact original tied alias policy, whole `model.safetensors` byte checker, and fail-closed missing key set. New `p0_mmbert_missing_keys_v14.fail_unverified_pretrained_missing_keys` logs a bounded lexical list of unverified parameter names and a SHA256 digest of the *key-name inventory only* to enable the **next** source compatibility investigation. Missing/extra/random tensors remain denied; this is a **diagnostic**, not an mmBERT load fix.

All evidence must be freshly generated on exact V14 HEAD. A previous V13 success/failure report is never a new physical original-model result. No forced partial four-model acceptance and no automatic retrospective E1/E2/E3/E4 rebinding.

## Locally verified scope

**22/22 new stdlib-only model-adapter tests**, normal Python and `python -O`, using **fake local model files and a stub native `laya.load`**; no real original Laya 843 MB weights or pinned 564 MB mmBERT checkpoint loaded locally. Tests reject altered publisher SHA, changed-then-rehashed local LFS bytes, fake commit ID, missing config/tokenizer files, symlink swaps, duplicate inventory, invalid URI, extra or unverified mmBERT parameter names, and false admission. Source CI also retains all prior original suites and must pass hosted exactly before any real physical model claim.

## Hard remaining gates

- Exact V14 original source/pinned runtime CI; independent hosted Laya snapshot and original native forward.
- mmBERT exact missing-key evidence, then research-scoped technical correction with **no blind alias exception**; complete state/tied table verification.
- Four original physically successful models, independent original V5/V6/V7 numerical/encoder/training replay, original source-replayed held-human score.
- Global rustfmt, `cargo-deny` and Windows Bazel blockers remain separate; do not add ignores, advisory waivers or skip CI to manufacture green.
- Independent publisher signatures, future windows, negative transfer and 4096-Cell target host still absent.

**DRAFT / DENY_ALL / NO MAIN MERGE / NO PRODUCTION STEM OR CELL SPLIT.**
