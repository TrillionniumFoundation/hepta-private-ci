Repair the library in repair_target.py to meet the specification below.
Keep the public names and call signatures. Use only Python 3.12's standard
library. Do not access the network, install dependencies, read outside this
workspace, or emit stdout/stderr from library calls. You may create your own
checks in the workspace; the submitted artifact is repair_target.py. Do not
change TASK.md. All evaluation inputs are bounded small in-memory values or
files in a temporary directory provided to the library. No production service
or external repository is involved. Explain the change and any checks you ran.

The module exports the unique sentinel DELETE and merge(base: dict,
override: dict) -> dict. Recursively merge dictionaries. Any override value
equal by identity to DELETE removes that key, even if it was absent. Other
values, including None, False, 0, empty strings, and empty lists, are ordinary
values and replace the old value. Lists replace rather than concatenate.
When an override dictionary replaces a non-dictionary, treat the old value as
an empty dictionary so nested DELETE entries still disappear.

Never mutate either input. The returned dictionary, including all nested
dictionaries and lists, must share no mutable container with either input.
Inputs contain JSON-like dict/list/scalar values with string keys. DELETE may
occur only as a dictionary value within override, never inside a list or base.
The grader may mutate the returned result after merge and verify the inputs
are unchanged.
