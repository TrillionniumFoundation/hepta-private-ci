# Broader GitHub CI failures at the code freeze

## Observed status

These are separate GitHub Actions runs at Hepta `ee57cd57c322a8fecdf674a662c741452baf6478`, tree `ec40412aff2091fd05e0feaf31a46179f8afaa46`. The uploaded scoped-command receipts record clean, identical source before and after execution. Both workflows completed with **failure**. They are not a source or merge-lane pass, and their overlapping counts must not be added to one another or to the 170 local scoped passes.

| Workflow / original run | Five-package nextest result | Additional qualification result |
| --- | --- | --- |
| [Neural study, 42042507261](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42042507261) | **1,972 run / 1,967 passed / 4 failed / 1 timed out / 30 skipped**, exit 100 | Ordinary inference, Cell and positive study gates were skipped; the required-outcome gate exited 1. |
| [Public initial, 42042507211](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42042507211) | **1,972 run / 1,967 passed (one flaky) / 4 failed / 1 timed out / 30 skipped**, exit 100 | Material reconstruction raised `ValueError: public plan bytes differ`; the required-outcome gate exited 1 and product qualification remained false. |

The GitHub step metadata labels the five-package command step `success`, but the original command exited 100 and its retained receipt says failed. The workflow uses a continued execution path and an explicit final required-outcome gate; that gate correctly records `SCOPED_RUST=failure`. A step label does not supersede the original command, test log or final qualification result. The command receipt's five nonpassing tests comprise four failures and one timeout in nextest's more precise breakdown.

## Exact nonpassing cases

Both original logs contain the same five nonpassing test names:

| Test | Observed failure |
| --- | --- |
| `real_agentd_local_memory_review_hides_host_tombstone_after_reopen` | Agentd refuses startup with `kernel.evidence recovery_required`: the local evidence/replay/effect/invocation frontier does not match the signed checkpoint. |
| `real_agentd_local_memory_review_is_read_only_and_replayable` | Same checkpoint/frontier mismatch. |
| `killed_agent_recovers_same_turn_then_dispatches_queue_once_while_peer_stays_live` | Same checkpoint/frontier mismatch. |
| `ambient_python_injection_cannot_enter_supervisor_or_descendant` | The environment test unwraps `Err("neural Python loader overrides are not allowed")`. |
| `six_agent_fleet_lifecycle_keeps_peers_fair_and_isolated` | Both original attempts hit the existing approximately 60-second watchdog. |

The original logs, receipt hashes, artifact IDs, line numbers and final qualification outcomes are indexed in [CI-FAILURE-REVIEW.json](CI-FAILURE-REVIEW.json). Readable, bounded extracts are retained for [the neural run](native/github/42042507261-failure-excerpts.txt) and [the public run](native/github/42042507211-failure-excerpts.txt). Each extract is checked against the original log's SHA256 and line ordering, with only ANSI escapes removed for display.

## Scope and causal limit

This is a read-only review of those two actual runs. It did not rerun or cancel CI, change tests, increase the watchdog, or reset/checkpoint around the failing recovery assertions. No comparison execution at the base was performed. Consequently this evidence does **not** establish that these failures predate, or were caused by, the PQ change. The separate 49,508-versus-24,576-byte ordinary PoN blocker must not be inferred as their cause.

The two workflows also use their own recorded Chain source identities (`c16507147b65285ea94dead22d3b93c5db7295af` and `cfa57cd04751427451302b5c10539b3984d7f8db`). Those identities do not replace the `04be5f02` input of the separate local ordinary PQ → Chain test. Successful binary builds, skipped positive qualification steps and a passing subset of tests receive no full-path execution credit.

A [narrow source-intersection review](CI-FAILURE-SOURCE-INTERSECTION.json) records identical base/head Git blobs for twelve relevant files: the failing test sources, shared startup fixture, Evidence admission, configuration/runtime seams and Python environment helpers. The reviewed Agentd fixtures supply only Evidence recovery arguments, with no ordinary effect-host configuration; Python fails in its environment helper before launching the interpreter. Evidence admission also precedes the optional effect-host open. These observations narrow direct call-path overlap, but changes elsewhere remain compiled into Agentd and its dependencies. They do not exclude a composition regression or waive the actual failures, and the timeout's internal cause remains undetermined.

## Original CI log retention

This Git evidence directory retains the original scoped-command receipts, final outcome files, line-checked failure excerpts and complete original log/artifact SHA256 values. The full 18,965,216-byte neural log and 19,208,770-byte public log are referenced through their original Actions artifacts and retained in the local review files; their complete contents are not copied into this Git evidence directory. The original artifact retention is 14 days, with expiry on 2026-11-19 at 14:55:15Z and 14:57:39Z respectively. [Retention, original sizes and hashes](CI-LOG-RETENTION.json) and [the publication review](CI-LOG-PUBLICATION-REVIEW.json) record this exact boundary. Local compressed copies are lossless evidence-log copies, not modified test inputs. This retention boundary applies to these two broad CI logs; the scoped X230/ROG command logs are included in full.
