# Preserve explicit subcommand cancellation in the canonical completion

The existing Unix execve approval path clears its pending receiver when the user
cancels the active turn. That receiver also resolves to `Abort` after an unrelated
interrupt or a dropped sender. A later parent execution completion previously
classified only its exit status, so an explicit subcommand Cancel could appear as
`Failed` in the canonical command item despite the existing integration assertion
requiring `Declined`.

This change gives each prepared zsh execution a private cancellation carrier.
Only the current still-open pending approval entry, keyed by its exact approval
ID and bound to the matching parent execution, can mark it. A supplied request
turn must match the stored approval turn; an omitted turn retains the existing
compatibility path and still requires that exact live entry and parent carrier.
The explicit
`Op::ExecApproval` Abort handler records that cause before its existing interrupt.
Receiver cleanup, hook decisions, guardian decisions, ordinary process failure,
and unrelated turn interruption do not set the marker. Each new execution owns a
distinct carrier even when a caller reuses the same call ID.

The existing immediate and background completion paths carry the same object to
their existing canonical emitter. A matching explicit cancellation changes only
`CommandExecutionStatus` to `Declined`; the original output, exit code, duration,
process identity, and command metadata remain intact. Terminal classification is
linearized before emission. A later Abort cannot rewrite it. Classification is
not an event-delivery flag and never skips an emitter call.

App-server preserves its existing suppression of a subcommand's synthetic parent
completion. The started-parent check and removal decision now share one existing
lock, so a parent cannot start between those observations. Ordinary command and
guardian completion paths retain their existing behavior.

The existing completion ownership is unchanged. Under normal handoff there is
one immediate owner or one stored-process watcher. In the pinned implementation,
pruned-entry removal uses a synchronous mutex and has no internal suspension
point. Its `.await` alone does not establish a post-insertion cancellation gap.
This change does not modify completion custody or claim delivery under every
interruption.

The original zsh integration regression and its assertions, budgets, and approval
sequence are unchanged. New controls cover exact pending identity, closed and
removed receivers, ordinary approval cleanup, reused call IDs, later-turn
requests, completion-before-Abort, and unchanged whole completion payloads. An
app-server control preserves the parent's pending completion after a subcommand
decision. These Rust controls are authored but have not been executed in this
source-only review; the next normal CI run remains the behavioral gate. No
dependencies, locks, workflow budgets, retries, sandbox permissions, or terminal
event send sites are added.
