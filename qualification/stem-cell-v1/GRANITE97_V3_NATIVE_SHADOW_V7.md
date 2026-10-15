# Granite97 V3 shadow CLI: original-source and independent-review admission

**Research only · DENY_ALL · No selected model, no FinalUse, no network, no effects.**

This adds an executable **native Rust command** on top of the existing
producer [#2388](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2388),
independent physical review [#2392](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2392)
and imported V3 multi-Cell Reader [#2393](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2393).

The CLI is deliberately **not** another model loader. Given four
*independently admitted* absolute-path files, it checks exact source/model/review
bytes, loads immutable V3 Q24 token rows into the real Rust Cell Reader, then
prints a bounded **source-free** JSON response. The file names and the CLI
are not proof that any model was run. Review JSON's forward/timing numbers are
still labeled as **claimed**.

## Required inputs, separated by owner

The original source is one complete UTF-8 file containing the *entire*
question, all ordered options and admitted context. The producer export is the
exact create-only file from the genuine pretrained Python encoder. The physical
review is the exact create-only, separately executed output of
`granite97_v3_independent_review.py`. An independent data/model owner must
freeze and attest both file SHA-256s, original source SHA-256, the model
material SHA-256 and **all** model preprocessing/adapter identities *before*
the Rust program consumes any inputs. Do not build or "approve" the
admission using values copied from untrusted export/review bytes.

The fourth file is this external owner's **data-only** JSON admission.
Its fields, all mandatory and no unregistered extensions allowed:

```json
{
  "schema": "hepta.stem.granite-v3-local-admission.v7",
  "principal_id": "research:principal-a",
  "purpose_id": "stem-reasoning",
  "generation": 7,
  "authority_epoch": 2,
  "material_digest": "<independently pinned 64-digit lowercase SHA256>",
  "source_digest": "<independently pinned original bytes SHA256>",
  "complete_input_digest": "<independently pinned complete original tokens SHA256>",
  "tokenizer_digest": "<original tokenizer asset profile SHA256>",
  "normalizer_digest": "<original normalizer profile SHA256>",
  "quantization_digest": "<original FP32-Q24 profile SHA256>",
  "preprocessing_digest": "<original full preprocessor profile SHA256>",
  "adapter_digest": "<identity/modality adapter profile SHA256>",
  "export_bytes_digest": "<the exact create-only export-file SHA256>",
  "independent_review_bytes_digest": "<the exact separate review-file SHA256>",
  "maximum_expires_at_ms": 1790000000000,
  "maximum_attention_pairs": 500000,
  "heads": [
    {
      "cell_id": "cell:a",
      "attention": "causal",
      "query_q24": [0],
      "key_q24": [0],
      "value_q24": [0],
      "local_q24": [0],
      "bias_q24": 0
    }
  ]
}
```

The above is **schema illustration, not valid physical admission**:
all SHA placeholders must be independently verified exact digests,
`maximum_expires_at_ms` must be in the *current* source owner TTL,
and each listed weight array must have **384** Q24 coefficients rather than
the one-element abbreviations above. Up to 32 independently parameterized
Heads may be activated at once. Each Head candidate's materialized digest
includes its Cell name, all frozen model/preprocess identifiers, attention
policy and every coefficient. The scalar Q24 Reader must not be called an
actual trained Transformer Head or claim reasoning generalization.

## Execute at the frozen real source

```bash
# On a prepared host with the original exact source, export and reviewer files:
cargo run --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-infer-worker-host --bin hepta-granite-v3-shadow -- \
  --admission "$OWNER_MANIFEST_ABSOLUTE_JSON" \
  --original-source "$ORIGINAL_SOURCE_ABSOLUTE_FILE" \
  --export "$CREATE_ONLY_EXPORT_ABSOLUTE_JSON" \
  --review "$CREATE_ONLY_REVIEW_ABSOLUTE_JSON"
```

The Rust entry point takes its current epoch time from the **host clock**, not
from command-line JSON. It refuses missing, relative, symlinked, oversized and
non-regular paths. Each file read is capped independently (owner 1MB, source
64KiB, export 2.5MB and review 64KiB). The input-source digest, frozen model,
expiry, independent review digest, Q24 tensor values and Head resources must
pass the unchanged native V5+V6+V3 gates. No original source, raw tokens,
hidden features or large model tensors appear in stdout. A failing gate
exits nonzero without printing a successful model or Cell result.

A valid research-only stdout has schema
`hepta.stem.granite-v3-local-shadow-result.v7` and
`authority="DENY_ALL"`, `model_selected=false`,
`production_authorized=false`. The gate receipt binds the exact owner
admission bytes, independently admitted review/export/source/model/feature
and each Cell's Q24 output and resource-accounting digest.

## What can be proven now versus later

**Source-only Rust tests** exercise constructed fake feature/review JSON,
record-binding, output redaction, two actual CPU Q24 Head operations and
adversarial admission; these are not real Granite97 pretrained forwards.
The existing shared-feature native check workflow includes
`cargo check --all-targets` and `cargo test --lib` for this crate, which
must finish successfully for an exact branch HEAD before any merge.
No `cargo` toolchain, pinned real pretrained safetensors or supported
Transformers are available in the present isolated author container.

A real qualification still requires source-authorized pinned weights, a
separate physically executed producer and reviewer, the exact native command
above, original outcome labeling with independent future/source groups,
matched shared/independent-421M and cheap model controls,
actual process/cold-load/memory/latency/energy accounting, retention,
and marginal NDU-System2 utility. This CLI never constructs a signed owner
token, production grant, external tool executor or native executable memory.
