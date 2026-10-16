# P0 V18 — original SHA-pinned Hugging Face content-addressed cache source

Research only: **DRAFT / DENY_ALL / NO MODEL PROMOTION / NO MAIN MERGE**.

## Proven actual external failure

Original V15.1 source+merge CPU run [38907753242](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38907753242), merge job `116995534023`, on strict P0 commit `12c4a3a64c508ac9f2838ac2efb20657c653f483`:

- 33/33 ordinary and 33/33 optimized original contract/mechanism source tests passed.
- Exact pinned mmBERT Hub SHA/LFS preflight completed and the original ModernBertForMaskedLM 137 weight tensors loaded.
- The next original strict physical proof returned `failure_code=original_checkpoint_missing` with `exception_class=Invalid`, not a pretrained model or task success.
- That bounded public code covers an original source path missing **or symlinked**; it does NOT alone prove which case occurred.

Independent upstream implementation identity: Hugging Face Hub **v1.33.0** `src/huggingface_hub/file_download.py` Git Blob `2658100ce167680cf32d109ad8ed6e3b7c5b105a`. It explicitly constructs `blobs/<etag>`, `snapshots/<full-commit>/model.safetensors`, then calls `_create_symlink(blob_path, pointer_path, ...)`. The standard Linux snapshot link is `../../blobs/<LFS-SHA256>`. P0's existing `verify_tied_pretrained_table` and `verify_complete_pretrained_state` intentionally reject symlink paths even if the cached source material itself is correct.

## Bounded candidate correction

Only for original repository `jhu-clsp/mmBERT-small` exact revision `0eb3d056ec1d6333cf4e19b0966dfde342a41a3a` and file `model.safetensors`:

1. Recognize a standard local-only snapshot symlink with exactly relative `../../blobs/<64 lowercase hex>` and target inside the same `models--jhu-clsp--mmBERT-small/blobs` cache.
2. Refuse absolute targets, altered repository or revision, traversal, external paths, untrusted symlink chains, missing/oversized/nonregular blobs.
3. Stream-compute the SHA256 of the **entire** blob and require it equals the content-addressed target basename. The loader does not substitute an alternate revision, regular file or synthetic model.
4. Return the now verified **ordinary regular blob file**, not the symlink, to BOTH original unchanged whole tied-table and all-serialized-tensor verifiers. The normal preregistered publisher-LFS preflight remains a separate mandatory gate.
5. Retain an already regular snapshot file only within the registered exact Hub cache scope, as permitted by the prior low-level source verifier.

Both original real `FrozenMMBert` and independent V16/V17 stage ledger use the same path resolver before the unchanged byte-by-byte checks. The existing original model and Head evaluation routes still return nonzero if a required safety or numeric condition fails. No auto-creation of cache links, model files, state migration, source label access, fallback or production authorization.

## Verification

**13/13** original-cache resolver adversarial tests normal and **13/13** under `python -O`, zero skips. Tests include valid content-addressed symlink, native Torch+safetensors reader, source modification after original SHA-naming, absolute/external/path-escape/missing links, incorrect repository/revision, unsuitable file geometry and accepted same-scope regular source. Additional source-only tests from V15.1/V16/V17 remain unchanged. The exact hosted source/merge CPU attempt must still execute on this new commit; do NOT treat local tiny synthetic safetensors as real mmBERT pretrained model verification.

A successful future original source test must report both physical shared table and **all 137** serialized original tensors byte-matched, one genuine 384D frozen CPU forward, independent P0 original human scoring, cold replay, then full four-model admission. No one of these is established by this patch. Native Hub cache source matching is **not** an independent publisher signature.

**Still DRAFT / DENY_ALL: no model selection, NDU/FinalUse, production route, physical Cell Split or main merge.**
