"""Strict source and observation inventory for one read-only namespace probe."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys

from hepta_core_selected_evidence import identity
from hepta_core_selected_evidence import read_regular
from hepta_core_selected_evidence import require

ROOT = Path(__file__).resolve().parents[2]
PARENT = "771cc150e2218c348753d6f8aa88057f07474091"
PARENT_TREE = "25bcead36b701f9e872f0c587cbcb719187d463a"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
INPUTS_REF = "research/ndu-bwrap-readonly-inputs-20261106"
INPUTS_HEAD = None
INPUTS_TREE = None
PROPOSAL_REF = "research/ndu-bwrap-readonly-probe-20261106"
ADDED = {
    ".github/scripts/hepta_bwrap_readonly_contract.py",
    ".github/scripts/hepta_bwrap_readonly.py",
    ".github/scripts/hepta_bwrap_readonly_evidence.py",
    ".github/workflows/hepta-bwrap-readonly-probe.yml",
}
INPUT_PATHS = {
    ".github/scripts/hepta_bwrap_readonly_contract.py",
    ".github/scripts/hepta_bwrap_readonly_evidence.py",
}
SCANNER_PATH = ".github/scripts/hepta_core_selected_evidence.py"
SCANNER_BLOB = "f18f5d0ce06cead0817513814da96f129523cf8c"
READS = {
    "os_release": "/etc/os-release",
    "apparmor_enabled": "/sys/module/apparmor/parameters/enabled",
    "restrict_userns": "/proc/sys/kernel/apparmor_restrict_unprivileged_userns",
    "userns_clone": "/proc/sys/kernel/unprivileged_userns_clone",
    "max_user_namespaces": "/proc/sys/user/max_user_namespaces",
    "profile_etc": "/etc/apparmor.d/bwrap-userns-restrict",
    "profile_bwrap": "/etc/apparmor.d/bwrap",
    "profile_usr_bin": "/etc/apparmor.d/usr.bin.bwrap",
    "profile_extra": "/usr/share/apparmor/extra-profiles/bwrap-userns-restrict",
    "local_bwrap": "/etc/apparmor.d/local/bwrap-userns-restrict",
    "local_unpriv": "/etc/apparmor.d/local/unpriv_bwrap",
    "observer_status": "/proc/self/status",
    "observer_label": "/proc/self/attr/current",
}
PACKAGES = [
    "bubblewrap",
    "libcap-dev",
    "libcap2",
    "libcap2-bin",
    "apparmor",
    "apparmor-profiles",
    "ubuntu-keyring",
]
COMMANDS = {
    "kernel": ["/usr/bin/uname", "-a"],
    "packages": [
        "/usr/bin/dpkg-query",
        "-W",
        "-f=${binary:Package}\\t${Version}\\n",
        *PACKAGES,
    ],
    "package_policy": ["/usr/bin/apt-cache", "policy", *PACKAGES],
    "bwrap_owner": ["/usr/bin/dpkg-query", "-S", "/usr/bin/bwrap"],
    "bwrap_version": ["/usr/bin/bwrap", "--version"],
    "bwrap_help": ["/usr/bin/bwrap", "--help"],
    "file_capabilities": ["/usr/sbin/getcap", "-n", "/usr/bin/bwrap"],
    "loaded_profiles": [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/cat",
        "/sys/kernel/security/apparmor/profiles",
    ],
    "apparmor_status": ["/usr/bin/sudo", "-n", "/usr/sbin/aa-status", "--json"],
    "system_python": ["/usr/bin/python3", "--version"],
}
CHILD = """import fcntl,json,os,socket,struct,sys
status=dict(line.split(":",1) for line in open("/proc/self/status") if ":" in line)
result={"effective_caps":int(status["CapEff"].strip(),16),"permitted_caps":int(status["CapPrm"].strip(),16),"no_new_privs":int(status["NoNewPrivs"].strip()),"netns":os.readlink("/proc/self/ns/net"),"userns":os.readlink("/proc/self/ns/user"),"apparmor_label":None,"label_errno":None,"loopback_address":None,"loopback_flags":None,"loopback_errno":None}
try:
    result["apparmor_label"]=open("/proc/self/attr/current").read()
except OSError as error:
    result["label_errno"]=error.errno
try:
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as handle:
        request=struct.pack("256s",b"lo")
        result["loopback_address"]=socket.inet_ntoa(fcntl.ioctl(handle,0x8915,request)[20:24])
        result["loopback_flags"]=struct.unpack("H",fcntl.ioctl(handle,0x8913,request)[16:18])[0]
except OSError as error:
    result["loopback_errno"]=error.errno
