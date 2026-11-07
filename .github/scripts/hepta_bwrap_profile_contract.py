"""Pin one official-profile intervention and its complete observation inventory."""

import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import tarfile

from hepta_bwrap_readonly_contract import COMMANDS as ORIGINAL_COMMANDS
from hepta_bwrap_readonly_contract import PROBE, journal_argv
from hepta_core_selected_evidence import identity, read_regular, require

ROOT = Path(__file__).resolve().parents[2]
PARENT = "25d940b9b768b9117a020fe350fd134198a2efcf"
PARENT_TREE = "26277e2bebd9e9f5a7cd04869c955dfd2fa7ddd2"
INPUTS_HEAD = None
INPUTS_TREE = None
CHECKS_HEAD = None
CHECKS_TREE = None
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
INPUTS_REF = "research/ndu-bwrap-share-inputs-20261107"
CHECKS_REF = "research/ndu-bwrap-share-checks-20261107"
PROPOSAL_REF = "research/ndu-bwrap-share-probe-20261107"
CONTRACT = ".github/scripts/hepta_bwrap_profile_contract.py"
PROFILE_PACKAGE = (
    ".github/scripts/apparmor-profiles_4.0.1really4.0.1-0ubuntu0.24.04.9_all.deb"
)
DEPENDENCIES = ".github/scripts/hepta-bwrap-profile-dependencies.json"
SHARE_HELPER = ".github/scripts/hepta_bwrap_share_mode.py"
SHARE_HELPER_SHA = "3ebf6137161889300b3173efc43a8acbd2fbdcbdee80d4903532d486d0c4333d"
SHARE_PYTHON = "/usr/bin/python3.12"
BASELINE_BLOBS = {
    ".github/scripts/hepta-bwrap-profile-dependencies.json": "5937fe0631024016c746b46f4a71f54ec124b48b",
    ".github/scripts/hepta_bwrap_profile.py": "5c42f13ba4bd91b0000a81d9716c5975e02dad16",
    ".github/scripts/hepta_bwrap_profile_contract.py": "947d24e58a849b8f6ab9103fd8ed94b37d1b33f6",
    ".github/scripts/hepta_bwrap_profile_evidence.py": "8e7174fda44ba76180168162ccd98988d1c344da",
    ".github/workflows/hepta-bwrap-profile-probe.yml": "f1faac01495487c2f253021db2cb3815331c82fd",
}
INPUT_PATHS = {CONTRACT, DEPENDENCIES, SHARE_HELPER}
CHECK_PATHS = {
    ".github/scripts/hepta_bwrap_share_checks.py",
    ".github/scripts/hepta_bwrap_profile_evidence.py",
}
EXECUTOR_PATHS = {
    ".github/scripts/hepta_bwrap_profile.py",
    ".github/workflows/hepta-bwrap-profile-probe.yml",
}
DECLARED_PATHS = INPUT_PATHS | CHECK_PATHS | EXECUTOR_PATHS
SCANNER_PATH = ".github/scripts/hepta_core_selected_evidence.py"
SCANNER_BLOB = "f18f5d0ce06cead0817513814da96f129523cf8c"
LIMIT = 4 * 1024 * 1024
PARSER = "/usr/sbin/apparmor_parser"
PROFILE_SHA = "11d39094f044f0cda0febb3ad517b830301da6b2ce929664af09ee9e4dd264f9"
BWRAP_SHA = "e318903862396f96de3df57264e0158682b952fd3fb53ac23d876413e7b30f71"
APPARMOR_VERSION = "4.0.1really4.0.1-0ubuntu0.24.04.9"
DEPENDENCY_DATA = json.loads(read_regular(ROOT / DEPENDENCIES))
PHASES = ("before", "preload", "after")
READS = {
    "os_release": "/etc/os-release",
    "apparmor_enabled": "/sys/module/apparmor/parameters/enabled",
    "restrict_userns": "/proc/sys/kernel/apparmor_restrict_unprivileged_userns",
    "userns_clone": "/proc/sys/kernel/unprivileged_userns_clone",
    "max_user_namespaces": "/proc/sys/user/max_user_namespaces",
    "observer_status": "/proc/self/status",
    "observer_label": "/proc/self/attr/current",
    **{
        f"input_{index:02d}": path
        for index, path in enumerate(sorted(DEPENDENCY_DATA["regular_files"]))
    },
}
ABSENT_PATHS = sorted(
    set(DEPENDENCY_DATA["absent_optional_paths"])
    | {
        "/etc/apparmor.d/bwrap-userns-restrict",
        "/etc/apparmor.d/bwrap",
        "/etc/apparmor.d/usr.bin.bwrap",
        "/usr/share/apparmor/extra-profiles/bwrap-userns-restrict",
    }
)
PARENTS = sorted(
    {
        str(parent)
        for name in set(DEPENDENCY_DATA["regular_files"])
        | set(DEPENDENCY_DATA["binaries"])
        | set(DEPENDENCY_DATA["included_directories"])
        | set(ABSENT_PATHS)
        for parent in Path(name).parents
    }
)

