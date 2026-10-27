"""Frozen native ARM64 image/tool authority; no implicit host or tag fallback."""

import os
from pathlib import Path
import re

from .files import SHA256, read_json, relative, verify


SCHEMA = "hepta.synapse.linux.builder-seal.v1"
PLATFORM = "linux/arm64"
TARGET = "aarch64-unknown-linux-gnu"
SYNAPSE_REF = "matrixdotorg/synapse@sha256:467a587a5052dadd5d0bf1f8d89f043cc652d5201bca510307340f8dddb6b312"
SYNAPSE_ID = "sha256:d1292ef4b8d934a5b2acc9471eeabc53f718dd748cf10773454f401f678db784"
SYNAPSE_VERSION = "1.159.0"
SYNAPSE_REVISION = "7b10e6b9bc2dacc33f0974c999f640b55ef831bc"
RUST_BASE_REF = "docker.io/library/rust@sha256:05f85ef6eb0f2600ac62e9d779642b5b362d5be2ed67b80e162fae6e28b66524"
RUST_BASE_ID = "sha256:e1c74d1ab074f9e6696ae7b759e9c522b1517b32c5a30cc567b3f11f8c3e1be0"
TEST_NAME = "real_synapse_dual_agentd_dual_matrixd_restart_and_isolation"
TEST_BINARY_ID = "codex-hepta-matrixd::real_synapse_e2e"
ENTRY = "codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse-linux.py"
PROXY = "codex-rs/hepta-matrixd/tests/fixtures/synapse-loopback-proxy.py"
TOOLS = {
    "python3",
    "git",
    "rustc",
    "cargo",
    "rustdoc",
    "cargo-nextest",
    "just",
    "bash",
    "sh",
    "cc",
    "c++",
    "ar",
    "ld",
    "ranlib",
    "cmake",
    "make",
    "pkg-config",
    "ps",
    "kill",
    "env",
    "uname",
    "cat",
    "chmod",
    "cp",
    "cut",
    "date",
    "dirname",
    "find",
    "grep",
    "head",
    "ln",
    "mkdir",
    "mv",
    "nm",
    "perl",
    "rm",
    "sed",
    "sort",
    "strip",
    "tail",
    "touch",
    "tr",
    "wc",
    "xargs",
    "readelf",
    "ldd",
    "as",
    "objcopy",
    "objdump",
    "dotslash",
    "bwrap",
}
IMAGE_ROOTS = ("/usr/", "/bin/", "/sbin/", "/lib/", "/lib64/", "/opt/")


def exact_keys(value, names, label):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError(f"Unexpected or missing {label} fields")


def image_identity(image):
    base = {"reference", "config_id", "os", "architecture"}
    if set(image) == base:
        if not re.fullmatch(
            r"[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}", image["reference"]
        ):
            raise ValueError("Builder must use an immutable OCI manifest reference")
    elif set(image) == base | {
        "archive",
        "base_reference",
        "base_config_id",
        "preparation_inputs_sha256",
    }:
        if (
            image["reference"] != image["config_id"]
            or image["base_reference"] != RUST_BASE_REF
            or image["base_config_id"] != RUST_BASE_ID
        ):
            raise ValueError(
                "Derived builder must bind its actual config ID and the original Rust base"
            )
        exact_keys(
            image["archive"], ("bytes", "sha256"), "complete derived image archive"
        )
        if (
            type(image["archive"]["bytes"]) is not int
            or image["archive"]["bytes"] <= 0
            or not SHA256.fullmatch(image["archive"]["sha256"])
            or not SHA256.fullmatch(image["preparation_inputs_sha256"])
        ):
            raise ValueError(
                "Derived builder archive/preparation inputs lack fixed byte identities"
            )
    else:
        raise ValueError("Unexpected builder image authority fields")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image["config_id"]):
        raise ValueError("Builder config/ImageID must be frozen")
    if (image["os"], image["architecture"]) != ("linux", "arm64"):
        raise ValueError("This qualification supports native Linux ARM64 only")


def tool_identity(tool):
    exact_keys(tool, ("path", "bytes", "sha256"), "tool")
    path = Path(tool["path"])
    if not path.is_absolute() or ".." in path.parts or path.as_posix() != tool["path"]:
        raise ValueError("Tool path must be absolute and canonical")
    if (
        type(tool["bytes"]) is not int
        or tool["bytes"] <= 0
        or not SHA256.fullmatch(tool["sha256"])
    ):
        raise ValueError("Tool byte identity must be frozen")


