# platform.wire: command-bound qualification and managed-stream properties

This follow-up extends the existing PR #1094 implementation, from source
`2474a778e0cd0fb6165c2f1b1694ca41b649f862`. That parent is an implementation
reference, not a qualification receipt for this revision. The subject of new
execution evidence must be the containing commit and its tested tree.

Read this alongside `TECHNICAL.md`, `SECURITY_AND_QUALIFICATION.md`, and the
existing Lane A implementation map. It does not replace those documents,
create another canonical lifecycle status, or grant acceptance.

## Ownership and protocol boundaries retained

`ManagedRecordStream` still consumes the existing
`ManagedAuthenticatedWireSession`. No second authenticator, durable store,
replay journal, transport executor, or domain authorization owner is introduced.
The fixed HPTA/HPTM formats, authenticated admission order, final-use authority,
zeroizing retirement, accepted-prefix delivery and cooperative work budgets
are unchanged. A successful record does not authorize its enclosed effect.

The stream owns no persistent checkpoint. A durable consumer must separately
prove that its checkpoint does not advance beyond the consumer's durable
accepted/committed prefix. These tests neither invent such a checkpoint nor
claim to have qualified an upstream durable consumer.

## Fuzz qualification changes

The existing campaign CLI and schema remain `init`, `seed`, `run`, `finalize`,
`check` and `hepta.platform-wire.fuzz-campaign.v2`. The three actual targets
remain `decode_frames`, `managed_records`, and `policy_admission`. Corpus,
crash-artifact, preparation-log and fuzz-lock inventories are retained.

The cargo-fuzz executable is built using pinned stable `1.95.0`; instrumented
harness compilation and execution still use pinned `nightly-2026-09-20`.
Both compiler identities and the cargo-fuzz version are logged. This separates
installer compatibility from the sanitizer toolchain rather than changing the
fuzz target to stable, weakening instrumentation, or allowing an install error
to pass. Actual compatibility must still be demonstrated by the workflow.

Qualification now checks the complete target command, corpus path, working
directory, target name, deterministic seed, sanitizer/runtime arguments,
per-target duration and process timeout. It also binds source/tested SHA,
source tree, workflow SHA/ref, run ID, attempt, event, compiler identities and
runner-image identity to the current invocation. Positive retained execution
statistics, matching log digest and a strict integer zero exit code remain
mandatory. JSON booleans/floats cannot masquerade as exit codes or counts.
Malformed objects, missing targets, stale attempts, changed budgets,
zero-execution logs and interrupted work fail closed.

The runner starts Cargo in an owned POSIX process group and retires the group
on timeout, interruption or wrapper exit, reaping the direct child. Killing
only Cargo can leave its libFuzzer descendant alive. This is process lifecycle
control for the selected Linux runner, not a sandbox guarantee against a
program that deliberately escapes its process group.

`run` invalidates earlier target successes before starting any child. A failing
target does not skip the remaining targets. `finalize` overwrites malformed
receipts with failed evidence and can be called again by `check`. It does not
reuse a prior successful result when the subject or invocation has changed.
Receipt consistency is not cryptographic proof of the artifact's issuer;
release must still obtain artifacts from the trusted workflow/owner and enforce
independent review and operations acceptance.

## Generated properties through the public managed API

`tests/managed_stream_properties.rs` adds five integration tests:

| Property | Executed path and assertion |
|---|---|
| Partition and budget invariance | 24 deterministic uneven partition schedules across seven byte budgets, one-record work limit, eight distinct authenticated frames; exact order and no duplication |
| EOF prefix preservation | Every nonempty truncated prefix of the second record preserves the first frame and fails consuming EOF |
| Authentication failure isolation | Seven chunk sizes preserve only the authenticated first record; the bad suffix retires the owner, frees the record buffer, and admits no replay |
| Cooperative multi-peer progress | A bounded round-robin fixture lets a small peer complete while a large peer remains partial; cancellation retires the latter |
| Fresh-session boundary | Partial input is discarded on retirement; the old session's record cannot enter a fresh channel-bound session |

These tests call `into_record_stream`, `feed`, `seal_envelope`, `finish` and
`retire` on the public owner. They are not an alternative product protocol.
The generated corpus is deterministic, not an exhaustive formal proof.
Bindings, keys and the round-robin driver are explicit fixtures; this is not
real authenticated transport, target-host or independent acceptance evidence.

The existing `managed_stream_resources` regressions and release-mode
`managed_record_profile` are retained. The core workflow continues to execute
the real profile and its validator; no fabricated timing, RSS, allocation or
throughput result is checked into this note. Record-buffer capacity is not
whole-process memory, and fixture round-robin progress is not proof of a
production executor's scheduling policy. Measure those at the existing host
before making further buffering or zero-copy changes.

## Reproduction and evidence scope

Run the campaign regressions with:

```sh
python3 -m unittest discover -s scripts/tests -p test_platform_wire_fuzz_campaign.py -v
```

Run the managed properties and all current core targets with:

```sh
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire --test managed_stream_properties
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire --all-targets
cargo clippy --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-wire --all-targets --no-deps -- -D warnings
```

The authoring environment ran 22 campaign regression tests, including an actual
Linux descendant-process timeout/reaping regression. This is local Python
execution on the authored file bytes, not final GitHub-SHA qualification and
not libFuzzer execution. Native test/Clippy execution, the three real fuzz
campaigns, release measurements and ordered synthetic merge must be reported
by the read-only workflows on the final published source.

The core workflow retains its existing source-head/base-merge matrix and all
prior gates; the new public integration tests are included by `--all-targets`.
Do not convert absent, queued, cancelled, startup-failed or historical runs into
a passed current-source receipt. Existing broad Lane A failures must be
diagnosed independently rather than attributed to cargo-fuzz by assumption.

## Remaining external acceptance gates

Actual transport identity and fresh exporter/key provisioning, real ingress
and consumer composition, cancellation/deadlines under the production executor,
restart and rolling-upgrade behavior, end-to-end retained memory, and any
consumer-owned durable checkpoint need source/artifact-bound host evidence.
Only the existing transport, resource and effect owners may close those gates.
Independent reviewer and operations receipts remain separate requirements.
This change does not assert production activation, release or independent
acceptance, and does not change lifecycle booleans to manufacture completion.
