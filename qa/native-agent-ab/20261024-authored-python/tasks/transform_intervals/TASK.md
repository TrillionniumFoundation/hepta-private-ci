Repair the library in repair_target.py to meet the specification below.
Keep the public names and call signatures. Use only Python 3.12's standard
library. Do not access the network, install dependencies, read outside this
workspace, or emit stdout/stderr from library calls. You may create your own
checks in the workspace; the submitted artifact is repair_target.py. Do not
change TASK.md. All evaluation inputs are bounded small in-memory values or
files in a temporary directory provided to the library. No production service
or external repository is involved. Explain the change and any checks you ran.

normalize(intervals) returns the union of half-open integer intervals [start,
end) as a sorted list of (start, end) tuples. Overlapping OR touching intervals
coalesce. Drop empty intervals where start == end. Reject start > end with
ValueError. Do not mutate the input list or any input pair. Accept any finite
iterable of two-item tuple/list pairs of valid integers; negative endpoints are
valid. The output must be canonical, nonempty per interval, and non-touching.