HOST_COMMANDS = {
    key: value
    for key, value in ORIGINAL_COMMANDS.items()
    if key not in {"packages", "package_policy", "bwrap_owner"}
}
HOST_COMMANDS["packages"] = [
    "/usr/bin/dpkg-query",
    "-W",
    "-f=${binary:Package}\\t${Version}\\n",
    "apparmor",
    "bubblewrap",
]
HOST_COMMANDS["parser_version"] = [PARSER, "--version"]
HOST_COMMANDS["parser_help"] = [PARSER, "--help"]
PARSER_COMMON = [
    "--skip-kernel-load",
    "--skip-cache",
    "--abort-on-error",
    "--base=/etc/apparmor.d",
]
PARSER_COMMANDS = {
    "parser_names": [PARSER, *PARSER_COMMON, "--print-config-file", "--names"],
    "parser_preprocess": [PARSER, *PARSER_COMMON, "--preprocess"],
    "parser_compile": [PARSER, *PARSER_COMMON],
    "profile_add": [
        "/usr/bin/sudo",
        "-n",
        PARSER,
        "--add",
        "--skip-cache",
        "--abort-on-error",
        "--base=/etc/apparmor.d",
    ],
}
COMMAND_IDS = (
    {f"{phase}.{name}" for phase in ("before", "after") for name in HOST_COMMANDS}
    | {f"loaded.{name}" for name in ("loaded_profiles", "apparmor_status")}
    | {"baseline", "post", "baseline_journal", "post_journal"}
    | set(PARSER_COMMANDS)
    | {"share_mode"}
)
READ_SLOTS = {f"reads/{phase}.{name}.raw" for phase in PHASES for name in READS}
SLOTS = (
    {
        "source-before.json",
        "source-after.json",
        "readiness.json",
        "result.json",
        "profile.raw",
        "share-runtime.before.json",
        "share-runtime.after.json",
    }
    | {f"{phase}.provenance.json" for phase in PHASES}
    | READ_SLOTS
    | {
        f"logs/{name}.{stream}.log"
        for name in COMMAND_IDS
        for stream in ("stdout", "stderr")
    }
)


