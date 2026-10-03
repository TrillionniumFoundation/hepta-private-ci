# Rejection and fixed-candidate evidence hardening — 2026-09-29

This implementation increment starts from `49d67536e8f21dc94ef1182451f1603342f6bcd7`, tree `043a01320aacb5d046d6191f554b606435720831`, on the existing cognitive-types closure branch. It is not module completion, authenticated product cutover, independent acceptance or deployment authority. `IMPLEMENTATION_MAP.json` remains the sole module status authority and is not promoted by this increment. Read this alongside `TECHNICAL.md`, `QUALIFICATION.md`, `INVARIANTS.json` and `DIGEST_REUSE_REVIEW_20260929.md`; those documents are retained.

## 1. Source correction and preserved boundaries

The actual source uses HNMF `MemoryEventV1`, `RecallPacketV1`, `CanonicalConsumerBindingV1` and `ContractViolationV1`. A previous external review referred to `RejectionInfo::cascade_id` and unrelated lexical consumers. Those descriptions are not repair instructions for this source. No reproduction or repair of that alleged compiler error is claimed.

This change keeps the existing read-only library, consumers and owners. It adds no storage, transport, executor, writer capability or authorization cache. Full operation, consumer, payload-family, source identity, snapshot, compatibility digest and migration posture binding remain in force. Current binding validation and full equality checks still precede final handoff use. A caller-supplied old binding is not authenticated freshness evidence.

Frozen V1 and schema-bound digests remain distinct and byte-compatible with their existing profiles. The previously introduced per-call paired digest reuse remains unchanged. No public unchecked byte-to-proof constructor is introduced, and independently expected payloads are not synthesized from received bytes to manufacture parity.

## 2. One construction path and structured refusal projection

The three public binding constructors in `src/consumer.rs` now delegate to one private `bind_consumer_v1` implementation. A private trait associates each supported Rust payload type with its payload kind, rather than accepting a caller-selected kind. Public signatures and the existing validation order are retained. The shared implementation computes the same frozen canonical digest, constructs the same complete binding, and enters the existing seal and migration checks. `consumer_accepts` and the existing source-mutation anchor are unchanged.

`src/consumer_error.rs` is a private implementation module for the existing public error type. Its exhaustive `violation()` mapping covers all ten current variants. Binding checksum failures remain `DigestMismatch`, missing compatibility/currentness fields remain `MissingValue`, wrong consumer/payload families remain `ContractMismatch`, and unauthorized migration remains `StateConflict`. The handoff now uses this mapping instead of reducing every binding failure to a generic `StateConflict` at `binding`.

This is an intentional diagnostic improvement: callers matching the old generic code/path should use the documented specific category. It does not change the public error enum, wire format, digest domain or acceptance conditions. The historical `CanonicalContract(String)` cannot safely recover a structured category from arbitrary text; its projection remains `InvalidValue` rather than guessing by parsing the string. Structured messages are fixed and payload-free. This is not a claim that every other legacy display/log surface is redacted.

## 3. Public-path regression inventory

`codex-rs/hepta-cognitive-types/tests/consumer_handoff_errors.rs` exercises the exported constructors, production codec, comparison and final-use handoff, not a replacement executor.

| Test | Obligation |
| --- | --- |
| `binding_error_categories_are_exhaustive_and_payload_free` | All ten error variants retain their category/path; structured messages do not copy a sensitive sentinel. |
| `all_five_public_handoffs_preserve_binding_refusal_categories` | Both comparison ingress and final use reject invalid binding checksums, missing fields, wrong payload families and unauthorized posture. A structurally valid resealed operation substitution cannot reuse an old handoff. |
| `all_five_public_handoffs_reject_wire_drift_without_reusing_success` | Noncanonical whitespace and wrong schema/contract/version fail through the public path after an earlier successful comparison. The unchanged original remains valid. |

The fixtures preserve the real payload matrix: `cognitive.read`, `cognitive.store` and `compact.engine` use events; `memory.retrieval` and `intelligence.control` use recall packets. The six binding-refusal cases run at both ingress and final use for every consumer. Existing semantic mismatch, resealed substitution, cross-language and mutation tests are not removed.

These are public contract integration tests. They are not proof of five authenticated default-profile product owners, current owner-epoch acquisition, real downstream effects or compatibility retirement. The new Rust tests have not been executed in the editing environment.

## 4. Complete six-artifact evidence verification

The existing read-only qualification runner and workflow remain the execution path. The six required groups are `native`, `consumers` and `owners`, each on `exact-head` and `synthetic-merge`.

