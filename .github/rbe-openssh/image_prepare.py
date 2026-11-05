#!/usr/bin/python3
"""Reviewed image-only OpenSSH addition; never a host/package installer."""

import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = Path("/usr/local/share/hepta-rbe-openssh")
SCRIPT = Path("/usr/local/lib/hepta-rbe-openssh/image_prepare.py")
TOOLS = (
    "/usr/bin/curl",
    "/usr/bin/git",
    "/usr/bin/python3",
    "/usr/local/bin/dotslash",
    "/bin/sh",
    "/usr/bin/env",
    "/usr/bin/ldd",
)
FIXED_FILES = ("/etc/passwd", "/etc/group", "/etc/ssl/certs/ca-certificates.crt")
LOGS = []
DEADLINE = 0.0


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def remaining():
    value = DEADLINE - time.monotonic()
    require(value > 0, "image preparation deadline exhausted")
    return value


def command(argv, *, data=None, success=True):
    environment = os.environ.copy()
    environment.update(LC_ALL="C", LANG="C", DEBIAN_FRONTEND="noninteractive")
    entry = {"argv": argv, "status": "requested"}
    LOGS.append(entry)
    try:
        result = subprocess.run(
            argv, input=data, capture_output=True, env=environment, timeout=remaining()
        )
    except subprocess.TimeoutExpired as error:
        entry.update(
            {
                "status": "timed-out",
                "exit_code": None,
                "timed_out": True,
                "capture_complete": False,
                "stdout_base64": base64.b64encode(error.stdout or b"").decode("ascii"),
                "stderr_base64": base64.b64encode(error.stderr or b"").decode("ascii"),
            }
        )
        raise
    except BaseException as error:
        entry.update(
            {
                "status": "invocation-failed",
                "exception": str(error),
                "capture_complete": False,
            }
        )
        raise
    entry.update(
        {
            "status": "completed",
            "exit_code": result.returncode,
            "capture_complete": True,
            "stdout": result.stdout.decode("utf-8", "replace"),
            "stderr": result.stderr.decode("utf-8", "replace"),
            "stdout_base64": base64.b64encode(result.stdout).decode("ascii"),
            "stderr_base64": base64.b64encode(result.stderr).decode("ascii"),
        }
    )
    if success:
        require(
            result.returncode == 0,
            "command failed: "
            + argv[0]
            + " exit="
            + str(result.returncode)
            + " stderr="
            + result.stderr.decode("utf-8", "replace")[-2000:],
        )
    return result


def snapshot(name):
    path = Path(name)
    resolved = path.resolve(strict=True)
    metadata = resolved.stat()
    require(
        resolved.is_absolute() and stat.S_ISREG(metadata.st_mode),
        "required input is not an absolute regular file: " + name,
    )
    raw = resolved.read_bytes()
    return {
        "logical": name,
        "resolved": str(resolved),
        "bytes": len(raw),
        "sha256": digest(raw),
        "uid": metadata.st_uid,
        "gid": metadata.st_gid,
        "mode": stat.S_IMODE(metadata.st_mode),
    }


def critical_files():
    names = set(TOOLS + FIXED_FILES)
    for name in TOOLS:
        with open(name, "rb") as handle:
            elf = handle.read(4) == b"\x7fELF"
        if not elf:
            continue
        result = command(["/usr/bin/ldd", name], success=False)
        text = (result.stdout + result.stderr).decode("utf-8", "replace")
        require("not found" not in text, "baseline dynamic dependency is missing")
        require(
            result.returncode == 0
            or text.strip() in ("not a dynamic executable", "statically linked"),
            "baseline dependency inspection failed",
        )
        for match in re.finditer(r"(?:=>\s+|^\s*)(/[^\s]+)\s+\(", text, re.M):
            names.add(match.group(1))
    return [snapshot(name) for name in sorted(names)]


def packages():
    fields = ("binary:Package", "Version", "Architecture", "db:Status-Abbrev")
    output_format = (
        "-f=" + "\t".join(chr(36) + "{" + field + "}" for field in fields) + "\n"
    )
    result = command(["/usr/bin/dpkg-query", "-W", output_format])
    values = {}
    for line in result.stdout.decode().splitlines():
        name, version, arch, status = line.split("\t")
        if status.strip() == "ii":
            key = name.split(":", 1)[0] + ":" + arch
            require(key not in values, "duplicate installed package")
            values[key] = version
    require(values, "empty installed package inventory")
    return values


