# Guardian network fixture request routing

Two existing network approval cases used a single ordered response queue for
both the parent agent and Guardian. The original exec request yields after one
second, so a parent request containing a still-running session can arrive before
Guardian's request. These are separate clients; their arrival order cannot
identify which response belongs to which client.

The retained routing failure contains a parent request with both original
commands still running, followed by HTTP 404. It reports three captured Guardian
actions where two were expected. Three retained attempts of the single-trigger
case report no captured action; those sections contain no full HTTP trace, so
their exact request order remains unobserved.

The fixture now matches Guardian by its identity and original call ID. Parent
follow-ups examine only the current command's latest output. A real running
header produces a normal write_stdin call using the original session ID, empty
input, and the existing one-second yield. There are at most nine polls. A new
user prompt ends the previous command's matching scope. One shared request log
retains the existing request invariant checks without recording rejected routes.

The next normal source build exposed an incorrect completion assumption: a
Guardian rejection is terminal without a process-exit header. The routing case
returned the intended ProcessFailed rejection, but the fixture rejected it as an
unknown dispatch error. This failure remains part of the qualification record.

Completion now requires the outcome declared by that specific test: a typed
process-exit header before Output: for approval, or the exact Guardian rejection
prefix and expected rationale for denial. exec_command's Debug envelope and
write_stdin's Display envelope are distinguished by the original or poll call ID.
Wrong rationales, wrong envelopes, unrelated calls, malformed or out-of-range
poll IDs, ordinary dispatch errors, and status-like lines in stdout cannot count
as the required denial. A successful process exit cannot satisfy a denial case.
Each turn must still leave no background terminal. Original action-count, full
action, exact trigger, command, and denial assertions remain in force. Command
arguments, network deadlines, approval policy, the nine-poll bound, and
production code are unchanged.

This is a source correction, not a successful native qualification. The two
original cases, the terminal-output parser controls, and the surrounding network
approval suite remain required on the normal source build. No failed CI attempt
is rerun to produce this evidence.
