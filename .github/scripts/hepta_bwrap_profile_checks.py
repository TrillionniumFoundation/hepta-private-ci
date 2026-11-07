"""Validate exact distribution inputs and observed namespace behavior."""

import json
import re

from hepta_bwrap_profile_contract import (
    ABSENT_PATHS,
    APPARMOR_VERSION,
    BWRAP_SHA,
    DEPENDENCY_DATA,
    READS,
    PARENTS,
)
from hepta_core_selected_evidence import identity, require


def process_fields(raw):
    result = {}
    for line in raw.decode().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            require(key not in result, "DUPLICATE_PROCESS_FIELD")
            result[key] = value.strip()
    return result


def validate_phase(originals, phase):
    provenance = json.loads(originals[f"{phase}.provenance.json"])
    require(
        set(provenance)
        == {
            "uid",
            "euid",
            "netns",
            "userns",
            "which_bwrap",
            "files",
            "binaries",
            "directories",
            "absent",
            "parents",
        },
        "PROVENANCE_SCHEMA",
    )
    require(
        type(provenance["uid"]) is int
        and provenance["uid"] != 0
        and provenance["euid"] == provenance["uid"]
        and provenance["which_bwrap"] == "/usr/bin/bwrap",
        "PRIVILEGED_OR_WRONG_CALLER",
    )
    for key in ("netns", "userns"):
        require(
            isinstance(provenance[key], str)
            and re.fullmatch(r"(?:net|user):\[\d+\]", provenance[key]),
            "INVALID_NAMESPACE",
        )
    raw_files = {
        path: originals[f"reads/{phase}.{name}.raw"] for name, path in READS.items()
    }
    for key in ("files", "binaries", "directories", "absent", "parents"):
        expected = (
            DEPENDENCY_DATA["regular_files"]
            if key == "files"
            else DEPENDENCY_DATA["binaries"]
            if key == "binaries"
            else DEPENDENCY_DATA["included_directories"]
            if key == "directories"
            else ABSENT_PATHS
            if key == "absent"
            else PARENTS
        )
        require(set(provenance[key]) == set(expected), "PROVENANCE_PATHS")
    for key, expected in (
        ("files", DEPENDENCY_DATA["regular_files"]),
        ("binaries", DEPENDENCY_DATA["binaries"]),
    ):
        for path, entry in expected.items():
            actual = provenance[key][path]
            require(
                actual["status"] == "REGULAR"
                and actual["uid"] == actual["gid"] == 0
                and actual["mode"] == int(entry["mode"], 8)
                and actual["nlink"] == 1,
                "UNSAFE_DISTRIBUTION_FILE",
            )
            observed = (
                identity(raw_files[path]) if key == "files" else actual["identity"]
            )
            require(
                observed["bytes"] == entry["bytes"]
                and observed["sha256"] == entry["sha256"],
                "DISTRIBUTION_BYTES_CHANGED",
            )
    for path, expected in DEPENDENCY_DATA["included_directories"].items():
        actual = provenance["directories"][path]
        require(
            actual["status"] == "DIRECTORY"
            and actual["uid"] == actual["gid"] == 0
            and not actual["mode"] & 0o022
            and actual["entries"] == expected,
            "CUSTOM_INCLUDE_DIRECTORY",
        )
    require(
        all(
            row == {"status": "ABSENT", "errno": 2}
            for row in provenance["absent"].values()
        ),
        "PREEXISTING_PROFILE_OR_INCLUDE",
    )
    for row in provenance["parents"].values():
        require(
            row == {"status": "ABSENT", "errno": 2}
            or row["status"] == "DIRECTORY"
            and row["uid"] == row["gid"] == 0
            and not row["mode"] & 0o022,
            "UNSAFE_POLICY_PARENT",
        )
    os_release = raw_files["/etc/os-release"].decode().splitlines()
    require(
        os_release.count("ID=ubuntu") == 1
        and os_release.count('VERSION_ID="24.04"') == 1,
        "WRONG_DISTRIBUTION",
    )
    require(
        raw_files["/sys/module/apparmor/parameters/enabled"] == b"Y\n",
        "APPARMOR_NOT_ENABLED",
    )
    for path in (
        "/proc/sys/kernel/apparmor_restrict_unprivileged_userns",
        "/proc/sys/kernel/unprivileged_userns_clone",
    ):
        require(raw_files[path].strip() == b"1", "USERNS_PRECONDITION")
    maximum = raw_files["/proc/sys/user/max_user_namespaces"].strip()
    require(
        re.fullmatch(rb"[0-9]+", maximum) and int(maximum) > 0, "USERNS_PRECONDITION"
    )
    status = process_fields(raw_files["/proc/self/status"])
    require(
        int(status["CapEff"], 16) == int(status["CapPrm"], 16) == 0,
        "CALLER_CAPABILITIES",
    )
    require(
        raw_files["/proc/self/attr/current"] == b"unconfined\n",
        "CALLER_PROFILE_CHANGED",
    )
    return provenance


