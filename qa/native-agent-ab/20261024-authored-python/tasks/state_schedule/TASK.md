Repair the library in repair_target.py to meet the specification below.
Keep the public names and call signatures. Use only Python 3.12's standard
library. Do not access the network, install dependencies, read outside this
workspace, or emit stdout/stderr from library calls. You may create your own
checks in the workspace; the submitted artifact is repair_target.py. Do not
change TASK.md. All evaluation inputs are bounded small in-memory values or
files in a temporary directory provided to the library. No production service
or external repository is involved. Explain the change and any checks you ran.

ScheduleQueue has schedule(key, value, deadline), cancel(key), and pop_due(now).
Keys are nonempty strings; deadlines and now are nonnegative integers. Calls
in this task use valid argument types. There is at most one live event per key.
Scheduling an existing key replaces it and creates a fresh insertion order.
cancel returns True only if a live event was removed. pop_due returns a list
of (key, value) tuples for all current events with deadline <= now, ordered by
deadline then the insertion order of their latest schedule call. Remove each
returned event. Stale heap entries from replacement or cancellation must never
fire or remove a newer event. Payload values may be any JSON value.
