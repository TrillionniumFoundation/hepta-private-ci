Repair the library in repair_target.py to meet the specification below.
Keep the public names and call signatures. Use only Python 3.12's standard
library. Do not access the network, install dependencies, read outside this
workspace, or emit stdout/stderr from library calls. You may create your own
checks in the workspace; the submitted artifact is repair_target.py. Do not
change TASK.md. All evaluation inputs are bounded small in-memory values or
files in a temporary directory provided to the library. No production service
or external repository is involved. Explain the change and any checks you ran.

Utf8Lines() accepts a stream of UTF-8 bytes. feed(chunk: bytes) returns complete
text records terminated by LF. A CR immediately preceding that LF is part of
the line ending and is removed; other CR and all spaces/tabs are preserved.
Return an empty string for an empty terminated line. Arbitrary byte boundaries,
including inside a multibyte UTF-8 character or between CR and LF, are valid.

finish() validates any remaining UTF-8 sequence and returns the final
unterminated record if nonempty, otherwise []. A trailing CR on an unterminated
record is data. Invalid UTF-8 raises UnicodeError (including incomplete UTF-8
at finish). Calls to either method after a successful finish raise ValueError.
