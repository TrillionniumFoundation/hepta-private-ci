# Original Training readonly caller registration repair

## Finding and exact scope

The complete caller gate on `8faf92e260e118508fc62f4f38f3816db24cd4cc` exited 1 naturally. Its 192-byte original diagnostic names `learning_source_bound_training_stage_readback`: the observed caller `codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs` was absent from `CALLERS.toml`. This failure is retained as a failure. The targeted repair uses exact `cc22a69972d029d3ef28d49096f396eb5214c616`, tree `827fb70ed75d30c48d4693cbd0d23ea04f5744da`.

The caller is an existing readonly implementation of `OriginalCellQ24TrainingCommandOwnerV1`, backed by the same private `Arc<SourceBoundCellQ24TrainingStageV1>`. `original_training_readback_response` first calls `readonly::require_request`, then calls `SourceBoundCellQ24TrainingStageV1::readback` with the retained Stage and original Dataset. The fixed readback purpose validates the original request sequence, context, actor, Dataset, scope, `Readback` action and absence of cancellation. It exposes no Execute operation and creates no native writer or signing authority.

Exact supporting Git blobs:

- Original readonly endpoint: `fae852c8a1d5022347e632787172b99f9d119307`.
- Original readonly purpose and request validation: `028a4ceba0738db604bcaf3bc1bf548f8c5dd832`.
- SourceBound Stage: `3eeb581ffafbd80957dcf87ad02923f27d8acb29`.

## Patch

`source-bound-training-readback-caller.patch` changes two existing files. The manifest appends this one exact existing caller path; the Training source QA adds the same third expected caller. The parsed manifest comparison proves all 534 boundary rows, all 386 protected-file rows and all other manifest values are unchanged except that single caller-list append. No Rust source, verifier, scope, timeout or authority flag changes.

`MANIFEST.json` records the baseline and postimage SHA256/Git blob identities. The root integration owns the caller-hash allowlist update and publishing.

## Verification and remaining work

The isolated existing Training source QA ran all five tests successfully, including the existing unauthorized typed and UFCS caller rejection checks. `LOCAL_QA_RESULT.json` retains the observed execution chunks and exit code. These local checks use the original relevant source dependencies.

Root submitted the canonical request `desktop-full-index-boundary-request.json` once, reconciling its initially unknown acknowledgement with the same key. The target job ran from 11:11:22 to 11:13:47 UTC and exited 0 without timeout. It read exact clean cc22, constructed the unchanged verifier's complete 6,595-file Rust index, reproduced the precise baseline failure, accepted the one-caller repair and rejected all three unregistered real Rust-call variants. The first attack clones the actual endpoint into a separate unregistered path; the others use explicit UFCS and typed method calls. Every attack must fail for that exact unexpected path. Attack files and logs stay outside the checked source tree.

The target driver retained the full 14,842-file inventory and Git identity, index, config, sparse, lock and Cargo.lock observations before and after; both source inventory and metadata were unchanged. It ran through the original `hepta_ci_exec` with a 600-second bound. Nine original result, log and metadata files were read back and checked by SHA256; `execution-readback/VERIFIED_MANIFEST.json` records every original. The final complete caller gate remains separate from this targeted source check.

Ordinary Adopt, ordinary NoUpdate and daemon-plus-Root cold-recovery qualification are unchanged. These checks grant no production authority or ordinary qualification.
