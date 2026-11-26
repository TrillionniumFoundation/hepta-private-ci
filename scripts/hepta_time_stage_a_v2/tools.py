"""Observe fixed native tools and retain the actual formatter payload identity."""

import io
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import tarfile

from . import contract as c
from .runtime import json_value, put, put_raw, require, sha256, stable_read


def prepare_tools(ctx, spec):
    require(spec["tool_payloads"] == c.TOOL_PAYLOADS, "official payload pins changed")
    require(
        os.environ.get("RUSTUP_TOOLCHAIN") == "1.96.0"
        and os.environ.get("PYTHONDONTWRITEBYTECODE") == "1",
        "fixed toolchain or no-bytecode environment absent",
    )
    steps = json_value(os.environ["STAGE_A_TOOL_STEPS"].encode())
    require(
        all(
            steps.get(name, {}).get("outcome") == "success"
            for name in ("job_scope", "checkout", "source", "rust", "rust_tools")
        ),
        "an original tool installation step failed or was skipped",
    )
    tools_dir = ctx.evidence.parent / "tools"
    tools_dir.mkdir()
    payload_dir = tools_dir / "payloads"
    payload_dir.mkdir()
    bin_dir = tools_dir / "bin"
    bin_dir.mkdir()
    observations = {"action_steps": steps, "payloads": {}, "versions": []}
    for name in ("bazel", "dotslash"):
        pin = c.TOOL_PAYLOADS[name]
        downloaded = payload_dir / name
        cap = c.PHASE_CAPS["download-" + name]
        transport_cap = min(float(cap) - 2.0, ctx.remaining() - 5.0)
        require(transport_cap > 0, "no tool transport budget")
        argv = [
            "/usr/bin/curl",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--retry",
            "0",
            "--connect-timeout",
            "10",
            "--max-time",
            str(transport_cap),
            "--max-filesize",
            str(pin["bytes"]),
            "--output",
            str(downloaded),
            pin["url"],
        ]
        download_record, _ = ctx.command("download-" + name, argv, cap)
        data, _ = stable_read(downloaded, 80 * 1024 * 1024)
        require(
            len(data) == pin["bytes"] and sha256(data) == pin["sha256"],
            "official tool payload bytes or digest changed: " + name,
        )
        if name == "bazel":
            executable_data = data
            target = tools_dir / "bazel.real"
        else:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                members = archive.getmembers()
                require(0 < len(members) <= 16, "unexpected DotSlash archive size")
                for member in members:
                    path = PurePosixPath(member.name)
                    require(
                        not path.is_absolute()
                        and ".." not in path.parts
                        and not member.issym()
                        and not member.islnk()
                        and (member.isfile() or member.isdir())
                        and member.size <= 8 * 1024 * 1024,
                        "unsupported DotSlash archive member",
                    )
                selected = [
                    member
                    for member in members
                    if member.isfile() and PurePosixPath(member.name).name == "dotslash"
                ]
                require(len(selected) == 1, "DotSlash archive lacks one executable")
                stream = archive.extractfile(selected[0])
                require(stream is not None, "DotSlash payload cannot be read")
                executable_data = stream.read(8 * 1024 * 1024 + 1)
                require(
                    len(executable_data) == selected[0].size,
                    "DotSlash extracted size changed",
                )
            target = bin_dir / "dotslash"
        require(
            executable_data[:4] == b"\x7fELF"
            and executable_data[4:6] == b"\x02\x01"
            and executable_data[18:20] == b"\x3e\x00",
            "tool is not the pinned native x86-64 ELF",
        )
        binary_pin = put_raw(target, executable_data)
        target.chmod(0o755)
        observations["payloads"][name] = {
            "official_asset": pin,
            "extracted_binary": binary_pin,
            "download_execution": download_record,
        }
    # A disclosed two-line launcher makes every original just bazel command
    # use foreground batch mode. It changes no repository source and prevents
    # a persistent Bazel server from escaping command ownership.
    wrapper = (
        "#!/bin/sh\nexec "
        + shlex.quote(str(tools_dir / "bazel.real"))
        + (
            " --batch --output_user_root="
            + shlex.quote(str(tools_dir / "bazel-user-root"))
            + ' "$@"\n'
        )
    )
    wrapper_path = bin_dir / "bazel"
    observations["bazel_batch_launcher"] = put_raw(wrapper_path, wrapper.encode())
    wrapper_path.chmod(0o755)
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]
    os.environ["DOTSLASH_CACHE"] = str(tools_dir / "dotslash-cache")
    os.environ["BAZEL_OUTPUT_USER_ROOT"] = str(tools_dir / "bazel-user-root")
    cases = (
        ("cargo", ["cargo", "--version", "--verbose"]),
        ("rustc", ["rustc", "--version", "--verbose"]),
        ("just", ["just", "--version"]),
        ("nextest", ["cargo", "nextest", "--version"]),
        ("rustfmt", ["rustfmt", "--version"]),
        ("clippy", ["cargo", "clippy", "--version"]),
        ("bazel", [str(tools_dir / "bazel.real"), "--version"]),
        ("dotslash", ["dotslash", "--version"]),
    )
    for name, argv in cases:
        record, raw = ctx.command("version-" + name, argv, c.PHASE_CAPS["version"])
        lines = raw.decode("utf-8").splitlines()
        require(lines, "empty tool-version observation")
        if name in ("cargo", "rustc"):
            require(
                re.fullmatch(name + r" 1\.96\.0(?: \([^\r\n]*\))?", lines[0])
                is not None
                and lines.count("release: 1.96.0") == 1
                and lines.count("host: x86_64-unknown-linux-gnu") == 1,
                "wrong Rust/Cargo native release",
            )
        elif name == "nextest":
            require(
                lines
                == [
                    "cargo-nextest 0.9.103 (d2e7b879f 2025-08-25)",
                    "release: 0.9.103",
                    "commit-hash: d2e7b879fb79975e8b47a8e3ce569b651e6381c0",
                    "commit-date: 2025-08-25",
                    "host: x86_64-unknown-linux-gnu",
                ],
                "nextest release/hash/date/host differs from the fixed official binary",
            )
        elif name == "just":
            require(lines == ["just 1.51.0"], "wrong just release")
        elif name == "bazel":
            require(lines == ["bazel 9.3.0"], "wrong Bazel payload release")
        elif name == "dotslash":
            require(lines == ["DotSlash 0.5.9"], "wrong DotSlash payload release")
        elif name == "clippy":
            require(
                len(lines) == 1 and lines[0].startswith("clippy 0.1.96 "),
                "clippy does not belong to the fixed Rust release",
            )
        else:
            require(
                len(lines) == 1 and lines[0].startswith("rustfmt "),
                "rustfmt component version was not observed",
            )
        observations["versions"].append(
            {"tool": name, "lines": lines, "execution": record}
        )
    put(ctx.evidence / "tool-observations.json", observations)
    return observations


