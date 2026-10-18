"""Physical observations of the two existing systemd roles, without secrets."""

import os
from pathlib import Path
import stat


def observe(raw, service, program, expected_args, uid, gid, capabilities):
    fields = dict(line.split("=", 1) for line in raw.decode().splitlines())
    cgroup = f"/system.slice/{service}"
    if (
        fields["User"],
        fields["Group"],
        fields["ControlGroup"],
        fields["ActiveState"],
    ) != ("root" if uid == 0 else str(uid), str(gid), cgroup, "active"):
        raise ValueError("service is not the enrolled active unit")
    pid = int(fields["MainPID"])
    if pid <= 0:
        raise ValueError("service has no physical process")
    process = Path(f"/proc/{pid}")
    before = process.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19]
    status = dict(
        line.split(":", 1)
        for line in process.joinpath("status").read_text().splitlines()
    )
    if (
        status["Uid"].split() != [str(uid)] * 4
        or status["Gid"].split() != [str(gid)] * 4
        or status["NoNewPrivs"].strip() != "1"
    ):
        raise ValueError("service kernel principal/confinement changed")
    if any(
        int(status[name], 16) != capabilities
        for name in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
    ):
        raise ValueError("service kernel capabilities differ")
    if process.joinpath("cgroup").read_text().strip() != f"0::{cgroup}":
        raise ValueError("service kernel cgroup changed")
    expected = os.stat(program, follow_symlinks=False)
    actual = process.joinpath("exe").stat()
    if (
        not stat.S_ISREG(expected.st_mode)
        or expected.st_uid != 0
        or expected.st_mode & 0o222
        or (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino)
    ):
        raise ValueError("service is not the pinned immutable program")
    args = process.joinpath("cmdline").read_bytes().rstrip(b"\0").split(b"\0")
    if args != [arg.encode() for arg in expected_args]:
        raise ValueError("service command differs from the fixed deployment")
    if process.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19] != before:
        raise ValueError("service process incarnation changed")
    return {
        "pid": pid,
        "start_ticks": int(before),
        "dropins": fields["DropInPaths"],
        "program": str(program),
        "uid": uid,
        "gid": gid,
        "capabilities": capabilities,
    }
