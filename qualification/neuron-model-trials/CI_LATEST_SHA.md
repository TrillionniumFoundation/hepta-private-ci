# Latest-SHA scheduling for Neuron diagnostic CI

Hepta's experimental PR spans six independent Python/Rust diagnostic lanes.
Rapid source commits previously queued redundant heavy Cargo builds for old
SHAs, starving the final PR revision of runner capacity.

Each of these six workflows now uses workflow-level concurrency keyed by
workflow name and PR number. A new pull_request commit cancels **only** an older
run of that same workflow for that same PR. Separate gates and separate PRs
never cancel one another. workflow_dispatch retains manual runs without
automatic cancellation. The operator-triggered physical Laya smoke and
matched CPU benchmark workflows are deliberately unchanged.

No test, Cargo check, Clippy, code coverage or selection permission is
weakened by this change. Cancelled historical runs do not count toward
acceptance. The exact final SHA must finish every required CI check with
success. Global blocking-ci and v8-canary remain independently required.

The new source regression test is
.github/scripts/test_hepta_neuron_ci_latest_sha.py. It validates the
workflow-level rule, its PR-only scope and the absence of cancellation on
the physical measurement workflows. It cannot certify the GitHub platform
scheduler or an actual production deployment. All Neuron experiments stay
shadow-only and DENY_ALL.
