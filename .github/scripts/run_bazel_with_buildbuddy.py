#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from collections.abc import Sequence
from pathlib import Path


OPENAI_REPOSITORY = "openai/codex"
# Remote configurations select cache/BES/download endpoints. Their -rbe forms
# also select the matching remote executor endpoint.
GENERIC_REMOTE_CONFIG = "buildbuddy-generic"
OPENAI_REMOTE_CONFIG = "buildbuddy-openai"
# These CI configurations require remote build execution. The wrapper supplies
# an RBE configuration, which also includes the common `remote` settings.
REMOTE_EXECUTION_CONFIGS = {
    "--config=ci-linux",
    "--config=ci-macos",
    "--config=ci-v8",
    "--config=ci-windows-cross",
}
# A keyless Windows cross build must reconstruct the local half of the split
# declared by `ci-windows-cross`: MSVC executes host-loaded actions while the
# target remains GNU LLVM. The custom test toolchain is required because Bazel
# otherwise insists that a test's execution and target platforms are equal.
LOCAL_WINDOWS_MSVC_EXEC_PLATFORM = "//:windows_x86_64_msvc"
LOCAL_WINDOWS_MSVC_CC_TOOLCHAIN = "//:local_windows_msvc_cc_toolchain"
LOCAL_WINDOWS_GNULLVM_TEST_TOOLCHAIN = (
    "//:windows_gnullvm_tests_on_msvc_host_toolchain"
)
# Honor either explicit setting so the wrapper never overrides the caller's
# choice when it supplies the CI default below.
REMOTE_REPO_CONTENTS_CACHE_STARTUP_OPTIONS = {
    "--experimental_remote_repo_contents_cache",
    "--noexperimental_remote_repo_contents_cache",
}


def startup_args(args: Sequence[str], env: Mapping[str, str]) -> list[str]:
    """Return shared startup options that are missing from a Bazel invocation.

    Bazel startup options must precede the command, and changing them restarts
    the server and discards its analysis cache. GitHub Actions invokes Bazel
    through several helpers, so normalize their startup options here while
    preserving any explicit choice made by the caller.
    """
    command_idx = next(
        (idx for idx, arg in enumerate(args) if not arg.startswith("-")),
        len(args),
    )
    configured_startup_args = args[:command_idx]
    injected_args = []

    output_user_root = env.get("BAZEL_OUTPUT_USER_ROOT")
    if output_user_root and not any(
        arg.startswith("--output_user_root=") for arg in configured_startup_args
    ):
        injected_args.append(f"--output_user_root={output_user_root}")

    if env.get("GITHUB_ACTIONS") == "true" and not any(
        arg in REMOTE_REPO_CONTENTS_CACHE_STARTUP_OPTIONS
        for arg in configured_startup_args
    ):
        # Work around Bazel 9 overlay materialization failures seen in CI. This
        # disables only the startup-level repo contents cache; keyed runs still
        # use BuildBuddy.
        injected_args.append("--noexperimental_remote_repo_contents_cache")

    return injected_args


# Only authenticated workflow runs executing trusted upstream code may use the
# OpenAI BuildBuddy host. A pull request event without proof that its head is
# in the upstream repository fails closed to the generic host.
def is_trusted_upstream_run(env: Mapping[str, str]) -> bool:
    # `GITHUB_REPOSITORY` is easy to set locally. Requiring GitHub's workflow
    # marker prevents a local command from opting itself into the OpenAI host.
    if (
        env.get("GITHUB_ACTIONS") != "true"
        or env.get("GITHUB_REPOSITORY") != OPENAI_REPOSITORY
    ):
        return False
    # Non-PR workflow runs in `openai/codex` execute upstream refs, so they are
    # trusted. Fork code reaches these workflows only through pull requests.
    if env.get("GITHUB_EVENT_NAME") != "pull_request":
        return True

    event_path = env.get("GITHUB_EVENT_PATH")
    if not event_path:
        return False
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    try:
        return event["pull_request"]["head"]["repo"]["fork"] is False
    except (KeyError, TypeError):
        return False


def uses_openai_host(env: Mapping[str, str]) -> bool:
    return bool(env.get("BUILDBUDDY_API_KEY")) and is_trusted_upstream_run(env)


def uses_remote_execution(args: Sequence[str]) -> bool:
    try:
        separator_idx = args.index("--")
    except ValueError:
        separator_idx = len(args)
    return any(arg in REMOTE_EXECUTION_CONFIGS for arg in args[:separator_idx])


def remote_config(args: Sequence[str], env: Mapping[str, str]) -> str | None:
    if not env.get("BUILDBUDDY_API_KEY"):
        return None

    config = OPENAI_REMOTE_CONFIG if uses_openai_host(env) else GENERIC_REMOTE_CONFIG
    if uses_remote_execution(args):
        config += "-rbe"
    return config


def option_contains_value(args: Sequence[str], option: str, value: str) -> bool:
    """Return whether a repeatable Bazel option already contains `value`."""
    for idx, arg in enumerate(args):
        encoded: str | None = None
        if arg == option and idx + 1 < len(args):
            encoded = args[idx + 1]
        elif arg.startswith(f"{option}="):
            encoded = arg.split("=", 1)[1]
        if encoded is not None and value in encoded.split(","):
            return True
    return False