def load_contract(path, expected_sha):
    if not isinstance(expected_sha, str) or not SHA256.fullmatch(expected_sha):
        raise ValueError("Builder contract requires its independent frozen SHA-256")
    value = read_json(path, expected_sha)
    exact_keys(
        value,
        (
            "schema",
            "image",
            "target",
            "rust_release",
            "nextest_version",
            "tools",
            "tool_bundle",
            "control_docker",
            "synapse",
        ),
        "builder seal",
    )
    if (
        value["schema"],
        value["target"],
        value["rust_release"],
        value["nextest_version"],
    ) != (SCHEMA, TARGET, "1.96.0", "0.9.103"):
        raise ValueError(
            "Builder schema, native target or qualification toolchain differs"
        )
    image_identity(value["image"])
    if set(value["tools"]) != TOOLS:
        raise ValueError("Builder tool set differs from the reviewed closed set")
    bundle = value["tool_bundle"]
    exact_keys(bundle, ("mount_path", "files"), "external tool bundle")
    if bundle["mount_path"] != "/hepta-tools" or not isinstance(bundle["files"], dict):
        raise ValueError("External tools must use the explicit read-only bundle mount")
    for name, identity in bundle["files"].items():
        relative(name)
        exact_keys(identity, ("bytes", "sha256"), "bundle file")
        if (
            type(identity["bytes"]) is not int
            or identity["bytes"] < 0
            or not SHA256.fullmatch(identity["sha256"])
        ):
            raise ValueError("Invalid tool-bundle file identity")
    for tool in value["tools"].values():
        tool_identity(tool)
        path = tool["path"]
        if path.startswith("/hepta-tools/"):
            name = path.removeprefix("/hepta-tools/")
            if bundle["files"].get(name) != {
                key: tool[key] for key in ("bytes", "sha256")
            }:
                raise ValueError("External tool is not in the complete sealed bundle")
        elif not path.startswith(IMAGE_ROOTS):
            raise ValueError(
                "Tool lies outside immutable image roots and sealed bundle"
            )
    tool_identity(value["control_docker"])
    if value["control_docker"]["path"] != "/hepta-control/docker":
        raise ValueError(
            "Privileged transport Docker client must use its separate control mount"
        )
    if value["synapse"] != {
        "reference": SYNAPSE_REF,
        "config_id": SYNAPSE_ID,
        "version": SYNAPSE_VERSION,
        "revision": SYNAPSE_REVISION,
        "platform": PLATFORM,
    }:
        raise ValueError(
            "The original Synapse immutable platform identity cannot change"
        )
    return value


def verify_tools(contract):
    """Inside image: resolve and hash actual executables, never ambient PATH."""
    observed = {}
    for name, tool in contract["tools"].items():
        path = Path(tool["path"])
        if path.resolve(strict=True) != path or not os.access(path, os.X_OK):
            raise ValueError(f"Tool is not the exact canonical executable: {name}")
        verify(path, {key: tool[key] for key in ("bytes", "sha256")})
        observed[name] = tool
    return observed


def validate_image_inspect(inspected, expected):
    if len(inspected) != 1:
        raise ValueError("Expected one exact materialized image")
    image = inspected[0]
    if (image["Id"], image["Os"], image["Architecture"]) != (
        expected["config_id"],
        expected["os"],
        expected["architecture"],
    ):
        raise ValueError("Actual builder image identity/platform differs")
    if expected["reference"] != expected["config_id"]:

        def normalized(reference):
            return reference.removeprefix("docker.io/library/").removeprefix(
                "docker.io/"
            )

        if normalized(expected["reference"]) not in {
            normalized(item) for item in image.get("RepoDigests", [])
        }:
            raise ValueError("Exact immutable image reference is not materialized")


def reject_compiler_overrides(environment):
    fixed = {
        "RUSTC",
        "RUSTDOC",
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
        "CARGO_BUILD_RUSTC",
        "CARGO_BUILD_RUSTC_WRAPPER",
        "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
    }
    bad = [
        name
        for name in environment
        if name in fixed
        or name.startswith("CARGO_PROFILE_")
        or (
            name.startswith("CARGO_TARGET_")
            and name.endswith(("_RUSTFLAGS", "_LINKER"))
        )
    ]
    if bad:
        raise ValueError(
            f"Inherited compiler/loader/profile overrides are forbidden: {sorted(bad)}"
        )
