# P41 Plugin Catalog auth-mode boundary — native rustfmt follow-up

Observed UTC: 2026-10-25. Evidence-only notes accompanying a **formatting-only** code change.

- Parent isolated Draft: [#3966](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3966), exact source `c31907a29fe3570afdb07e622f64a7c7b7417cdc`.
- Parent-source blocking CI: [run 40218860221](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40218860221).
- Original **executed FAILURE**: `repo-checks / build-test`, job [121312656965](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40218860221/job/121312656965), emitted `Diff in .../codex-rs/core-plugins/src/manager_tests.rs:7297:`; `just fmt-check` failed with exit code 1.
- Minimal exact repair: rustfmt's requested multiline layout for `assert_eq!(api_identity.chatgpt_user_id, headers_identity.chatgpt_user_id)`. Test expression, negative assertions and production logic **unchanged**.
- Same exact parent-source cargo-deny: job [121312657017](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40218860221/job/121312657017) **FAILURE**, `RUSTSEC-2026-0387 / crypto-bigint 0.5.5`, upgrade guidance `>=0.7.6`. **Not repaired** here; no dependencies or ignorelists changed.
- Parent-source Windows Native Hepta paths job [121312657072](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40218860221/job/121312657072) **SUCCESS**; this scoped path check does not resolve Windows DELETE, ledger or AppServer ownership.
- Architecture base-merge job [121245837396](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40218860277/job/121245837396) **SUCCESS**; source-head and final required not yet established.
- V8 metadata success in [run 40218860195](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40218860195) is scoped; skipped variants do not qualify themselves.
- Other jobs remain mixed pending/in-progress/terminal. Fetch exact run/job logs and artifacts again for the **new** SHA. Queue state or artifact emptiness does not imply nonexecution.

No frozen P39 research cohort/plan/weights/thresholds or original Windows positive/negative cases were changed. No full policy or target-device claim. `SHADOW_ONLY / DENY_ALL / HOLD_NO_GO`. **No blocker closed solely by this patch.**
