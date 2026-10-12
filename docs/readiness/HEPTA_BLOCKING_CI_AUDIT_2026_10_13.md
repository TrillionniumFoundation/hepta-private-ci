# Hepta blocking CI evidence and release blockers — 2026-10-13

**Review status: DO NOT MERGE / DO NOT PROMOTE TO PRODUCTION.**
Snapshot references the exact [signed Stem PR #1517](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1517)
head `f4cedf984a3e117982a072a1fd9f0d399a071498` and
[blocking-ci run 38239518519](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38239518519).
Review CI on the final **combined** SHA before changing this status.
This report is an audit, **not** a substituted test receipt.

## Confirmed native qualification

On #1517 head `f4cedf984a3e117982a072a1fd9f0d399a071498`,
Worker Bridge, Neuron Stem, v8-canary and architecture-convergence workflows
each concluded `success`. #1510 had the corresponding named successes on
`821687a48d245de64f8a0b07339c3bb493a966e8`. None of those
successes overrides the failed global CI or supplies real Jina weights, signed
production Stem artifact provenance, NDU learning gain, or 4096 Cell benchmarks.

## P0.1 — Exact Windows core API compile defect (this PR)

Run `38239518519`, Windows Bazel release, failed
`//codex-rs/core:core-unit-tests-bin` compilation at
`core/src/client_provider_policy_tests.rs:117` with `E0277` and `E0061`.
All **six** terminal-acknowledgment policy tests still called
`map_response_events(upstream_id, events, telemetry, trace, provider,
attempt, redact, observer)`, whereas the implementation now expects
`map_response_events(events, ResponseEventMapContext { ... })`.

This PR updates all six tests without removing any expectations or changing
production dispatch behavior. It adds a separate pinned Rust 1.95
`windows-latest` Cargo test of the unmodified terminal-policy assertions,
and the preexisting `blocking-ci` continues to run. This fix is **unverified
until the new Windows and final Bazel runs succeed**.

## P0.2 — Security advisories still block cargo-deny

The same CI failed `cargo-deny` on **real reported dependencies**:

| Advisory | Package and dependency source | Genuine remediation |
| --- | --- | --- |
| [RUSTSEC-2026-0318](https://rustsec.org/advisories/RUSTSEC-2026-0318.html) | `matrix-sdk-crypto 0.18.0` via `matrix-sdk 0.18.0` / Matrix adapter | Upgrade crypto and compatible Matrix SDK family to patched `>=0.19.0`, regenerate lock file, run native + Matrix authentication/replay tests |
| [RUSTSEC-2026-0319](https://rustsec.org/advisories/RUSTSEC-2026-0319.html) | `anymap2 0.13.0` via `matrix-sdk` | **Upgrading to matrix-sdk 0.19.1 is insufficient:** its published crate manifest still declares `anymap2 ^0.13.0`. Requires reviewed compatible upstream replacement or independently audited patch/migration to `anymap3` |
| [RUSTSEC-2024-0449](https://rustsec.org/advisories/RUSTSEC-2024-0449.html) | `unsafe-libyaml 0.2.11` via `serde_yaml 0.9.34` used by core plugins | Migrate owned YAML serialization/deserialization to a maintained safe parser with canonicalization, semantic and adversarial conformance tests |
| Yanked warning | `chacha20 0.10.0` via `rand 0.10.1`; other yanked packages | Review transitive dependency graph, resolve to available audited versions and regenerate lock without disabling warnings |

Do **not** add advisory ignore entries, delete lockfile evidence, or declare
a `cargo-deny` green result merely after a partial Matrix upgrade.

## P0.3 — Separate Windows/Bazel failures not fixed by this PR

Additional failures in `38239518519` include Unix-specific durable ownership
fixtures on Windows (Agentd `secure durable Prompt Registry owner unavailable
on this platform`), Windows Matrixd local socket-path qualification,
Supervisor signed-intent/restart recovery, Git Utils, queue timing,
snapshot assertions and worktree mutations on failing tests.

These require targeted platform conformance/fail-closed tests and real host
implementations where intended. **Never silently skip an affected platform,
weaken authority on unsupported Windows paths, or claim that passing Linux
qualification proves Windows availability.**

## Strict downstream gates

1. Rebase or merge each stacked Draft PR against the latest predecessor and
   preserve independent native CI evidence on the *combined* SHA.
2. Validate Rustfmt, Cargo tests and strict Clippy; Windows Bazel and MSVC
   compile; `cargo-deny` with no ignored advisories; and genuine unclean
   recovery with fault injection.
3. Connect independently verified Stem Artifact CAS/load/signature/selected
   generation/Final-use to the owner and actual Worker, then confirm
   terminal receipt, checkpoint CAS and WAL replay.
4. Run approved, pinned Jina Text/Omni weights against no-change, frozen and
   learned Cell Heads with prequential future windows, negative transfer,
   real signed NDU, and physical 64 / 256 / 1024 / 4096 Cell resource tests.

**No green production gate or model upgrade is asserted by this audit.**
