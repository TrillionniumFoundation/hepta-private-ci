#!/usr/bin/env python3
"""Read-only DAG guard for Windows proxy/sandbox integration-test isolation.

This is a structural preflight, not a substitute for real Cargo/Bazel builds.
The Windows restricted-token ingress regression must remain executable from a
leaf crate, never a dev dependency of the protocol-facing proxy library.
"""
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
CRATES = ROOT / "codex-rs"


def manifest(relative):
    return tomllib.loads((CRATES / relative / "Cargo.toml").read_text(encoding="utf-8"))


def one_package(lock, name):
    matches = [p for p in lock["package"] if p["name"] == name and p["version"] == "0.0.0"]
    if len(matches) != 1:
        raise AssertionError(f"missing unique locked workspace package {name}")
    return matches[0]


def main():
    proxy = manifest("network-proxy")
    cli = manifest("cli")
    sandbox = manifest("windows-sandbox-rs")
    deps = proxy["dependencies"]
    if "codex-windows-sandbox" in deps or "codex_windows_sandbox" in deps:
        raise AssertionError("proxy runtime must not own Windows sandbox")
    for target in proxy.get("target", {}).values():
        for kind in ("dependencies", "dev-dependencies", "build-dependencies"):
            if any("windows-sandbox" in key for key in target.get(kind, {})):
                raise AssertionError("proxy cannot import Windows sandbox via any Cargo target")
    if "codex-protocol" not in sandbox["dependencies"]:
        raise AssertionError("Windows sandbox must retain real protocol boundary")
    leaf = cli.get("target", {}).get("cfg(windows)", {}).get("dev-dependencies", {})
    if "codex-network-proxy" not in leaf:
        raise AssertionError("CLI Windows leaf must exercise real network-proxy")
    if not any("windows-sandbox" in name for name in
               cli.get("target", {}).get('cfg(target_os = "windows")', {})
               .get("dependencies", {})):
        raise AssertionError("CLI must retain real Windows sandbox dependency")
    test = CRATES / "cli/tests/windows_stable_ingress.rs"
    if (not test.is_file() or
            (CRATES / "network-proxy/tests/windows_stable_ingress.rs").exists()):
        raise AssertionError("Windows proxy test must have exactly one leaf owner")
    body = test.read_text(encoding="utf-8")
    for required in (
        '#![cfg(target_os = "windows")]',
        "restricted_tokens_select_stable_routes_and_cleanup",
        "restricted_child_exercises_http_and_socks",
        "create_readonly_token_with_caps_and_user_from",
        "codex_network_proxy::",
        "codex_windows_sandbox::",
    ):
        if required not in body:
            raise AssertionError("Windows proxy regression lost required coverage: " + required)
    lock = tomllib.loads((CRATES / "Cargo.lock").read_text(encoding="utf-8"))
    proxy_locked = one_package(lock, "codex-network-proxy")
    cli_locked = one_package(lock, "codex-cli")
    if "codex-windows-sandbox" in proxy_locked["dependencies"]:
        raise AssertionError("locked Cargo graph restores protocol/proxy/sandbox cycle")
    if "codex-network-proxy" not in cli_locked["dependencies"]:
        raise AssertionError("locked CLI test must own real proxy dependency")
    if "codex-windows-sandbox" not in cli_locked["dependencies"]:
        raise AssertionError("locked CLI must keep real Windows sandbox dependency")
    print("PASS: full restricted-token Windows ingress moved to CLI; library DAG cycle absent")


if __name__ == "__main__":
    main()
