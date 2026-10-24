Repair the library in repair_target.py to meet the specification below.
Keep the public names and call signatures. Use only Python 3.12's standard
library. Do not access the network, install dependencies, read outside this
workspace, or emit stdout/stderr from library calls. You may create your own
checks in the workspace; the submitted artifact is repair_target.py. Do not
change TASK.md. All evaluation inputs are bounded small in-memory values or
files in a temporary directory provided to the library. No production service
or external repository is involved. Explain the change and any checks you ran.

WindowLimiter(capacity, window) has allow(key, now) -> bool. capacity and window
must be positive integers (bool is not an integer for this API), otherwise the
constructor raises ValueError. key is a nonempty string, now a nonnegative
integer; allow calls in this task use those valid types. The time supplied
across all keys of an instance must never decrease; a decrease raises
ValueError without changing its state.

At time now, admit iff fewer than capacity previously admitted calls for this
key lie in (now - window, now]. Calls exactly window old have expired. A denied
call must not consume capacity or delay later admission. Keys are independent,
apart from the single nondecreasing supplied clock. Do not read the wall clock.
