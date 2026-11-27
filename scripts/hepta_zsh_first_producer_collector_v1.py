"""Data-only evidence checks for one ordinary zsh producer; never runs a child."""

import gzip
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import stat
import struct
import tarfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw, kind="blob"):
    return hashlib.sha1(
        kind.encode("ascii") + b" " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest()


def pin(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": digest(raw),
    }


def metadata(value):
    return {
        "dev": value.st_dev,
        "ino": value.st_ino,
        "mode": value.st_mode,
        "nlink": value.st_nlink,
        "uid": value.st_uid,
        "gid": value.st_gid,
        "size": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
    }


def safe_relative(value):
    require(
        isinstance(value, str) and value and len(value) <= 4096, "invalid relative path"
    )
    require(
        "\0" not in value
        and "\\" not in value
        and "\n" not in value
        and "\r" not in value,
        "noncanonical relative path",
    )
    p = PurePosixPath(value)
    require(
        not p.is_absolute()
        and str(p) == value
        and all(part not in ("", ".", "..") for part in p.parts),
        "unsafe relative path",
    )
    return p


def stable_raw(path, maximum, check):
    path = Path(path)
    require(
        path.is_absolute() and path.resolve(strict=True) == path, "nonphysical input"
    )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and 0 <= before.st_size <= maximum,
            "unbounded or nonregular input",
        )
        data = bytearray()
        while True:
            check()
            chunk = os.read(fd, min(1024 * 1024, maximum + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            require(len(data) <= maximum, "input exceeded its bound")
        after = os.fstat(fd)
        require(
            metadata(before) == metadata(after) == metadata(path.lstat())
            and len(data) == before.st_size,
            "input changed during descriptor read",
        )
        check()
        return bytes(data), metadata(before)
    finally:
        os.close(fd)


def stable_digest(path, maximum, check):
    path = Path(path)
    require(
        path.is_absolute() and path.resolve(strict=True) == path,
        "nonphysical hash input",
    )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and 0 <= before.st_size <= maximum,
            "unbounded hash input",
        )
        sha = hashlib.sha256()
        git = hashlib.sha1(b"blob " + str(before.st_size).encode("ascii") + b"\0")
        total = 0
        while True:
            check()
            chunk = os.read(fd, min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            require(total <= maximum, "hash input grew")
            sha.update(chunk)
            git.update(chunk)
        after = os.fstat(fd)
        require(
            total == before.st_size
            and metadata(before) == metadata(after) == metadata(path.lstat()),
            "hash input identity changed",
        )
        check()
        return {
            "path": str(path),
            "bytes": total,
            "sha256": sha.hexdigest(),
            "git_blob": git.hexdigest(),
            "metadata": metadata(before),
        }
    finally:
        os.close(fd)


def git_tree(leaves):
    directories = {"": {}}
    for path, row in leaves.items():
        parts = safe_relative(path).parts
        parent = ""
        for name in parts[:-1]:
            child = name if not parent else parent + "/" + name
            require(
                name not in directories[parent]
                or directories[parent][name][0] == "40000",
                "file and directory overlap",
            )
            directories[parent][name] = ("40000", child)
            directories.setdefault(child, {})
            parent = child
        require(parts[-1] not in directories[parent], "duplicate tree entry")
        directories[parent][parts[-1]] = (row["mode"], row["git_blob"])
    hashes = {}
    for folder in sorted(
        directories, key=lambda p: (p.count("/"), len(p)), reverse=True
    ):
        values = directories[folder]
        body = bytearray()
        for name in sorted(
            values,
            key=lambda n: (
                n.encode("utf-8") + (b"/" if values[n][0] == "40000" else b"")
            ),
        ):
            mode, value = values[name]
            object_sha = hashes[value] if mode == "40000" else value
            body.extend(
                mode.encode("ascii")
                + b" "
                + name.encode("utf-8")
                + b"\0"
                + bytes.fromhex(object_sha)
            )
        hashes[folder] = digest(bytes(body), "tree")
    return hashes[""], hashes


def physical_tree(
    root, expected_leaves, check, substitutions=None, reject_untracked=False
):
    root = Path(root)
    require(
        root.is_absolute() and root.resolve(strict=True) == root, "source root alias"
    )
    require(0 < len(expected_leaves) <= 30000, "source tree entry bound")
    substitutions = substitutions or {}
    require(set(substitutions).issubset(expected_leaves), "unknown substituted source")
    observed = {}
    total = 0
    for relative in sorted(expected_leaves):
        check()
        row = expected_leaves[relative]
        rel = safe_relative(relative)
        path = root.joinpath(*rel.parts)
        require(
            path.parent.resolve(strict=True) == path.parent, "source ancestor symlink"
        )
        wanted = substitutions.get(relative, row)
        mode = wanted["mode"]
        if mode == "120000":
            before = path.lstat()
            require(
                stat.S_ISLNK(before.st_mode) and before.st_nlink == 1,
                "expected source symlink changed",
            )
            raw = os.fsencode(os.readlink(path))
            require(
                len(raw) <= 4096 and metadata(before) == metadata(path.lstat()),
                "symlink changed",
            )
            actual = {**pin(raw), "metadata": metadata(before)}
        else:
            require(mode in ("100644", "100755"), "unsupported source mode")
            actual = stable_digest(path, 64 * 1024 * 1024, check)
            executable = bool(actual["metadata"]["mode"] & 0o111)
            require(executable == (mode == "100755"), "source executable mode changed")
        require(
            actual["git_blob"] == wanted["git_blob"], "source blob differs: " + relative
        )
        if wanted.get("bytes") is not None:
            require(
                actual["bytes"] == wanted["bytes"], "source size differs: " + relative
            )
        total += actual["bytes"]
        require(total <= 512 * 1024 * 1024, "total source byte bound")
        observed[relative] = {"mode": mode, **actual}
    if reject_untracked:
        found = set()
        count = 0
        for folder, directories, files in os.walk(root, followlinks=False):
            check()
            relative_folder = Path(folder).relative_to(root)
            if relative_folder == Path("."):
                directories[:] = [name for name in directories if name != ".git"]
                files = [name for name in files if name != ".git"]
            for name in list(directories):
                path = Path(folder) / name
                if path.is_symlink():
                    found.add(path.relative_to(root).as_posix())
                    directories.remove(name)
            for name in files:
                found.add((Path(folder) / name).relative_to(root).as_posix())
            count += len(directories) + len(files)
            require(count <= 50000, "physical checkout census bound")
        require(found == set(expected_leaves), "untracked or missing checkout content")
    return {"files": observed, "total_bytes": total, "leaf_count": len(observed)}


def api_tree(data, root_sha):
    require(
        data.get("sha") == root_sha
        and data.get("truncated") is False
        and isinstance(data.get("tree"), list)
        and len(data["tree"]) <= 50000,
        "incomplete Git tree response",
    )
    leaves, tree_rows = {}, {}
    for row in data["tree"]:
        path = row.get("path")
        safe_relative(path)
        sha = row.get("sha")
        require(
            isinstance(sha, str)
            and len(sha) == 40
            and all(c in "0123456789abcdef" for c in sha),
            "bad tree object",
        )
        if row.get("type") == "tree":
            require(
                row.get("mode") == "040000" and path not in tree_rows, "bad tree row"
            )
            tree_rows[path] = sha
        else:
            require(
                row.get("type") == "blob"
                and row.get("mode") in ("100644", "100755", "120000")
                and path not in leaves
                and type(row.get("size")) is int,
                "unsupported or duplicate source leaf",
            )
            leaves[path] = {"mode": row["mode"], "bytes": row["size"], "git_blob": sha}
    calculated, directories = git_tree(leaves)
    require(
        calculated == root_sha
        and set(tree_rows) == set(directories) - {""}
        and all(directories[path] == sha for path, sha in tree_rows.items()),
        "complete API Git tree does not reconstruct",
    )
    return leaves


def upstream_basis(evidence, check, upstream_commit, upstream_tree):
    evidence = Path(evidence)
    commit, commit_meta = stable_raw(evidence / "upstream-commit.raw", 65536, check)
    require(
        digest(commit, "commit") == upstream_commit, "upstream commit object differs"
    )
    header = commit.split(b"\n\n", 1)[0].splitlines()
    tree_lines = [line for line in header if line.startswith(b"tree ")]
    require(
        len(tree_lines) == 1 and len(tree_lines[0]) == 45,
        "upstream commit tree missing",
    )
    root_sha = tree_lines[0][5:].decode("ascii")
    raw, tree_meta = stable_raw(evidence / "upstream-tree.raw", 8 * 1024 * 1024, check)
    require(raw.endswith(b"\0"), "unterminated upstream ls-tree")
    leaves = {}
    for item in raw[:-1].split(b"\0"):
        prefix, relative = item.split(b"\t", 1)
        mode, kind, sha = prefix.decode("ascii").split(" ")
        path = relative.decode("utf-8")
        safe_relative(path)
        require(
            kind == "blob"
            and mode in ("100644", "100755", "120000")
            and path not in leaves
            and len(sha) == 40,
            "bad upstream leaf",
        )
        leaves[path] = {"mode": mode, "git_blob": sha}
    actual, _ = git_tree(leaves)
    require(
        actual == root_sha == upstream_tree,
        "upstream fixed full tree does not reconstruct",
    )
    require(
        leaves.get("Src/exec.c")
        == {"mode": "100644", "git_blob": "27bca110cc5e90bffb35c6f24da1ac8cbaf672dc"},
        "original upstream exec.c differs",
    )
    require("Src/zsh" not in leaves, "upstream contains a prebuilt target")
    return {
        "commit": upstream_commit,
        "tree": root_sha,
        "leaves": leaves,
        "commit_record": {**pin(commit), "metadata": commit_meta},
        "tree_record": {**pin(raw), "metadata": tree_meta},
    }


def events(path, phases, check):
    raw, identity = stable_raw(path, 16384, check)
    expected = []
    for phase in phases:
        expected.extend(["START\t" + phase, "DONE\t" + phase])
    expected.append("EXIT\t" + phases[-1] + "\t0")
    require(
        raw.decode("utf-8").splitlines() == expected, "phase attempts or exit changed"
    )
    return {
        "phases": phases,
        "attempts_each": 1,
        "record": pin(raw),
        "metadata": identity,
    }


def preconfig_observation(root, check):
    evidence = Path(root) / "evidence"
    output, output_meta = stable_raw(evidence / "preconfig.stdout", 1024 * 1024, check)
    errors, errors_meta = stable_raw(evidence / "preconfig.stderr", 1024 * 1024, check)
    exit_raw, exit_meta = stable_raw(evidence / "preconfig.exit.txt", 64, check)
    nested = [
        line
        for line in (output + b"\n" + errors).splitlines()
        if line.startswith(b"./Util/preconfig: ") and b" failed (status " in line
    ]
    require(
        exit_raw == b"0\n" and not nested,
        "original preconfig exit or nested generator failure was not successful",
    )
    return {
        "original_caller_exit": 0,
        "caller_invocation_limit": 1,
        "upstream_nested_failure_diagnostic_absent": True,
        "stdout": {**pin(output), "metadata": output_meta},
        "stderr": {**pin(errors), "metadata": errors_meta},
        "exit_record": {**pin(exit_raw), "metadata": exit_meta},
        "individual_nested_process_kernel_trace_claimed": False,
    }


def collect_smoke(root, touch, check):
    root = Path(root)
    evidence = root / "evidence"
    echo, _ = stable_raw(evidence / "echo.stdout", 65536, check)
    echo_log, _ = stable_raw(evidence / "echo-wrapper.log", 65536, check)
    touch_stdout, _ = stable_raw(evidence / "touch.stdout", 65536, check)
    touch_log, _ = stable_raw(evidence / "touch-wrapper.log", 65536, check)
    marker = root / "work" / "touch-marker"
    marker_data, marker_meta = stable_raw(marker, 1, check)
    require(echo == b"smoke-zsh\n", "echo output differs")
    require(
        echo_log.decode("utf-8").splitlines()
        == ["/bin/echo", "/bin/echo", "smoke-zsh"],
        "echo did not traverse exact EXEC_WRAPPER arguments",
    )
    require(touch_stdout == b"" and marker_data == b"", "touch marker/output differs")
    require(
        touch_log.decode("utf-8").splitlines() == [touch, "touch", str(marker)],
        "missing PATH traversal did not reach actual absolute touch",
    )
    require(
        not (root / "work" / "missing").exists()
        and list((root / "work" / "empty-cwd").iterdir()) == [],
        "PATH missing/empty candidates were not absent",
    )
    return {
        "interface": "EXEC_WRAPPER",
        "ZSH_EXEC_WRAPPER_environment_variable_used": False,
        "echo_wrapper": {"stdout": pin(echo), "wrapper_log": pin(echo_log)},
        "missing_path_touch_wrapper": {
            "stdout": pin(touch_stdout),
            "wrapper_log": pin(touch_log),
            "absolute_intercepted_command": touch,
            "marker": {
                "path": str(marker),
                **pin(marker_data),
                "metadata": marker_meta,
            },
        },
        "two_new_producer_smokes_passed": True,
        "ordinary_shell_only_smoke": False,
        "Rust_approval_protocol_executed": False,
        "original_seven_Mac_regressions_executed": False,
        "O_UNIQUE_or_skill_read_qualified": False,
    }


def collect_archive(root, check):
    root = Path(root)
    archive_path = root / "artifacts" / "codex-zsh-aarch64-apple-darwin.tar.gz"
    compressed, archive_metadata = stable_raw(archive_path, 32 * 1024 * 1024, check)
    require(compressed.startswith(b"\x1f\x8b"), "archive is not gzip")
    plain = bytearray()
    with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
        while True:
            check()
            chunk = stream.read(min(1024 * 1024, 129 * 1024 * 1024 + 1 - len(plain)))
            if not chunk:
                break
            plain.extend(chunk)
            require(
                len(plain) <= 129 * 1024 * 1024, "decompressed archive exceeds bound"
            )
    require(len(plain) % 512 == 0, "tar block length differs")
    required = {"codex-zsh", "codex-zsh/bin", "codex-zsh/bin/zsh"}
    members, executable, last_end = [], None, 0
    with tarfile.open(fileobj=io.BytesIO(plain), mode="r:") as archive:
        for item in archive:
            check()
            name = item.name.rstrip("/")
            safe_relative(name)
            require(
                name in required
                and name not in {row["name"] for row in members}
                and not item.issym()
                and not item.islnk()
                and not item.isdev()
                and not item.isfifo(),
                "unexpected archive member",
            )
            if name == "codex-zsh/bin/zsh":
                require(
                    item.isfile()
                    and item.mode == 0o755
                    and 0 < item.size <= 128 * 1024 * 1024,
                    "bad executable member",
                )
                stream = archive.extractfile(item)
                require(stream is not None, "executable data absent")
                executable = stream.read(item.size + 1)
                require(len(executable) == item.size, "incomplete executable")
            else:
                require(item.isdir() and item.size == 0, "bad package directory")
            members.append(
                {
                    "name": name,
                    "type": item.type.decode("ascii"),
                    "size": item.size,
                    "mode": item.mode,
                    "pax_headers": item.pax_headers,
                }
            )
            last_end = max(
                last_end, item.offset_data + ((item.size + 511) // 512) * 512
            )
    require(
        {row["name"] for row in members} == required and executable is not None,
        "archive member set differs",
    )
    require(
        len(plain) - last_end >= 1024 and not any(plain[last_end:]),
        "nonzero data after the exact tar members",
    )
    require(
        len(executable) >= 32 and executable[:4] == b"\xcf\xfa\xed\xfe",
        "not a thin little-endian Mach-O64 binary",
    )
    cpu, subtype, filetype = struct.unpack("<III", executable[4:16])
    require(cpu == 0x0100000C and filetype == 2, "not an ARM64 executable")
    command_count, command_bytes = struct.unpack("<II", executable[16:24])
    require(
        0 < command_count <= 1024 and 32 + command_bytes <= len(executable),
        "unbounded Mach-O load commands",
    )
    position, deployment = 32, []
    for _ in range(command_count):
        check()
        require(position + 8 <= 32 + command_bytes, "truncated Mach-O command")
        command, size = struct.unpack("<II", executable[position : position + 8])
        require(
            size >= 8 and size % 4 == 0 and position + size <= 32 + command_bytes,
            "invalid Mach-O command extent",
        )
        if command == 0x32:
            require(size >= 24, "truncated LC_BUILD_VERSION")
            target_platform, minimum, sdk, tool_count = struct.unpack(
                "<IIII", executable[position + 8 : position + 24]
            )
            require(
                target_platform == 1 and size == 24 + 8 * tool_count,
                "non-macOS build version",
            )
            deployment.append(
                {
                    "command": "LC_BUILD_VERSION",
                    "platform": target_platform,
                    "minimum": minimum,
                    "sdk": sdk,
                }
            )
        elif command == 0x24:
            require(size == 16, "invalid LC_VERSION_MIN_MACOSX")
            minimum, sdk = struct.unpack(
                "<II", executable[position + 8 : position + 16]
            )
            deployment.append(
                {
                    "command": "LC_VERSION_MIN_MACOSX",
                    "platform": 1,
                    "minimum": minimum,
                    "sdk": sdk,
                }
            )
        position += size
    require(
        position == 32 + command_bytes
        and len(deployment) == 1
        and deployment[0]["minimum"] == 0x000F0000,
        "binary minimum deployment target is not the admitted macOS15.0",
    )

    built = stable_digest(
        root / "work" / "zsh" / "Src" / "zsh", 128 * 1024 * 1024, check
    )
    staged = stable_digest(
        root / "work" / "codex-zsh" / "bin" / "zsh", 128 * 1024 * 1024, check
    )
    inner = pin(executable)
    require(
        all(
            built[key] == staged[key] == inner[key]
            for key in ("bytes", "sha256", "git_blob")
        ),
        "archive executable is not the just-built binary",
    )
    require(
        staged["metadata"]["mode"] & 0o777 == 0o755, "staged executable mode differs"
    )
    check()
    return {
        "archive": {
            "path": str(archive_path),
            **pin(compressed),
            "metadata": archive_metadata,
        },
        "gzip_complete": True,
        "archive_member_count": len(members),
        "members": members,
        "binary": {
            "path": "codex-zsh/bin/zsh",
            **inner,
            "mode": "100755",
            "format": "Mach-O64",
            "architecture": "arm64",
            "cpu_type": cpu,
            "cpu_subtype": subtype,
            "file_type": filetype,
            "deployment": deployment[0],
            "macOS15_native_executed": False,
        },
        "built": built,
        "staged": staged,
        "blake3": None,
        "immutable_provider": None,
        "release_tag": None,
        "DotSlash_manifest_updated": False,
        "promotion_accepted": False,
    }