def command_succeeded(commands, name):
    row = commands[name]
    return (
        row["status"] == "EXITED"
        and row["exit_code"] == 0
        and row["cleanup_confirmed"] is True
    )


def profiles(originals, commands, phase):
    require(
        all(
            command_succeeded(commands, f"{phase}.{name}")
            for name in ("loaded_profiles", "apparmor_status")
        ),
        "PROFILE_INVENTORY_UNAVAILABLE",
    )
    listed = {}
    for line in (
        originals[f"logs/{phase}.loaded_profiles.stdout.log"].decode().splitlines()
    ):
        name, mode = line.rsplit(" (", 1)
        require(name not in listed and mode.endswith(")"), "PROFILE_INVENTORY_SCHEMA")
        listed[name] = mode[:-1]
    status = json.loads(originals[f"logs/{phase}.apparmor_status.stdout.log"])
    require(
        set(status) == {"version", "profiles", "processes"}
        and status["version"] == "2",
        "APPARMOR_STATUS_SCHEMA",
    )
    require(
        status["profiles"] == listed and type(status["processes"]) is dict,
        "PROFILE_INVENTORY_MISMATCH",
    )
    return listed


def validate_before(originals, commands):
    before = validate_phase(originals, "before")
    for name in (
        "packages",
        "bwrap_version",
        "bwrap_help",
        "file_capabilities",
        "parser_version",
        "parser_help",
    ):
        require(command_succeeded(commands, "before." + name), "HOST_COMMAND_FAILED")
    package_lines = originals["logs/before.packages.stdout.log"].decode().splitlines()
    require(len(package_lines) == 2, "PACKAGE_INVENTORY")
    packages = dict(line.split("\t", 1) for line in package_lines)
    require(
        packages == {"apparmor": APPARMOR_VERSION, "bubblewrap": "0.9.0-1ubuntu0.3"},
        "PACKAGE_VERSION_CHANGED",
    )
    require(
        originals["logs/before.bwrap_version.stdout.log"] == b"bubblewrap 0.9.0\n",
        "BWRAP_VERSION_CHANGED",
    )
    require(
        originals["logs/before.file_capabilities.stdout.log"] == b"",
        "BWRAP_FILE_CAPABILITIES",
    )
    help_text = originals["logs/before.parser_help.stdout.log"]
    require(
        all(
            flag in help_text
            for flag in (
                b"--add",
                b"--names",
                b"--preprocess",
                b"--base",
                b"--skip-cache",
                b"--skip-kernel-load",
                b"--abort-on-error",
            )
        ),
        "PARSER_OPTIONS_UNAVAILABLE",
    )
    require(
        before["binaries"]["/usr/bin/bwrap"]["identity"]["sha256"] == BWRAP_SHA,
        "BWRAP_BYTES_CHANGED",
    )
    loaded = profiles(originals, commands, "before")
    require(
        not any(
            re.search(r"(?:^|[:/&])(?:bwrap|unpriv_bwrap)(?:$|[:/&])", name)
            for name in loaded
        ),
        "PREEXISTING_PROFILE",
    )
    require(
        loaded.get("unprivileged_userns") == "enforce",
        "RESTRICTION_PROFILE_UNAVAILABLE",
    )
    return loaded


