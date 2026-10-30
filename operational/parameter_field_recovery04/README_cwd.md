# Execution04: working-directory isolation

The original scientific and operational modules remain byte-identical to the
recovered public source. The wrapper addresses an observed pre-main failure:
Torch generated-module pseudo filenames such as `_ops.py` were resolved inside
the repository when that repository was also the current directory. The original
loaded-source check then attempted to hash a nonexistent repository file.

`cwd_runner.py` requires a hash-bound policy, the registered virtual-environment
interpreter and an empty working directory outside the source tree. It delegates
controller execution to the original `controller_envelope_v2`, intercepting only
its known worker-spawn site. Scientific module names and arguments are retained;
the child receives the pinned source root through `PYTHONPATH`. Existing other
environment values, resource admission, worker registration, source checks,
guards, labels, statistical rules and original controller logic remain intact.
The wrapper never changes sandbox or network-policy variables.

Analysis parent and child execution use the same directory policy. The analysis
child enters the explicitly registered historical-cost adapter before delegating
to the original analysis child. This adapter is separately frozen and documented:
missing historical preflight originals cannot be represented as real complete
receipts. Scientific scoring, statistical calculations and completion checks
remain those of the original source.

Each Popen attempt has a request record; successful launches also have a started record, including
the exact requested/effective argument arrays and observed process identity when
available. If the started record cannot be written, the wrapper terminates and
waits for only the child it just created before raising; it does not lose that
process handle. Environment values are not written to these records. The scoped
subprocess reference and original `sys.argv` are restored with `finally`.

Five synthetic behavior checks cover unchanged scientific arguments and retained
unrelated environment entries, analysis-child routing, rejection before spawning
from a dirty or unexpected directory, restoration after an exception, and child
cleanup when its started receipt fails. They
passed on 2026-10-29 America/New_York. They do not replace the required real
source-import and resource admission checks in the new runtime.

The workflow is explicitly Linux-specific: its existing resource contract uses
cgroup v2, `/proc`, POSIX process groups and file locks.
