# V15 native migration transition increment

## Result and boundary

This increment fixes a reproduced monotone-counter defect in the Python reference
and adds a deterministic Rust implementation of five migration transitions:
`prepare`, `recover_prepare`, `ready`, `commit` and `abort`.

The signed Python/SQLite reference passed **57/57** protocol cases, including the
original 53 and four counter-exhaustion regressions. A seeded differential experiment
executed **1,536 operations in 64 stateful sequences**. The compiled Rust runner
on both Mac arm64 and x230 x86_64 matched every acceptance/rejection outcome,
cell owner/epoch/phase, addressed transfer phase and complete retained transfer history.
There are 1,600 output lines per host, including 64 resets.

**This is a native transition-subset qualification, not production Control
integration, a second authority, full V15 equivalence, or new memory efficacy.**
The kernel performs no I/O. No runtime service or training process was replaced.
There was no model/LoRA transfer between these hosts: each host independently ran
the same transition fixture.

## Reproduced defect

The pinned baseline is
[`379c21c2e625c3a3dfbb514e11b9e8fe2213cda8`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/379c21c2e625c3a3dfbb514e11b9e8fe2213cda8/qualification/memory-cell-v15).
At SQLite's signed integer maximum, `epoch=epoch+1` promotes the value to REAL.
The original implementation accepted three counter-changing requests and ended
with the same imprecise floating-point epoch on the latter two receipts.
This violates strict monotonicity and exact compare-and-swap identity.

The reproducer directly installs a saturated epoch into a real SQLite fixture.
It does not claim that a normal deployment can perform 2^63 updates in practical
time, or that an unprivileged user can edit the database. It exercises an edge
condition relevant to imported or corrupted authority state.

`next_counter` now rejects a counter-changing request before overflow or mutation.
Source revisions receive the same signed rejection treatment. Prepare reserves
two representable increments so that either commit or abort can finish. The last
legal prepare/commit reaches the integer maximum without promotion.

A saturated counter has no implicit rollover. Its mutations stop; existing
read/status semantics are unchanged. A separate, reviewed authority namespace
transition would be needed to resume mutations. This change does not protect
against restoration of an old complete authority filesystem.

Original and repaired outputs are preserved as
[`epoch-before.json`](../evidence/native-transfer-20261105/epoch-before.json) and
[`epoch-after.json`](../evidence/native-transfer-20261105/epoch-after.json).
The original Python `authority.py` Git blob was
`8a8791e79f3e1a84c1244271db83886ab1cc72c6`.

## Native integration contract

`transfer.rs` contains typed current state, requests, proposed state, phases,
and rejection reasons. It has no dependency beyond Rust's standard library.
A caller may include this module in the existing native Control owner after the
remaining integration requirements are implemented.

A trusted Control adapter must, within one serialized authoritative transaction:

1. Authenticate the actor and authority identity, bind the full request and
   idempotency key, and reject conflicting replay.
2. Load a complete current cell and transfer cut; validate persisted identifiers,
   integer counters, bundle bytes, effective permission and source revisions.
3. Construct the typed request and current source status, then call `transition`.
   A `Ready` request's `verified_bundle` is a digest of bytes already checked by
   the adapter; it is not an assertion accepted from an untrusted client.
4. Persist the proposed cell and transfer rows together with the signed receipt
   and durable request binding before granting any execution effect.
5. Recheck current epoch/owner at final use. An old successful receipt does not
   grant fresh authority, and copying a proposed state does not commit it.

The module has explicit owner/admin handoff, epoch/bundle comparisons, source
freshness gates, duplicate transfer refusal, recovery-controller abort rules and
checked integer increments. It leaves publication, reshape, authorization,
signed receipts, durable deduplication, torn-WAL recovery, I/O and whole-authority
rollback protection outside its scope. Its public state is intended for a trusted
adapter; it is not a safe untrusted deserialization API.

`runner.rs` is a nine-field, bounded-input qualification transport. Fixture numeric
IDs stand for public keys and bundle digests. It neither authenticates a user nor
persists state and must not be exposed as a service.