def bazel_args_without_remote_execution(
    args: Sequence[str], env: Mapping[str, str]
) -> list[str]:
    """Remove credentialed RBE configs and select a coherent local Windows ABI.

    The pinned hermetic LLVM toolchain builds GNU Windows target C/C++ inputs,
    while native MSVC Rust targets and host-loaded proc macros must consume
    archives produced by the installed MSVC compiler. A keyless cross request
    therefore pairs an MSVC host/exec platform with a gnullvm target. A native
    MSVC request keeps its MSVC target and receives the same ABI-scoped local
    C/C++ toolchain. Explicit platform choices and arguments after ``--``
    remain owned by the caller.
    """
    try:
        separator_idx = args.index("--")
    except ValueError:
        separator_idx = len(args)

    prefix = list(args[:separator_idx])
    requested_windows_cross = "--config=ci-windows-cross" in prefix
    requested_native_windows_msvc = (
        option_contains_value(prefix, "--host_platform", "//:local_windows_msvc")
        or option_contains_value(prefix, "--platforms", "//:windows_x86_64_msvc")
    )
    prefix = [arg for arg in prefix if arg not in REMOTE_EXECUTION_CONFIGS]
    suffix = list(args[separator_idx:])
    if env.get("RUNNER_OS") != "Windows":
        return [*prefix, *suffix]

    command_idx = next(
        (idx for idx, arg in enumerate(prefix) if not arg.startswith("-")),
        None,
    )
    # Queries and administrative commands do not configure build actions.
    # Do not inject CI build options or runtime skip filters into those calls.
    if command_idx is None or prefix[command_idx] not in {
        "build",
        "test",
        "run",
        "coverage",
        "cquery",
        "aquery",
        "info",
    }:
        return [*prefix, *suffix]

    injected_args: list[str] = []
    if "--config=ci-windows" not in prefix and (
        requested_windows_cross
        or not any(arg.startswith("--config=") for arg in prefix)
    ):
        injected_args.append("--config=ci-windows")
    if requested_windows_cross:
        for option, platform in (
            ("--host_platform", "//:local_windows_msvc"),
            ("--platforms", "//:windows_x86_64_gnullvm"),
        ):
            if not any(arg == option or arg.startswith(f"{option}=") for arg in prefix):
                injected_args.append(f"{option}={platform}")
        for option, value in (
            ("--extra_execution_platforms", LOCAL_WINDOWS_MSVC_EXEC_PLATFORM),
            ("--extra_toolchains", LOCAL_WINDOWS_GNULLVM_TEST_TOOLCHAIN),
        ):
            if not option_contains_value(prefix, option, value):
                injected_args.append(f"{option}={value}")

    if requested_windows_cross or requested_native_windows_msvc:
        # Keep native archives on the same ABI as the Rust action that links
        # them. Without this bounded override, globally registered hermetic
        # LLVM can produce MinGW objects for an MSVC Rust target.
        for option, value in (
            ("--extra_toolchains", LOCAL_WINDOWS_MSVC_CC_TOOLCHAIN),
            ("--repo_env", "BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0"),
        ):
            if not option_contains_value(prefix, option, value):
                injected_args.append(f"{option}={value}")

    # Put defaults before caller options so a CI config cannot override an
    # explicit per-job cache path (or other later command-line setting).
    # Later --extra_toolchains also take precedence over the fallback compiler.
    return [
        *prefix[: command_idx + 1],
        *injected_args,
        *prefix[command_idx + 1 :],
        *suffix,
    ]


def bazel_args_with_remote_config(
    args: Sequence[str], env: Mapping[str, str]
) -> list[str]:
    command_idx = next(
        (idx for idx, arg in enumerate(args) if not arg.startswith("-")),
        None,
    )
    if command_idx is None:
        raise ValueError("expected a Bazel command")

    config = remote_config(args, env)
    if config is None:
        configured_args = bazel_args_without_remote_execution(args, env)
    else:
        # `remote_config()` returns a configuration only when this key is present.
        api_key = env["BUILDBUDDY_API_KEY"]
        remote_args = [
            f"--config={config}",
            f"--remote_header=x-buildbuddy-api-key={api_key}",
        ]

        # Insert immediately after the Bazel command. This keeps wrapper-added
        # options out of positional payloads and lets later CI configs override
        # shared RBE defaults such as the Windows cross-compilation exec platforms.
        configured_args = [
            *args[: command_idx + 1],
            *remote_args,
            *args[command_idx + 1 :],
        ]

    try:
        separator_idx = configured_args.index("--")
    except ValueError:
        separator_idx = len(configured_args)

    cache_args = [
        f"{option_prefix}{env[env_name]}"
        for env_name, option_prefix in (
            ("BAZEL_REPO_CONTENTS_CACHE", "--repo_contents_cache="),
            ("BAZEL_REPOSITORY_CACHE", "--repository_cache="),
        )
        if env.get(env_name)
        and not any(
            arg.startswith(option_prefix) for arg in configured_args[:separator_idx]
        )
    ]
    return [
        *configured_args[:separator_idx],
        *cache_args,
        *configured_args[separator_idx:],
    ]


def bazel_command(*args: str, env: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if env is None else env
    bazel = env.get("CODEX_BAZEL_BIN", "bazel")
    return [bazel, *startup_args(args, env), *bazel_args_with_remote_config(args, env)]


def main() -> None:
    config = remote_config(sys.argv[1:], os.environ)
    if config is None:
        print(
            "BuildBuddy key unavailable; using local Bazel configuration.",
            file=sys.stderr,
        )
    else:
        host_description = (
            "OpenAI tenant" if uses_openai_host(os.environ) else "generic"
        )
        print(
            f"Using {host_description} BuildBuddy configuration: {config}.",
            file=sys.stderr,
        )

    command = bazel_command(*sys.argv[1:])
    if os.name == "nt":
        # Windows CRT exec can split arguments containing spaces and lose the
        # eventual child exit status. Wait for Bazel and propagate its status.
        result = subprocess.run(command, check=False)
        raise SystemExit(result.returncode)

    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