def observe_buildifier(ctx):
    _, buildifier_path_log = ctx.command(
        "buildifier-cache-path",
        ["dotslash", "--", "get-extracted-cache-path", "tools/buildifier"],
        c.PHASE_CAPS["version"],
    )
    buildifier_lines = buildifier_path_log.decode("utf-8").splitlines()
    require(
        len(buildifier_lines) == 1, "buildifier cache path is not one original value"
    )
    buildifier_path = Path(buildifier_lines[0])
    require(
        buildifier_path.is_absolute()
        and buildifier_path.is_relative_to(Path(os.environ["DOTSLASH_CACHE"])),
        "buildifier was located outside the owned DotSlash cache",
    )
    buildifier_raw, _ = stable_read(buildifier_path, 8 * 1024 * 1024)
    wrapper_raw, _ = stable_read(ctx.root / "tools/buildifier")
    wrapper_document = json_value(wrapper_raw.split(b"\n", 1)[1])
    payload = wrapper_document["platforms"]["linux-x86_64"]
    require(
        payload["size"] == len(buildifier_raw) == 7757842
        and payload["hash"] == "sha256"
        and payload["digest"]
        == sha256(buildifier_raw)
        == "887377fc64d23a850f4d18a077b5db05b19913f4b99b270d193f3c7334b5a9a7"
        and payload["providers"]
        == [
            {
                "url": "https://github.com/bazelbuild/buildtools/releases/download/v8.5.1/buildifier-linux-amd64"
            }
        ],
        "actual formatter binary differs from the pinned buildifier 8.5.1 payload",
    )
    put(
        ctx.evidence / "formatted-buildifier-binary.json",
        {
            "bytes": len(buildifier_raw),
            "sha256": sha256(buildifier_raw),
            "dotSlash_manifest_sha256": sha256(wrapper_raw),
            "official_release": c.EXPECTED_TOOLS["buildifier"],
            "version_string_not_substituted_for_binary_identity": True,
        },
    )
