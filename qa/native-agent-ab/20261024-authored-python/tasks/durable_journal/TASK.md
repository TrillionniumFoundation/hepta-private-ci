Repair the library in repair_target.py to meet the specification below.
Keep the public names and call signatures. Use only Python 3.12's standard
library. Do not access the network, install dependencies, read outside this
workspace, or emit stdout/stderr from library calls. You may create your own
checks in the workspace; the submitted artifact is repair_target.py. Do not
change TASK.md. All evaluation inputs are bounded small in-memory values or
files in a temporary directory provided to the library. No production service
or external repository is involved. Explain the change and any checks you ran.

read_journal(path) returns all committed records from a byte-oriented JSONL
journal, in order. A record is committed only when terminated by byte LF.
Ignore an unterminated tail completely, even if it is valid JSON, malformed
JSON, or incomplete UTF-8. Do not modify the file.

Every complete line must decode as strict UTF-8 and contain one JSON object
with exactly "seq" and "value". seq must be integer (not bool), starting at 1
and increasing by exactly 1. Blank complete lines, invalid JSON/UTF-8, wrong
schema, gaps, duplicates, or an out-of-order seq raise ValueError; never skip
committed corruption. value can be any JSON value. The empty file returns [].
Only the supplied file is read; all files are bounded and local fixtures.