def profile_bytes():
    package = read_regular(ROOT / PROFILE_PACKAGE)
    require(
        identity(package)
        == {
            "bytes": 39592,
            "sha256": "90b02aa006eea7702cd4e851343e469e41365dda42145a3cb035de1d6c773b8c",
            "git_blob": "8f61d6ca3cae0490dd63520c75a036f9307b4c76",
        },
        "VENDOR_PACKAGE_CHANGED",
    )
    packed = package[5806:]
    require(
        len(packed) == 33786
        and identity(packed)["sha256"]
        == "8dcb82b7ce73e7097dcf1a60b88e2cd7ea77faf7213d7a1640054b77b7e6f086",
        "VENDOR_PAYLOAD_CHANGED",
    )
    library = ctypes.CDLL("/usr/lib/x86_64-linux-gnu/libzstd.so.1")
    library.ZSTD_decompress.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    library.ZSTD_decompress.restype = ctypes.c_size_t
    library.ZSTD_isError.argtypes = [ctypes.c_size_t]
    library.ZSTD_isError.restype = ctypes.c_uint
    source = ctypes.create_string_buffer(packed, 33786)
    destination = ctypes.create_string_buffer(368640)
    size = library.ZSTD_decompress(destination, 368640, source, 33786)
    require(not library.ZSTD_isError(size) and size == 368640, "VENDOR_DECODE_FAILED")
    raw = destination.raw
    require(
        identity(raw)["sha256"]
        == "fb52ed27e061c153b387f2d2317deaea16ccbe94718347d7dc21a5b78e831352",
        "VENDOR_TAR_CHANGED",
    )
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        matches = [
            member
            for member in archive.getmembers()
            if member.name
            == "./usr/share/apparmor/extra-profiles/bwrap-userns-restrict"
        ]
        require(len(matches) == 1, "VENDOR_MEMBER_COUNT")
        member = matches[0]
        require(
            member.isreg()
            and member.size == 1936
            and member.mode == 0o644
            and member.uid == member.gid == 0
            and not member.linkname
            and not member.sparse,
            "VENDOR_MEMBER_TYPE",
        )
        stream = archive.extractfile(member)
        require(stream is not None, "VENDOR_MEMBER_MISSING")
        with stream:
            profile = stream.read(1937)
    require(
        len(profile) == 1936 and identity(profile)["sha256"] == PROFILE_SHA,
        "PROFILE_CHANGED",
    )
    return profile


