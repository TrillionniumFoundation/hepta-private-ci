# Final CI snapshot before PR #2599 repair

Observation window: **2026-10-18 17:36:53.874–17:37:42.653 UTC**.
Repository: `TrillionniumFoundation/hepta-private-ci`.
Collection is complete for the two exact source commits below. All runs, checks, statuses, and latest-attempt jobs were fetched with explicit pagination. Each reported total equals received count. This is one read-only observation, without reruns, dispatches, or mutations.

## Immediate blocker: compilation regression introduced by this wave

PR #2599 source `19c5cd41c17dd42da7afac96203a4bc7901e23a6` failed in [Architecture run 39140469435, source-head job 117713683668](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39140469435/job/117713683668).
First failed step: **21 — Converged authority and browser semantics**.
The actual command was:

```text
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-agentd browser_servo
```

It exited 101 after 476.110592174 seconds because compilation of the agentd lib-test target failed. The command receipt reports zero observed passing or failed tests; this is not a runtime test failure.

The two E0599 errors are in `codex-rs/hepta-agentd/src/automation_effect_host.rs`:

- Line 939 applies `.context("provider key")?` to `Result<ProviderEffectKey, ProviderEffectBindingError>`. The error enum at `codex-rs/hepta-contracts/src/provider_effect.rs:474` derives only Clone, Debug, Eq, PartialEq and does not implement StdError. Suggested local error conversion: `.map_err(|error| anyhow::anyhow!("provider key: {error:?}"))?`.
- Line 971 applies `.context("contract digest")?` to `Result<Sha256Digest, String>`. String does not implement StdError. Suggested local conversion: `.map_err(anyhow::Error::msg).context("contract digest")?`.

The exact old head `1ebb9b8a9313e6504d2ebf9597412f3fe9c49d9e` used `unwrap_or_else`/panic at both locations; the new invalid Context calls came from this wave's source commit `e21417abcedda77d73a08b1417522966dc2d1c0a`. The maps child did not change these source bytes.

**The earlier independent static review missed these error trait bounds. Earlier local native verification stopped at ENOSPC preflight and never compiled these changes.** The new real native CI evidence corrects that uncertainty. All Wiremock call-count assertions and authority assertions must remain in the repair. The current collector has not modified source.

## Exact-source inventory

| PR | Head | Base | Runs | Checks | Statuses | Latest-attempt jobs |
|---|---|---|---:|---:|---:|---:|
| #2599 | 19c5cd41c17dd42da7afac96203a4bc7901e23a6 | f8c9419df6ddeb36ff8b522a50219981fb8d9345 | 4 | 41 | 0 | 40 |
| #2714 | f191cd081ba16fed8827a18093b5a5b39e9a36cd | e08323af4805ed9a8d14afabf2212923195f2156 | 5 | 12 | 0 | 12 |

All 9 workflow runs are attempt 1. Every returned run/check/job source head equals its expected PR source head. PR #2599 is open, non-draft and blocked. PR #2714 is open, draft and unstable.

| PR | Job success | Failure | Cancelled | Skipped | Queued | In progress |
|---|---:|---:|---:|---:|---:|---:|
| #2599 | 9 | 1 | 1 | 5 | 23 | 1 |
| #2714 | 6 | 0 | 0 | 2 | 4 | 0 |
| Total | 15 | 1 | 1 | 7 | 27 | 1 |

These are job states, not a count of complete quality gates. The earlier checks response differs by one transitioning macOS Bazel check: it was in progress when checks were read, then cancelled when latest jobs were read. Both responses and timestamps are retained.

## Required contexts and incomplete validation

- **#2599 Architecture required:** queued, job/check 117730307873, run 39140469435. Source-head dependency failed. Its base-merge job 117713683546 succeeded but explicitly declared `native_execution_required=false` and `requires_source_head_success=true`; its planning and Python checks do not substitute for failed source native execution.
- **#2714 Architecture required:** queued, job/check 117734399071, run 39140341635. Both source-head and base-merge lane jobs succeeded.
- **CI required:** not yet present for either head. Blocking-ci runs 39140469581 (#2599) and 39140341708 (#2714) remain queued with incomplete child matrices.
- Main's required-context names were verified in earlier branch metadata. The administrative full protection endpoint was inaccessible. Protection on the research target was inaccessible; this snapshot does not assume inherited main protection.
- Both v8-canary runs have overall success with a metadata job success and two native build jobs skipped. This is not native v8 validation.
- #2599 CodeQL Rust job 117713672992 is in progress; the neutral CodeQL check reports one missing configuration, Rust.
- #2599 macOS Bazel job 117728886353 ran genuine compilation/tests but was cancelled before completion. Its log says “The operation was canceled” at 17:36:57 UTC. No cancellation actor or reason was identified. Treat as CANCELLED / CAUSE_UNKNOWN, not successful platform coverage or a proven source failure.

The #2599 source lane also contains genuine earlier passing commands, including Fleet module_catalog (7 tests) and final_use_linearization (1 test). They do not erase the subsequent agentd compilation failure or prove all authority fixtures passed.

## Evidence and boundaries

Raw PR, collections and latest-attempt job responses are retained as JSON, alongside three complete decoded job logs and both old/new automation source plus the exact provider error definition. Member hashes and exact Git blob hashes are computed from decoded UTF-8 bytes. No large run artifact or model weights were downloaded for this snapshot.

This observation executes no model calls. The previously collected 64 fresh Laya calls remain separately documented evidence; they do not fulfill the 40 calibration plus 72 nine-arm acceptance requirement. Research remains SHADOW_ONLY / DENY_ALL / NO_GO.

No CI was rerun or cancelled by this collector. No GitHub writes were made. No pending agent-owned tool call or background process remains after local archive creation. This is preserved as **pre-repair evidence**; a subsequent source repair requires its own exact-head checks.
