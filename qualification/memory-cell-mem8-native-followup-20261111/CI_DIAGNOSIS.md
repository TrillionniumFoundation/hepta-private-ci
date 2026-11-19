# Hosted CI: bounded diagnosis of the original Fence failure

The retained original job is [43002359918 / attempt 2 / job 130483156553](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43002359918/job/130483156553). Its source is the existing MEM8 composition, not either native follow-up patch. See [raw log](./CI_BLOB_RETRY.log) and [step observation](./CI_BLOB_RETRY.json).

## Confirmed observation

Fence v0.10.0 failed before checkout with `local_control_inventory_unavailable`. Checkout, the comparison-range calculation and both blob-size checks were skipped. The later missing local-action and post-job evidence failures follow that failed setup; the log does not establish a blob-size violation.

At the exact [v0.10.0 source pin](https://github.com/openai/fence/blob/e6b39c80c51cb2b2a39448ddeff74b3b886c0a63/src/local_control.rs), this error means the local observation or scan is unavailable, or the unavailable-input list is nonempty. The raw job lacks the detailed cause. A particular unreadable process/socket input, unknown owner or runner identity mismatch is **not established**.

## Supported investigation candidate

Official [PR #180](https://github.com/openai/fence/pull/180) added bounded retries for incomplete service inspection and safer diagnostics while retaining the complete/stable inventory requirement. The published [v0.13.0 release](https://github.com/openai/fence/releases/tag/v0.13.0), dated 2026-11-09, identifies complete Action pin `c7675fea986c29f1d655753a7a61fd6b4141be8f`.

Its [official troubleshooting documentation](https://github.com/openai/fence/blob/c7675fea986c29f1d655753a7a61fd6b4141be8f/docs/troubleshooting.md) describes bounded read retries, restricted missing-owner retries and fixed diagnostic fields. It still refuses incomplete inspection in audit mode. Changing a network allowlist does not address this failure.

That pin is a candidate for a separately reviewed compatibility/diagnostic update. It is **not a demonstrated repair of this job**. An affected-runner execution and its readiness/post-job evidence would be needed. No workflow, policy, approval, secret or security control was changed during this diagnosis, and no CI job was rerun. Both native code proposals remain narrowly scoped.
