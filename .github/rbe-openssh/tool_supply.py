#!/usr/bin/python3
"""Select one signed-package tool without installing packages or maintainer scripts."""

import base64
import hashlib
import io
import os
from pathlib import Path
import re
import resource
import stat
import struct
import subprocess
import tarfile
import tempfile

MAX_DEB = 8 * 1024 * 1024
MAX_TAR = 16 * 1024 * 1024
MAX_TOOL = 2 * 1024 * 1024
TOOL_MEMBER = "usr/bin/ssh-keygen"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def payload_limit():
    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    limit = min([MAX_TAR] + [x for x in (soft, hard) if x != resource.RLIM_INFINITY])
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))


def archive_payload(path, expected, remaining, logs):
    metadata = path.lstat()
    require(
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_nlink == 1
        and metadata.st_uid == metadata.st_gid == 0
        and stat.S_IMODE(metadata.st_mode) == 0o444
        and 0 < metadata.st_size <= MAX_DEB,
        "retained package must be one bounded protected regular file",
    )
    raw = path.read_bytes()
    require(
        len(raw) == expected["bytes"]
        and hashlib.sha256(raw).hexdigest() == expected["sha256"],
        "retained package bytes changed",
    )
    argv = ["/usr/bin/dpkg-deb", "--fsys-tarfile", str(path)]
    entry = {"argv": argv, "status": "requested", "binary_stdout": True}
    logs.append(entry)
    # Only dpkg-deb's data stream is read. No extract/install/configure operation.
    # A child-only file-size limit bounds decompression before Python reads bytes.
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(
                argv,
                stdout=output,
                stderr=subprocess.PIPE,
                timeout=remaining(),
                preexec_fn=payload_limit,
                env={**os.environ, "LC_ALL": "C", "LANG": "C"},
            )
        except BaseException as error:
            output.seek(0)
            partial = output.read(MAX_TAR + 1)
            entry.update(
                status="failed",
                capture_complete=False,
                exception=str(error),
                stdout_base64=base64.b64encode(partial).decode("ascii"),
                stderr_base64=base64.b64encode(
                    getattr(error, "stderr", None) or b""
                ).decode("ascii"),
            )
            raise
        output.seek(0)
        payload = output.read(MAX_TAR + 1)
    entry.update(
        status="completed",
        exit_code=result.returncode,
        capture_complete=True,
        stdout_base64=base64.b64encode(payload).decode("ascii"),
        stderr_base64=base64.b64encode(result.stderr).decode("ascii"),
    )
    require(result.returncode == 0, "bounded package data stream failed")
    require(0 < len(payload) <= MAX_TAR, "package data stream exceeds its bound")
    remaining()
    return payload