def expected_argv(name, commands):
    if name == "share_mode":
        source = read_regular(ROOT / SHARE_HELPER)
        require(identity(source)["sha256"] == SHARE_HELPER_SHA, "SHARE_HELPER_CHANGED")
        return [
            "/usr/bin/sudo",
            "-n",
            SHARE_PYTHON,
            "-I",
            "-S",
            "-c",
            source.decode("utf-8"),
        ]
    if name in {"baseline", "post"}:
        return PROBE
    if name.endswith("_journal"):
        row = commands[name.removesuffix("_journal")]
        return journal_argv([row["started_utc"], row["finished_utc"]])
    if name in PARSER_COMMANDS:
        return PARSER_COMMANDS[name]
    return HOST_COMMANDS[name.split(".", 1)[1]]


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
    require(
        INPUTS_HEAD and INPUTS_TREE and CHECKS_HEAD and CHECKS_TREE, "UNBOUND_SOURCE"
    )
    require(
        sys.platform == "linux" and platform.machine() == "x86_64", "WRONG_PLATFORM"
    )
    require(
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_JOB") == "bwrap-profile"
        and os.environ.get("GITHUB_RUN_ATTEMPT") == "1",
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
        event["base"]["sha"] == CHECKS_HEAD
        and event["base"]["ref"] == CHECKS_REF
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
    for child, parent in (
        (head, CHECKS_HEAD),
        (CHECKS_HEAD, INPUTS_HEAD),
        (INPUTS_HEAD, PARENT),
    ):
        require(
            git("show", "-s", "--format=%P", child).decode().strip() == parent,
            "PARENT_MISMATCH",
        )
    for commit, tree in (
        (PARENT, PARENT_TREE),
        (INPUTS_HEAD, INPUTS_TREE),
        (CHECKS_HEAD, CHECKS_TREE),
    ):
        require(
            git("show", "-s", "--format=%T", commit).decode().strip() == tree,
            "TREE_MISMATCH",
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
    for previous, current, added in (
        (PARENT, INPUTS_HEAD, INPUT_PATHS),
        (INPUTS_HEAD, CHECKS_HEAD, CHECK_PATHS),
        (CHECKS_HEAD, head, EXECUTOR_PATHS),
    ):
        expected = {
            ("M\t" if name in BASELINE_BLOBS else "A\t") + name for name in added
        }
        if previous != PARENT:
            expected.add("M\t" + CONTRACT)
        require(
            set(
                git(
                    "diff-tree",
                    "-r",
                    "--no-commit-id",
                    "--name-status",
                    "--no-renames",
                    previous,
                    current,
                )
                .decode()
                .splitlines()
            )
            == expected,
            "STAGE_SCOPE_MISMATCH",
        )
    unbound = read_regular(ROOT / CONTRACT)
    for prefix, commit, tree, expected_commit in (
        ("CHECKS", CHECKS_HEAD, CHECKS_TREE, CHECKS_HEAD),
        ("INPUTS", INPUTS_HEAD, INPUTS_TREE, INPUTS_HEAD),
    ):
        for suffix, value in (("HEAD", commit), ("TREE", tree)):
            key = prefix + "_" + suffix
            literal = f'{key} = "{value}"'.encode()
            require(unbound.count(literal) == 1, "BINDING_LITERAL")
            unbound = unbound.replace(literal, f"{key} = None".encode())
        require(
            unbound == git("show", expected_commit + ":" + CONTRACT), "BINDING_DELTA"
        )
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
            mode == "100644"
            and (
                name in BASELINE_BLOBS
                and old_mode == ":100644"
                and old_blob == BASELINE_BLOBS[name]
                and status == "M"
                or name not in BASELINE_BLOBS
                and old_mode == ":000000"
                and old_blob == "0" * 40
                and status == "A"
            ),
            "PRODUCT_CHANGE",
        )
        require(name not in additions, "DUPLICATE_PATH")
        additions[name] = blob
    require(set(additions) == DECLARED_PATHS, "DECLARED_SCOPE_MISMATCH")
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
    require(
        identity(read_regular(ROOT / PROFILE_PACKAGE))["sha256"]
        == "90b02aa006eea7702cd4e851343e469e41365dda42145a3cb035de1d6c773b8c",
        "VENDOR_PACKAGE_CHANGED",
    )
    return {
        "head": head,
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "parent": PARENT,
        "parent_tree": PARENT_TREE,
        "inputs_head": INPUTS_HEAD,
        "inputs_tree": INPUTS_TREE,
        "checks_head": CHECKS_HEAD,
        "checks_tree": CHECKS_TREE,
        "declared_source_changes": additions,
        "all_tracked_worktree_blobs_verified": count,
        "scanner_blob": SCANNER_BLOB,
        "profile_sha256": PROFILE_SHA,
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
        and path.name.startswith("hepta-bwrap-profile.")
        and path.parent.resolve() == Path(os.environ["RUNNER_TEMP"]).resolve(),
        "INVALID_PRIVATE_DIR",
    )
    return path


def bounded_read(path):
    chunks = []
    remaining = LIMIT + 1
    with open(path, "rb", buffering=0) as handle:
        while remaining:
            chunk = handle.read(min(4096, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    raw = b"".join(chunks)
    require(len(raw) <= LIMIT, "HOST_INPUT_TOO_LARGE")
    return raw


def path_observation(name, *, include_members=False):
    path = Path(name)
    try:
        value = path.lstat()
        kind = (
            "REGULAR"
            if stat.S_ISREG(value.st_mode)
            else "DIRECTORY"
            if stat.S_ISDIR(value.st_mode)
            else "OTHER"
        )
        row = {
            "status": kind,
            "errno": None,
            "mode": stat.S_IMODE(value.st_mode),
            "uid": value.st_uid,
            "gid": value.st_gid,
            "nlink": value.st_nlink,
        }
        if kind == "DIRECTORY" and include_members:
            row["entries"] = sorted(child.name for child in path.iterdir())
        return row
    except OSError as error:
        return {
            "status": "ABSENT"
            if isinstance(error, FileNotFoundError)
            else "UNAVAILABLE",
            "errno": error.errno,
        }
