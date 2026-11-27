# Cancel completion fixture event fanout

This source candidate is based on Cancel B commit
`2bd2df402f8fd025ab9c78d77e29a8aef278867d`. It changes only the shared
`completion_item` test helper and this qualification note. Production cancellation,
event delivery, permissions, workflow settings, and time budgets are unchanged.

## Retained failure and fixed source

Normal Windows job `140334408347`, run `45947126959` attempt 1, failed the two new
controls `explicit_cancel_changes_only_the_canonical_status_for_real_exit_output`
and `explicit_cancel_preserves_the_existing_failed_completion_payload`. Each has
three original failed attempts in artifact `15175338868`. All six fail at the
helper's final `one completion per emitter call` assertion. They have already
received a canonical `ItemCompleted` containing a `CommandExecutionItem`; this is
not evidence of a missing completion. Each control fails during its first ordinary
completion, before its later cancelled comparison can run.

The fixed production source supplies the causal distinction. Both real emitter
functions await `ToolEmitter`, which awaits `emit_turn_item_completed`. That method
awaits `Session::send_event`: it first sends the canonical event, then converts the
same item to its compatibility events and awaits each send. A completed, failed,
or declined command maps to exactly one `ExecCommandEnd`. The test's session
helper returns the unfiltered event receiver. The six failure logs do not print
the second event's variant; its expected identity follows from this source chain,
not from a recorded runtime dump of that event.

## Narrow correction and controls

The helper now requires the next event to be exactly `ExecCommandEnd`. It compares
the full serialized legacy payload, both envelope turn IDs, the completion timestamp, and
all command payload fields. Known fixture values directly bind the call and
process IDs, command, stdout, failure message, exit code, duration, and expected
ordinary or cancelled status. Fields derived by the emitter are compared with
the canonical item. The expectation does not call the production legacy
conversion as its oracle.

After this exact second-event check, the original queue-empty assertion remains.
Missing or wrong event variants, wrong IDs or payload, another canonical event,
or any additional queued event still fail. There is no drain, filter, polling,
new wait, retry, or timeout. The two existing control bodies, both exit-code
cases, their complete ordinary/cancelled item equality checks, and the other six
approval identity and negative controls remain byte-for-byte unchanged.

Preparation runs only formatting, spelling, diff, source-inverse, and fixed-input
checks. No Rust compilation, native control, CI retry, or publication has occurred
for this candidate. The retained native failures remain failures until a later
reviewed source run supplies evidence. This fixture correction does not qualify
the Windows filesystem backend or close Cancel B's separate two deletion failures.