`run_qualification.py` now records the check-plan version, source/evidence directories and interpreter identity. It will not mark a nonempty successful prefix as complete: every planned command, its zero integer exit code, and the final clean-worktree outcome are required. The ordered command plan and existing package, cross-language, mutation and fuzz-build commands are unchanged.

`verify_receipts.py` verifies the downloaded artifacts before the existing acceptance job can succeed:

- Exactly six separate artifacts from one source, workflow run and attempt; no missing, duplicate, unexpected or symlinked artifact directories.
- Recomputed immutable source/base trees and deterministic two-parent merge commit/tree/ordered parents, using the clean exact-source checkout. Resolution creates only Git objects and does not check out or edit candidate files.
- Receipt digest, strict JSON without duplicate keys or nonfinite constants, bounded receipt size, workflow identity, runner image and unpromoted product/activation/release flags.
- The complete ordered command list, exact arguments and package set, recorded working directories, execution times, integer zero exits and the final clean tree. Python executable locations can differ across runners but each receipt must use its one recorded interpreter.
- Actual complete log bytes matching each recorded digest. A resealed receipt with substituted log bytes, a weakened lint command, mixed candidate identity or missing outcomes is refused.

The acceptance job requires both successful matrix execution and successful evidence verification. It retains an aggregate refusal report when verification fails. Both individual and aggregate evidence remain outside the source worktree. Qualification still has `contents: read`, disabled checkout credential persistence, and no source edits, commits or pushes.

All artifacts must come from the same run attempt. Rerunning only one failed job does not authorize mixing earlier successful artifacts with a later attempt; rerun the whole six-group matrix for a new complete qualification. A candidate-owned verifier checks consistency, not independent trust in candidate code, and cannot grant product acceptance or release authority.

## 5. Bounded log processing

The runner previously read an entire command log into memory to hash it and again to display its tail. It now hashes complete logs in 1 MiB chunks and reads at most 32,000 trailing bytes for an 8,000-character diagnostic tail. Evidence bytes and SHA-256 meaning are unchanged. Empty and invalid-UTF-8 logs retain safe diagnostic handling. The verifier also streams log hashing.

This removes whole-log memory growth from these operations. It is not a selected-host latency, allocator, throughput or end-to-end cognitive performance benchmark. No authorization decision is reused as a performance optimization.

## 6. Actually executed checks and limits

In the editing environment, 23 Python unit tests passed: the four existing `test_run_qualification.py` tests and 19 new `test_verify_receipts.py` tests. The new suite uses temporary real Git repositories and explicit synthetic receipt/log fixtures to test evidence acceptance and refusal. Synthetic fixture text is not represented as execution of Rust or product commands.

Coverage includes incomplete/duplicate/reordered matrices and command plans, resealed source/tree/parent/workflow/run substitutions, altered or missing logs, symlinks, wrong digests, duplicate JSON keys, nonfinite JSON constants, nonzero or unexecuted outcomes disguised as success, weakened lint arguments, inappropriate authority flags, dirty source trees, bounded log hashing and diagnostics. Existing timeout/process-group and deterministic-candidate tests also passed.

Only those two Python test modules were reconstructed locally from the reviewed repository files. This is not a claim that the full repository Python discovery, HNMF registry checks, production codec oracle, actual source mutants or actual repository merge were executed. The editing environment has no `cargo`, `rustc` or `rustfmt`; Rust compilation, the new integration tests, strict Clippy and Rust formatting remain unexecuted locally. Workflow YAML parsing and changed-file whitespace checks are static checks, not GitHub-host execution.

Reproduction in the complete repository:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s qualification/cognitive-types-v1 -p 'test_run_qualification.py'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s qualification/cognitive-types-v1 -p 'test_verify_receipts.py'
cd codex-rs
cargo test --locked -p codex-hepta-cognitive-types --test consumer_handoff_errors
cargo test --locked -p codex-hepta-cognitive-types
cargo clippy --locked -p codex-hepta-cognitive-types --all-targets -- -D warnings
cargo fmt -p codex-hepta-cognitive-types -- --check
```

The existing workflow still runs the broader reviewed command plans. Bind any eventual pass to the final pushed commit and its fixed-base merge, not to this baseline or to a local fixture. Pending, queued, skipped, cancelled, missing or failed evidence is not acceptance.

## 7. Remaining closure obligations

Authenticated default-profile composition for all five consumers, complete native/source-and-merge qualification, compatibility retirement, appropriate cross-language/FFI/WASM evidence, selected-host performance/allocation measurements and independent acceptance remain separate obligations. This increment improves the existing source and qualification boundaries without claiming those obligations are closed or changing `IMPLEMENTATION_MAP.json` completion flags.
