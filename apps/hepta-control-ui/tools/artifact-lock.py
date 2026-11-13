"""POSIX kernel-owned build lock; inherited descriptors keep compiler children fenced."""

import os
import sys
import stat

if os.name != "posix":
    raise SystemExit("Owned UI builds/previews currently require POSIX flock")
import fcntl

if sys.argv[1] == "--shared":
    fcntl.flock(3, fcntl.LOCK_SH)
    raise SystemExit(0)
root, *command = sys.argv[1:]
path = os.path.join(root, ".robrix-artifact.lock")
fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
if not stat.S_ISREG(os.fstat(fd).st_mode):
    raise SystemExit("Artifact lock must be a regular file")
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit("Another build/startup owns the artifact; retry after it exits")
if fd != 3:
    os.dup2(fd, 3, inheritable=True)
    os.close(fd)
else:
    os.set_inheritable(3, True)
os.environ["HEPTA_ARTIFACT_LOCK_ROOT"] = os.path.realpath(root)
os.execvp(command[0], command)