def select_tool(payload, architecture):
    require(
        0 < len(payload) <= MAX_TAR and len(payload) % 512 == 0,
        "package payload exceeds its bound or has a partial tar block",
    )
    found, names, data_end = None, set(), 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        for item in archive:
            require(
                not item.sparse and 0 <= item.size <= MAX_TAR,
                "unsupported or oversized package member",
            )
            data_end = item.offset_data + ((item.size + 511) // 512) * 512
            require(data_end <= len(payload), "package member data was truncated")
            require(
                not item.name.endswith("/") or item.isdir(),
                "nondirectory package member has a trailing separator",
            )
            name = item.name.removeprefix("./").rstrip("/")
            if item.name in (".", "./"):
                require(item.isdir(), "archive root must be a directory")
                name = "."
            else:
                require(
                    not name.startswith("/")
                    and all(part not in ("", ".", "..") for part in name.split("/")),
                    "noncanonical package member",
                )
            require(name not in names, "duplicate package member")
            names.add(name)
            require(len(names) <= 4096, "package contains too many members")
            if name == ".":
                continue
            if name in ("usr", "usr/bin"):
                require(item.isdir(), "package tool ancestor is not a directory")
            if name != TOOL_MEMBER:
                continue
            require(
                item.isreg()
                and not item.sparse
                and not item.linkname
                and item.uid == item.gid == 0
                and item.mode == 0o755
                and 0 < item.size <= MAX_TOOL,
                "tool must be one root-owned bounded regular executable",
            )
            found = archive.extractfile(item).read(MAX_TOOL + 1)
            require(len(found) == item.size, "tool member was truncated")
    # A standard tar ends with two zero blocks, followed only by zero padding.
    # Stopping at the first end block must not hide a second nonempty archive.
    require(
        len(payload) - data_end >= 1024 and not any(payload[data_end:]),
        "nonzero data or missing end blocks after the first tar archive",
    )
    require(found is not None, "package does not contain the required tool")
    require(
        len(found) >= 64
        and found[:7] == b"\x7fELF\x02\x01\x01"
        and found[7] in (0, 3)
        and struct.unpack_from("<H", found, 16)[0] in (2, 3)
        and struct.unpack_from("<H", found, 18)[0]
        == {"amd64": 62, "arm64": 183}.get(architecture)
        and struct.unpack_from("<I", found, 20)[0] == 1,
        "tool ELF does not match the original native architecture",
    )
    return found


def create_exclusive(path, raw, mode):
    require(
        path.is_absolute() and path.parent.resolve(strict=True) == path.parent,
        "destination parent is not an absolute canonical directory",
    )
    require(mode in (0o444, 0o500, 0o755), "unexpected new-file mode")
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        before = os.fstat(parent)
        require(
            before.st_uid == os.geteuid()
            and before.st_gid == os.getegid()
            and stat.S_IMODE(before.st_mode) & 0o022 == 0,
            "destination parent ownership or permissions changed",
        )
        fd = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        try:
            created = os.fstat(fd)
            require(
                stat.S_ISREG(created.st_mode) and created.st_nlink == 1,
                "new destination is not a unique regular file",
            )
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fchmod(fd, mode)
                os.fsync(fd)
            named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            require(
                (named.st_dev, named.st_ino) == (created.st_dev, created.st_ino)
                and named.st_nlink == 1
                and named.st_size == len(raw)
                and named.st_uid == os.geteuid()
                and named.st_gid == os.getegid()
                and stat.S_IMODE(named.st_mode) == mode,
                "exclusive new-file identity changed",
            )
            current_parent = path.parent.stat()
            require(
                (current_parent.st_dev, current_parent.st_ino)
                == (before.st_dev, before.st_ino),
                "destination parent was replaced",
            )
            os.fsync(parent)
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def dependency_files(path, command, snapshot):
    result = command(["/usr/bin/ldd", str(path)], success=False)
    require(
        result.returncode == 0 and not result.stderr,
        "tool dynamic dependency inspection failed",
    )
    names = set()
    for line in result.stdout.decode("utf-8").splitlines():
        if re.fullmatch(r"\s*linux-vdso\.so\.\d+\s+\(0x[0-9a-f]+\)\s*", line):
            continue
        match = re.fullmatch(
            r"\s*(?:[^\s]+\s+=>\s+)?(/[^\s]+)\s+\(0x[0-9a-f]+\)\s*", line
        )
        require(match is not None, "unresolved or unexpected tool dependency")
        require(match[1] not in names, "duplicate tool dependency")
        names.add(match[1])
    require(names, "tool has no verified original dynamic dependency closure")
    files = [snapshot(name) for name in sorted(names)]
    require(
        all(x["uid"] == x["gid"] == 0 and x["mode"] & 0o022 == 0 for x in files),
        "tool dependency is not root-owned and protected",
    )
    return files


def supply_tool(root, arch, before_packages, command, snapshot, remaining, logs):
    apt = [
        "/usr/bin/apt-get",
        "-o",
        "APT::Get::AllowUnauthenticated=false",
        "-o",
        "Acquire::AllowInsecureRepositories=false",
        "-o",
        "Acquire::AllowDowngradeToInsecureRepositories=false",
        "-o",
        "APT::Update::Error-Mode=any",
    ]
    command(apt + ["update"])
    policy = command(["/usr/bin/apt-cache", "policy", "openssh-client"]).stdout.decode()
    candidates = re.findall(r"^\s*Candidate:\s+(\S+)\s*$", policy, re.M)
    require(
        len(candidates) == 1 and candidates[0] != "(none)",
        "missing signed package candidate",
    )
    package_spec = "openssh-client=" + candidates[0]
    simulation = command(
        apt
        + [
            "--simulate",
            "--no-remove",
            "--no-install-recommends",
            "install",
            package_spec,
        ]
    ).stdout.decode()
    require(
        not re.search(r"^(?:Remv|Purg) ", simulation, re.M), "package removal requested"
    )
    debs = []
    with tempfile.TemporaryDirectory(prefix="hepta-rbe-openssh-apt-") as directory:
        archive = Path(directory)
        archive.chmod(0o755)
        cache = ["-o", "Dir::Cache::archives=" + str(archive)]
        command(
            apt
            + cache
            + [
                "--yes",
                "--download-only",
                "--no-remove",
                "--no-install-recommends",
                "install",
                package_spec,
            ]
        )
        keep = root / "debs"
        keep.mkdir(mode=0o755)
        paths = sorted(archive.glob("*.deb"))
        require(0 < len(paths) <= 32, "downloaded package count exceeds its bound")
        for path in paths:
            metadata = path.lstat()
            require(
                stat.S_ISREG(metadata.st_mode)
                and metadata.st_nlink == 1
                and 0 < metadata.st_size <= MAX_DEB,
                "downloaded package is nonregular, linked, or oversized",
            )
            raw = path.read_bytes()
            control = command(
                ["/usr/bin/dpkg-deb", "--field", str(path)]
            ).stdout.decode()
            fields = dict(
                line.split(": ", 1)
                for line in control.splitlines()
                if line and not line[0].isspace() and ": " in line
            )
            name, version, package_arch = (
                fields[k] for k in ("Package", "Version", "Architecture")
            )
            require(package_arch in (arch, "all"), "cross-architecture dependency")
            key = name + ":" + package_arch
            require(
                key not in before_packages or before_packages[key] == version,
                "existing installed package would change: " + key,
            )
            destination = keep / path.name
            with destination.open("xb") as handle:
                handle.write(raw)
            destination.chmod(0o444)
            debs.append(
                {
                    "package": key,
                    "version": version,
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "file": path.name,
                }
            )
        require(
            any(item["package"] == "openssh-client:" + arch for item in debs),
            "OpenSSH candidate archive was not retained",
        )
        candidates_kept = [
            item
            for item in debs
            if item["package"] == "openssh-client:" + arch
            and item["version"] == candidates[0]
        ]
        require(len(candidates_kept) == 1, "required package identity is not unique")
        selected = candidates_kept[0]
        payload = archive_payload(keep / selected["file"], selected, remaining, logs)
        tool = select_tool(payload, arch)
        staged = archive / "selected-ssh-keygen"
        create_exclusive(staged, tool, 0o500)
        before_dependencies = dependency_files(staged, command, snapshot)
        create_exclusive(Path("/usr/bin/ssh-keygen"), tool, 0o755)
        after_dependencies = dependency_files(
            Path("/usr/bin/ssh-keygen"), command, snapshot
        )
        require(
            after_dependencies == before_dependencies,
            "original tool dependencies changed",
        )
    return debs, selected, before_dependencies, after_dependencies, tool


def directory_identities():
    paths = (
        "/workspace",
        "/usr/bin",
        "/usr/local/share",
        "/usr/local/lib/hepta-rbe-openssh",
    )
    result = []
    for name in paths:
        path = Path(name)
        metadata = path.lstat()
        require(
            stat.S_ISDIR(metadata.st_mode) and path.resolve(strict=True) == path,
            "image directory is not canonical",
        )
        result.append(
            {
                "path": name,
                "uid": metadata.st_uid,
                "gid": metadata.st_gid,
                "mode": stat.S_IMODE(metadata.st_mode),
            }
        )
    return result
