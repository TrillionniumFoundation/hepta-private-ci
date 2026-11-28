# Exact Finish ownership before resident reload

The public child reload could reject capacity after receiving TurnComplete while the only reclaimable resident still owned its Finish cleanup. Two deterministic controls hold a real on_thread_idle lifecycle contributor, then call the production ThreadManager reload API. One also cancels and reissues the waiting call without releasing the held owner.

The production change takes a read-only resident snapshot, releases active/state locks, and waits only for the captured Finish completions (or that thread's actual termination). It does not pop or reserve a resident while waiting, recapture successor ownership, change capacity, add sleeps or increase deadlines. All original unloadability, pending mail, shutdown, durable rollout and environment-preservation logic remains intact.

The final control fixture explicitly selects a resolved read-only environment before either spawn. This keeps the complete before/after effective-environment and cwd equality within one authority domain. Earlier two fixture versions incorrectly compared deferred FromThread authority with the original reload path's permitted Ready normalization; both actual failures remain in the archive. The original five integration controls and their full source are unchanged.

Actual final results on macOS Rust 1.96.1 via the repository's just test entry:
- Original production with the final two controls: both fail with AgentLimitReached while the real Finish owner is held. All attempts and raw source identities are retained.
- Candidate production with the complete agent_execution module: 7/7 pass, including all original five controls, no retry or FLAKY result. Wall time including incremental compile: 35.08042537490837 seconds.
- Actual just fmt passed; Cargo manifests and lock stayed byte-identical. The archive retains all preparation failures and actual earlier observations.
- This is the macOS integration qualification. The complete original Windows consumer targets remain separately open; no old Windows run is reclassified as passing.

The archive inventory records every raw member's full bytes, mode and SHA256, and every member was independently read back from the archive before this commit.
