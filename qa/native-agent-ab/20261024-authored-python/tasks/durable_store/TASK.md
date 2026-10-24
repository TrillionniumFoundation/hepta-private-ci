Repair the library in repair_target.py to meet the specification below.
Keep the public names and call signatures. Use only Python 3.12's standard
library. Do not access the network, install dependencies, read outside this
workspace, or emit stdout/stderr from library calls. You may create your own
checks in the workspace; the submitted artifact is repair_target.py. Do not
change TASK.md. All evaluation inputs are bounded small in-memory values or
files in a temporary directory provided to the library. No production service
or external repository is involved. Explain the change and any checks you ran.

JsonStore(path) stores a JSON object with exactly "revision" and "value" fields.
The parent directory already exists. load() returns (0, None) when the file
does not exist, otherwise (revision, value). A stored revision must be a
positive integer, not bool; malformed JSON or schema raises ValueError.

commit(value, expected_revision) performs a single-process compare-and-swap:
load the current record, raise ConflictError on a mismatch without changing
any bytes, otherwise atomically replace the file with revision+1 and the given
JSON value and return the new revision. Use a same-directory temporary file
and os.replace. If serialization, writing, or os.replace fails, preserve the
old committed file and remove the temporary file. The grader injects an
OSError at os.replace to exercise this documented failure boundary. It does
not test concurrent writers, power-loss durability, symlink attacks, or
outside-directory access. Only this path and its same-directory temporary
files may be touched. Preserve the public ConflictError exception class.
