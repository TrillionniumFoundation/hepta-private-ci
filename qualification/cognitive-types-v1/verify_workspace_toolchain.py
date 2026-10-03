"""Require the active workspace toolchain to match its repository pin."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def verify_identity(pin: str, active: str, rustc: str, cargo: str) -> None:
    if re.fullmatch(r"\d+\.\d+\.\d+", pin) is None:
        raise ValueError("workspace requires an exact numeric toolchain pin")
    selected = active.split()[0] if active.split() else ""
    if selected != pin and not selected.startswith(pin + "-"):
        raise ValueError("active Rust toolchain does not match workspace pin")
    for name, identity in (("rustc", rustc), ("cargo", cargo)):
        release = re.search(r"(?m)^release: (\S+)$", identity)
        if release is None or release.group(1) != pin:
            raise ValueError(f"{name} release does not match workspace pin")


def verify_working_directory(directory: Path, root: Path = ROOT) -> None:
    if directory.resolve() != (root / "codex-rs").resolve():
        raise ValueError("Rust qualification must run from codex-rs")


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] not in {"fmt", "check", "clippy", "test"}:
        raise ValueError("only workspace fmt/check/clippy/test commands are allowed")
    verify_working_directory(Path.cwd())
    settings = tomllib.loads(Path("rust-toolchain.toml").read_text())["toolchain"]
    pin = settings["channel"]
    if not isinstance(pin, str) or re.fullmatch(r"\d+\.\d+\.\d+", pin) is None:
        raise ValueError("workspace requires an exact numeric toolchain pin")
    components = settings.get("components", [])
    if not isinstance(components, list) or any(
        not isinstance(item, str) or re.fullmatch(r"[a-z][a-z0-9_-]*", item) is None
        for item in components
    ):
        raise ValueError("toolchain components must be a list of component names")
    # Only the explicit setup invocation may install; proxies must fail closed.
    environment = {**os.environ, "RUSTUP_TOOLCHAIN": pin, "RUSTUP_AUTO_INSTALL": "0"}
    if not arguments:
        install = ["rustup", "toolchain", "install", pin, "--profile", "minimal", "--no-self-update"]
        for component in components:
            install.extend(["--component", component])
        subprocess.run(install, env=environment, check=True)
    active = subprocess.check_output(["rustup", "show", "active-toolchain"], text=True, env=environment)
    rustc = subprocess.check_output(["rustc", "--version", "--verbose"], text=True, env=environment)
    cargo = subprocess.check_output(["cargo", "--version", "--verbose"], text=True, env=environment)
    clippy = subprocess.check_output(["cargo", "clippy", "--version"], text=True, env=environment)
    verify_identity(pin, active, rustc, cargo)
    if components:
        listing = subprocess.check_output(
            ["rustup", "component", "list", "--installed", "--toolchain", pin],
            text=True, env=environment,
        )
        installed = {line.split()[0] for line in listing.splitlines() if line.strip()}
        host = active.split()[0].removeprefix(pin + "-")
        if any(item not in installed and item + "-" + host not in installed for item in components):
            raise ValueError("declared toolchain component is not installed")
    print(json.dumps({"declared_pin": pin, "active_toolchain": active.strip(),
                      "rustc": rustc.strip(), "cargo": cargo.strip(),
                      "clippy": clippy.strip(), "workspace_pin_verified": True}, sort_keys=True), flush=True)
    if arguments:
        return subprocess.run(["cargo", *arguments], cwd=ROOT / "codex-rs",
                              env=environment, check=False).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
