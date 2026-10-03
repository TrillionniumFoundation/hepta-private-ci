"""Install the declared workspace toolchain before read-only qualification."""

from pathlib import Path
import re
import subprocess
import tomllib

from verify_workspace_toolchain import verify_working_directory


def main() -> int:
    verify_working_directory(Path.cwd())
    declared = tomllib.loads(Path("rust-toolchain.toml").read_text())["toolchain"]
    pin = declared["channel"]
    components = declared["components"]
    if not isinstance(pin, str) or re.fullmatch(r"\d+\.\d+\.\d+", pin) is None:
        raise ValueError("workspace requires an exact numeric toolchain pin")
    if (
        not isinstance(components, list)
        or any(
            not isinstance(component, str)
            or re.fullmatch(r"[a-z][a-z0-9-]*", component) is None
            for component in components
        )
        or not {"clippy", "rustfmt"}.issubset(components)
    ):
        raise ValueError("workspace qualification requires declared clippy and rustfmt")
    command = [
        "rustup",
        "toolchain",
        "install",
        pin,
        "--profile",
        "minimal",
        "--no-self-update",
    ]
    for component in components:
        command.extend(["--component", component])
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