def baseline_observation(originals, commands):
    row = commands["baseline"]
    require(
        row["status"] == "EXITED"
        and row["exit_code"] == 1
        and row["cleanup_confirmed"] is True,
        "BASELINE_NOT_REPRODUCED",
    )
    require(
        originals["logs/baseline.stdout.log"] == b""
        and originals["logs/baseline.stderr.log"]
        == b"bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted\n",
        "BASELINE_NOT_REPRODUCED",
    )
    require(
        command_succeeded(commands, "baseline_journal"), "BASELINE_JOURNAL_UNAVAILABLE"
    )
    parsed = []
    for line in originals["logs/baseline_journal.stdout.log"].decode().splitlines():
        fields = {
            key: quoted or plain
            for key, quoted, plain in re.findall(r'\b(\w+)=(?:"([^"]*)"|(\S+))', line)
        }
        parsed.append(fields)
    transition = [
        p
        for p in parsed
        if all(
            p.get(k) == v
            for k, v in {
                "apparmor": "AUDIT",
                "operation": "userns_create",
                "profile": "unconfined",
                "target": "unprivileged_userns",
                "execpath": "/usr/bin/bwrap",
                "comm": "bwrap",
                "pid": str(row["pid"]),
            }.items()
        )
    ]
    denial = [
        p
        for p in parsed
        if all(
            p.get(k) == v
            for k, v in {
                "apparmor": "DENIED",
                "operation": "capable",
                "profile": "unprivileged_userns",
                "capability": "12",
                "capname": "net_admin",
                "comm": "bwrap",
            }.items()
        )
        and p.get("pid", "").isdigit()
    ]
    require(len(transition) == 1 and len(denial) == 1, "BASELINE_APPARMOR_ASSOCIATION")
    return {
        "observed_probe_pid": row["pid"],
        "observed_denial_pid": int(denial[0]["pid"]),
        "parent_child_relationship": "INFERRED_FROM_REVIEWED_BWRAP_SOURCE_NOT_CAPTURED_PPID",
    }


def validate_precompile(originals, commands):
    require(
        all(
            command_succeeded(commands, name)
            for name in ("parser_names", "parser_preprocess", "parser_compile")
        ),
        "PRECOMPILE_FAILED",
    )
    lines = originals["logs/parser_names.stdout.log"].decode().splitlines()
    require(
        len(lines) == 3
        and lines[0] == "/etc/apparmor/parser.conf"
        and set(lines[1:]) == {"bwrap", "unpriv_bwrap"},
        "PARSER_NAMES_OR_CONFIG",
    )
    require(bool(originals["logs/parser_preprocess.stdout.log"]), "PREPROCESS_MISSING")
    require(
        validate_phase(originals, "before") == validate_phase(originals, "preload"),
        "PRELOAD_PROVENANCE_DRIFT",
    )


def validate_loaded(originals, commands, phase):
    require(command_succeeded(commands, "profile_add"), "LOAD_FAILED_OR_UNKNOWN")
    before = profiles(originals, commands, "before")
    after = profiles(originals, commands, phase)
    require(
        after == {**before, "bwrap": "enforce", "unpriv_bwrap": "enforce"},
        "LOADED_PROFILE_SET_OR_MODE",
    )


def validate_after(originals, commands):
    before = validate_phase(originals, "before")
    preload = validate_phase(originals, "preload")
    after = validate_phase(originals, "after")
    require(before == preload == after, "PROVENANCE_DRIFT")
    for name in (
        "restrict_userns",
        "userns_clone",
        "max_user_namespaces",
        "os_release",
        "apparmor_enabled",
        "observer_label",
    ):
        require(
            originals[f"reads/before.{name}.raw"]
            == originals[f"reads/preload.{name}.raw"]
            == originals[f"reads/after.{name}.raw"],
            "HOST_POLICY_CHANGED",
        )
    validate_loaded(originals, commands, "after")
    require(
        command_succeeded(commands, "post")
        and command_succeeded(commands, "post_journal"),
        "POST_NAMESPACE_FAILED",
    )
    child = json.loads(originals["logs/post.stdout.log"])
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
        type(child["effective_caps"]) is int
        and type(child["permitted_caps"]) is int
        and child["effective_caps"] == child["permitted_caps"] == 0,
        "CHILD_CAPABILITIES",
    )
    require(
        child["apparmor_label"] == "bwrap//&unpriv_bwrap (enforce)\n"
        and child["label_errno"] is None,
        "CHILD_PROFILE",
    )
    require(
        type(child["no_new_privs"]) is int and child["no_new_privs"] == 1,
        "CHILD_NO_NEW_PRIVILEGES",
    )
    require(
        all(
            isinstance(child[key], str) and re.fullmatch(pattern, child[key])
            for key, pattern in (("netns", r"net:\[\d+\]"), ("userns", r"user:\[\d+\]"))
        ),
        "CHILD_NAMESPACE_SCHEMA",
    )
    require(
        child["netns"] != before["netns"] and child["userns"] != before["userns"],
        "CHILD_NAMESPACE",
    )
    require(
        child["loopback_address"] == "127.0.0.1"
        and type(child["loopback_flags"]) is int
        and child["loopback_flags"] & 1
        and child["loopback_errno"] is None,
        "CHILD_LOOPBACK",
    )
    return child