print(json.dumps(result,sort_keys=True),flush=True)
sys.exit(0 if result["effective_caps"]==result["permitted_caps"]==0 and result["loopback_address"]=="127.0.0.1" and isinstance(result["loopback_flags"],int) and result["loopback_flags"]&1 else 3)
"""
PROBE = [
    "/usr/bin/bwrap",
    "--as-pid-1",
    "--new-session",
    "--die-with-parent",
    "--ro-bind",
    "/",
    "/",
    "--dev",
    "/dev",
    "--unshare-user",
    "--unshare-pid",
    "--unshare-ipc",
    "--unshare-net",
    "--proc",
    "/proc",
    "--chdir",
    "/",
    "--cap-drop",
    "ALL",
    "--",
    "/usr/bin/python3",
    "-B",
    "-c",
    CHILD,
]
PHASES = ("before", "after")
COMMAND_IDS = {f"{phase}.{name}" for phase in PHASES for name in COMMANDS} | {
    "probe",
    "kernel_journal",
}
MANDATORY = (
    {"source-before.json", "source-after.json", "readiness.json", "result.json"}
    | {f"{phase}.process.json" for phase in PHASES}
    | {
        f"logs/{name}.{stream}.log"
        for name in COMMAND_IDS
        for stream in ("stdout", "stderr")
    }
)
READ_SLOTS = {f"reads/{phase}.{name}.raw" for phase in PHASES for name in READS}
SLOTS = MANDATORY | READ_SLOTS


def policy_snapshot_equal(reads, files, before, after):
    return all(
        reads[f"reads/before.{name}.raw"] == reads[f"reads/after.{name}.raw"]
        and files.get(f"reads/before.{name}.raw")
        == files.get(f"reads/after.{name}.raw")
        for name in READS
        if name != "observer_status"
    ) and all(
        before[key] == after[key]
        for key in (
            "uid",
            "euid",
            "netns",
            "userns",
            "which_bwrap",
            "bwrap_path",
            "bwrap_mode",
            "bwrap_uid",
            "bwrap_gid",
            "bwrap_identity",
        )
    )


def child_observation(raw, outer_netns):
    child = json.loads(raw)
    require(
        set(child)
        == {
            "effective_caps",
            "permitted_caps",
            "no_new_privs",
            "netns",
            "userns",
            "apparmor_label",
            "label_errno",
            "loopback_address",
            "loopback_flags",
            "loopback_errno",
        },
        "CHILD_SCHEMA",
    )
    require(
        all(
            type(child[name]) is int and child[name] >= 0
            for name in ("effective_caps", "permitted_caps", "no_new_privs")
        ),
        "CHILD_CAPABILITIES",
    )
    require(
        all(isinstance(child[name], str) for name in ("netns", "userns")),
        "CHILD_NAMESPACE",
    )
    return (
        child["effective_caps"] == child["permitted_caps"] == 0
        and child["netns"] != outer_netns
        and child["loopback_address"] == "127.0.0.1"
        and type(child["loopback_flags"]) is int
        and bool(child["loopback_flags"] & 1)
    )


def git(*args):
    result = subprocess.run(
        ["git", "--no-replace-objects", *args],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    require(result.returncode == 0, "GIT_FAILED")
    return result.stdout


def source_guard():
    require(INPUTS_HEAD and INPUTS_TREE, "UNBOUND_INPUTS")
    require(
        sys.platform == "linux" and platform.machine() == "x86_64", "WRONG_PLATFORM"
    )
    require(
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_JOB") == "bwrap-readonly",
        "WRONG_JOB",
    )
    require(
        [
            os.environ.get(name)
            for name in ("PROBE_RUNNER_CLASS", "PROBE_RUNNER_OS", "PROBE_RUNNER_ARCH")
        ]
        == ["github-hosted", "Linux", "X64"],
        "WRONG_RUNNER",
    )
    require(
        os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
        and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY,
        "WRONG_EVENT",
    )
    event = json.loads(read_regular(Path(os.environ["GITHUB_EVENT_PATH"])))[
        "pull_request"
    ]
    require(
        event["base"]["sha"] == INPUTS_HEAD
        and event["base"]["ref"] == INPUTS_REF
        and event["head"]["ref"] == PROPOSAL_REF,
        "WRONG_REFS",
    )
    require(
        event["head"]["repo"]["full_name"]
        == event["base"]["repo"]["full_name"]
        == REPOSITORY
        and event["head"]["repo"]["fork"] is False,
        "WRONG_REPOSITORY",
    )
    head = git("rev-parse", "HEAD").decode().strip()
    require(
        head == event["head"]["sha"] == os.environ["CANDIDATE_SHA"], "HEAD_MISMATCH"
    )
    require(
        git("show", "-s", "--format=%P", "HEAD").decode().strip() == INPUTS_HEAD,
        "PARENT_MISMATCH",
    )
    require(
        git("show", "-s", "--format=%T", PARENT).decode().strip() == PARENT_TREE,
        "PARENT_TREE_MISMATCH",
    )
    require(
        not git(
            "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"
        ),
        "DIRTY_SOURCE",
    )
    require(
        all(
            row[:2] == b"H " for row in git("ls-files", "-v", "-z").split(b"\0") if row
        ),
        "HIDDEN_INDEX_ENTRY",
    )
    require(
        git("show", "-s", "--format=%P", INPUTS_HEAD).decode().strip() == PARENT,
        "INPUTS_PARENT_MISMATCH",
    )
    require(
        git("show", "-s", "--format=%T", INPUTS_HEAD).decode().strip() == INPUTS_TREE,
        "INPUTS_TREE_MISMATCH",
    )
    input_rows = (
        git(
            "diff-tree",
            "-r",
            "--no-commit-id",
            "--name-status",
            "--no-renames",
            PARENT,
            INPUTS_HEAD,
        )
        .decode()
        .splitlines()
    )
    require(
        set(input_rows) == {"A\t" + name for name in INPUT_PATHS},
        "INPUTS_SCOPE_MISMATCH",
    )
    changed = set(
        git("diff", "--name-only", "--no-renames", INPUTS_HEAD, head)
        .decode()
        .splitlines()
    )
    contract_path = ".github/scripts/hepta_bwrap_readonly_contract.py"
    require(changed == (ADDED - INPUT_PATHS) | {contract_path}, "INPUTS_CHANGED")
    unbound = read_regular(ROOT / contract_path)
    for key, value in (("INPUTS_HEAD", INPUTS_HEAD), ("INPUTS_TREE", INPUTS_TREE)):
        literal = f'{key} = "{value}"'.encode()
        require(unbound.count(literal) == 1, "BINDING_LITERAL")
        unbound = unbound.replace(literal, f"{key} = None".encode())
    require(unbound == git("show", INPUTS_HEAD + ":" + contract_path), "BINDING_DELTA")
    rows = git(
        "diff-tree",
        "-r",
        "--no-commit-id",
        "--raw",
        "--no-abbrev",
        "-z",
        "--no-renames",
        PARENT,
        head,
    ).split(b"\0")
    require(rows.pop() == b"" and len(rows) % 2 == 0, "INVALID_DIFF")
    additions = {}
    for offset in range(0, len(rows), 2):
        old_mode, mode, old_blob, blob, status = rows[offset].decode().split()
        name = rows[offset + 1].decode()
        require(
            old_mode == ":000000"
            and mode == "100644"
            and old_blob == "0" * 40
            and status == "A",
            "PRODUCT_CHANGE",
        )
        require(name not in additions, "DUPLICATE_PATH")
        additions[name] = blob
    require(set(additions) == ADDED, "ADDITIONS_MISMATCH")
    count = 0
    for row in git("ls-files", "--stage", "-z").split(b"\0"):
        if not row:
            continue
        fields, name = row.split(b"\t", 1)
        mode, expected, stage = fields.decode().split()
        path = ROOT / name.decode()
        require(stage == "0" and mode in {"100644", "100755", "120000"}, "INDEX_MODE")
        require(
            all(
                not parent.is_symlink()
                for parent in path.parents
                if parent != ROOT and ROOT in parent.parents
            ),
            "LINKED_SOURCE_PARENT",
        )
        before = path.lstat()
        if mode == "120000":
            require(stat.S_ISLNK(before.st_mode), "SOURCE_MODE")
            actual = identity(os.fsencode(os.readlink(path)))["git_blob"]
        else:
            require(
                stat.S_ISREG(before.st_mode)
                and before.st_nlink == 1
                and stat.S_IMODE(before.st_mode) == int(mode[-3:], 8),
                "SOURCE_MODE",
            )
            digest = hashlib.sha1(b"blob " + str(before.st_size).encode() + b"\0")
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                require(
                    (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
                    "SOURCE_REPLACED",
                )
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
            require(
                (before.st_size, before.st_mtime_ns)
                == (after.st_size, after.st_mtime_ns),
                "SOURCE_CHANGED",
            )
            actual = digest.hexdigest()
        require(actual == expected, "WORKTREE_BLOB_MISMATCH")
        count += 1
    require(
        identity(read_regular(ROOT / SCANNER_PATH))["git_blob"] == SCANNER_BLOB,
        "SCANNER_CHANGED",
    )
    return {
        "head": head,
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "parent": PARENT,
        "parent_tree": PARENT_TREE,
        "inputs_head": INPUTS_HEAD,
        "inputs_tree": INPUTS_TREE,
        "only_additions": additions,
        "all_tracked_worktree_blobs_verified": count,
        "scanner_blob": SCANNER_BLOB,
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "runner_class": os.environ["PROBE_RUNNER_CLASS"],
        "runner_os": os.environ["PROBE_RUNNER_OS"],
        "runner_arch": os.environ["PROBE_RUNNER_ARCH"],
    }


def private_dir():
    path = Path(os.environ["PROBE_PRIVATE_DIR"])
    require(
        path.is_dir()
        and not path.is_symlink()
        and path.name.startswith("hepta-bwrap-readonly.")
        and path.parent.resolve() == Path(os.environ["RUNNER_TEMP"]).resolve(),
        "INVALID_PRIVATE_DIR",
    )
    return path


def journal_argv(interval):
    require(type(interval) is list and len(interval) == 2, "INVALID_INTERVAL")
    for value in interval:
        require(
            isinstance(value, str)
            and datetime.datetime.fromisoformat(value).utcoffset()
            == datetime.timedelta(0),
            "INVALID_INTERVAL",
        )
    return [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/journalctl",
        "--dmesg",
        "--no-pager",
        "--output=short-precise",
        "--lines=2000",
        "--since",
        interval[0],
        "--until",
        interval[1],
    ]