def write_json(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    with path.open("xb") as handle:
        os.fchmod(handle.fileno(), 0o644)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def identity():
    require(Path(__file__).resolve() == SCRIPT, "image-only installation path required")
    require(Path.cwd() == Path("/workspace"), "original image workdir required")
    release = dict(
        line.split("=", 1)
        for line in Path("/etc/os-release").read_text().splitlines()
        if "=" in line
    )
    require(
        release.get("ID") == "ubuntu"
        and release.get("VERSION_ID", "").strip('"') == "24.04",
        "original Ubuntu 24.04 userland required",
    )
    arch = command(["/usr/bin/dpkg", "--print-architecture"]).stdout.decode().strip()
    require(arch in ("amd64", "arm64"), "unexpected original image architecture")
    user = pwd.getpwnam("ubuntu")
    require(
        user.pw_uid == 1000 and user.pw_gid == 1000, "original ubuntu identity changed"
    )
    return arch, user


def install():
    global DEADLINE
    DEADLINE = time.monotonic() + 900
    require(os.geteuid() == 0, "image installation requires the Dockerfile root stage")
    arch, user = identity()
    require(
        not Path("/usr/bin/ssh-keygen").exists(),
        "base image already has ssh-keygen; reconcile the missing-tool diagnosis",
    )
    ROOT.mkdir(mode=0o755, parents=True, exist_ok=False)
    before_packages = packages()
    before_files = critical_files()
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
        keep = ROOT / "debs"
        keep.mkdir(mode=0o755)
        for path in sorted(archive.glob("*.deb")):
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
                    "sha256": digest(raw),
                    "file": path.name,
                }
            )
        require(
            any(item["package"] == "openssh-client:" + arch for item in debs),
            "OpenSSH candidate archive was not retained",
        )
        command(
            apt
            + cache
            + [
                "--yes",
                "--no-download",
                "--no-remove",
                "--no-install-recommends",
                "install",
                package_spec,
            ]
        )
    after_packages = packages()
    require(
        all(after_packages.get(key) == value for key, value in before_packages.items()),
        "a previously installed package was removed or changed",
    )
    after_files = critical_files()
    if after_files != before_files:
        print(
            json.dumps(
                {
                    "schema": "hepta.rbe-openssh-image.critical-difference.v1",
                    "before_critical_files": before_files,
                    "after_critical_files": after_files,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
    require(
        after_files == before_files,
        "a baseline tool, dependency, owner or mode changed",
    )
    require(identity() == (arch, user), "original image identity changed")
    signed_metadata = [
        snapshot(str(path))
        for path in sorted(Path("/var/lib/apt/lists").glob("*InRelease"))
    ]
    require(signed_metadata, "signed APT release metadata missing")
    executable = snapshot("/usr/bin/ssh-keygen")
    require(
        executable["uid"] == 0 and executable["mode"] & 0o022 == 0,
        "OpenSSH executable is not root owned and protected",
    )
    remaining()
    write_json(
        ROOT / "install.json",
        {
            "schema": "hepta.rbe-openssh-image.install.v1",
            "status": "installed-not-original-tests-qualified",
            "architecture": arch,
            "uid": user.pw_uid,
            "gid": user.pw_gid,
            "before_packages": before_packages,
            "after_packages": after_packages,
            "added_packages": {
                key: value
                for key, value in after_packages.items()
                if key not in before_packages
            },
            "before_critical_files": before_files,
            "after_critical_files": after_files,
            "openssh_executable": executable,
            "retained_debs": debs,
            "apt_signed_release_metadata": signed_metadata,
            "commands": LOGS,
        },
    )


def qualify():
    global DEADLINE
    DEADLINE = time.monotonic() + 120
    arch, user = identity()
    require(
        os.geteuid() == user.pw_uid and os.getegid() == user.pw_gid,
        "tool smoke test must use original nonroot image identity",
    )
    installed = json.loads((ROOT / "install.json").read_text())
    require(installed["architecture"] == arch, "installed image architecture mismatch")
    require(
        critical_files() == installed["after_critical_files"], "baseline tools changed"
    )
    require(
        snapshot("/usr/bin/ssh-keygen") == installed["openssh_executable"],
        "OpenSSH executable identity changed",
    )
    executable = "/usr/bin/ssh-keygen"
    cases = []
    with tempfile.TemporaryDirectory(prefix="hepta-rbe-sshsig-") as directory:
        temporary = Path(directory)
        key = temporary / "key"
        command([executable, "-q", "-t", "ed25519", "-N", "", "-f", str(key)])
        allowed = temporary / "allowed_signers"
        allowed.write_text("fixture " + key.with_suffix(".pub").read_text())
        message = bytes((index % 251 for index in range(8213)))
        for algorithm in ("sha256", "sha512"):
            message_path = temporary / ("message-" + algorithm)
            message_path.write_bytes(message)
            command(
                [
                    executable,
                    "-Y",
                    "sign",
                    "-f",
                    str(key),
                    "-n",
                    "hepta-rbe-tool-smoke",
                    "-O",
                    "hashalg=" + algorithm,
                    str(message_path),
                ]
            )
            signature = str(message_path) + ".sig"
            base = [
                executable,
                "-Y",
                "verify",
                "-f",
                str(allowed),
                "-I",
                "fixture",
                "-s",
                signature,
                "-n",
            ]
            for namespace, data, expected in (
                ("hepta-rbe-tool-smoke", message, True),
                ("wrong-namespace", message, False),
                ("hepta-rbe-tool-smoke", message + b"x", False),
            ):
                result = command(base + [namespace], data=data, success=False)
                require(
                    (result.returncode == 0) == expected,
                    "real SSHSIG smoke case failed",
                )
                cases.append(
                    {
                        "hash_algorithm": algorithm,
                        "namespace": namespace,
                        "message_sha256": digest(data),
                        "accepted": expected,
                        "actual_exit_code": result.returncode,
                    }
                )
    remaining()
    write_json(
        Path("/tmp/hepta-rbe-openssh-tool-test.json"),
        {
            "schema": "hepta.rbe-openssh-image.tool-smoke.v1",
            "status": "tool-smoke-only-not-original-operator-tests",
            "architecture": arch,
            "uid": os.geteuid(),
            "gid": os.getegid(),
            "executable": snapshot(executable),
            "cases": cases,
            "commands": LOGS,
        },
    )


if __name__ == "__main__":
    try:
        require(
            sys.argv[1:] in (["install"], ["qualify"]), "expected install or qualify"
        )
        (install if sys.argv[1] == "install" else qualify)()
    except BaseException as error:
        # A failed Docker RUN layer cannot be extracted. Retain all completed
        # command bytes in the build log, plus explicitly partial timeout bytes.
        # This image-only process has no registry token or caller credentials.
        print(
            json.dumps(
                {
                    "schema": "hepta.rbe-openssh-image.failure.v1",
                    "status": "failed-not-qualified",
                    "exception_type": type(error).__name__,
                    "exception": str(error),
                    "traceback": traceback.format_exc(),
                    "commands": LOGS,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        raise