## Executed evidence

The Python oracle uses real signed Ed25519 requests through the reference
SQLite WAL/FULL authority. Every operation gets a new request ID. The experiment
injects wrong actors, epochs, bundles, cells, transfers, readiness digests and
same-owner targets, plus source invalidation and high counter fixtures.
It compares state and outcomes, not the wording of rejection messages.

| Operation | Accepted | Rejected |
|---|---:|---:|
| prepare | 103 | 251 |
| recover_prepare | 109 | 264 |
| ready | 81 | 207 |
| commit | 33 | 216 |
| abort | 146 | 126 |
| Total | 472 | 1,064 |

These are 64 related traces, not 1,536 independent statistical samples. The ASCII
fixture identifiers, mapped keys and operation subset do not establish universal
input-domain equivalence. Authentication attacks, idempotency and process-kill
recovery remain exercised by the Python suite, not newly ported to Rust.

| Actual host | Toolchain | Comparison | Runner wall seconds | Runner child CPU seconds |
|---|---|---:|---:|---:|
| Mac, macOS 26.6.2 arm64 | rustc 1.95.0 | 1,600 / 1,600 lines | 0.843602 | 0.016512 |
| x230, Linux 6.8 x86_64 | rustc 1.95.0 | 1,600 / 1,600 lines | 0.008265 | 0.007545 |

Both were compiled with `--edition=2024 -Dwarnings -O`. Separate final
`rustfmt --check` runs passed on the exact source hashes on both hosts.
Runner wall time includes process startup and host scheduling; these one-shot
numbers are not a speed benchmark. They exclude compilation, setup, transport,
review and all energy/cloud costs.

The Linux Python suite used Python 3.12.14, cryptography 50.0.2 and SQLite 3.53.1;
its recorded validation wall time was 4.292 seconds. The local partial workspace
does not contain `just`; the required `just fmt` attempt returned exit 127.
The scoped native format/compile runs above are the only new Rust validation
claim; no whole-repository formatting or build gate is claimed.

The two original native stdout files have identical SHA-256:
`e3e7b7f0b0584abaaef4f5d8d7745c9bcabaacf4466aef466eecc9c480dcc03f`.
Comparison strips trailing whitespace per line; it preserves line count and all
state fields. Raw bytes and their distinct expected-output digest are retained.

See [QUALIFICATION.json](../evidence/native-transfer-20261105/QUALIFICATION.json)
for machine-readable status, source identity, costs, job identities and limits.
The raw archive retains commands, expected states, Python decisions, both complete
native outputs, source snapshots and execution scripts. The archive manifest
records each member's size and digest. Host receipts report observed executions;
they are not hardware attestations.

## Reproduce

From a complete checkout with the recorded Python dependency and Rust 1.95.0:

```sh
python3 qualification/memory-cell-v15/verify.py
native=qualification/memory-cell-v15/native-transfer
evidence=/tmp/memory-v15-native-reproduce
python3 "$native/differential.py" generate "$evidence"
rustfmt +1.95.0 --check --edition 2024 "$native/transfer.rs" "$native/runner.rs"
rustc +1.95.0 --edition=2024 -Dwarnings -O "$native/runner.rs" -o "$evidence/runner"
"$evidence/runner" < "$evidence/commands.txt" > "$evidence/actual.txt"
python3 "$native/differential.py" compare "$evidence" --actual "$evidence/actual.txt"
```

Run `exhaustion_reproducer.py` with the original pinned authority and with the
changed authority in separate checkouts to reproduce the before/after result.
Its direct SQL fixture setup must never be applied to a live authority database.
The dedicated workflow repeats the scoped protocol and differential checks.

## Still open

Production Control integration and native authentication/transaction adapters,
native replay and torn-WAL parity, full authority rollback/consensus, remote
final-use fencing, real model plus optimizer/RNG continuation, matched-resource
semantic evaluation and complete economic cost remain open. The historical
negative LoRA-versus-retrieval evidence is unchanged.
