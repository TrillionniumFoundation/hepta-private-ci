#!/usr/bin/env python3
"""Prepare the one-shot platform.types closure patch for coherent Rama 0.3.0."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement anchor, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def rewrite_closure_patch() -> None:
    path = Path("scripts/platform_types_apply_closure_repair.py")
    text = path.read_text(encoding="utf-8")

    old_wire = '''    replace_once(
        "codex-rs/hepta-wire/src/platform_manifest_json.rs",
        ".set(index.checked_add(1).ok_or_else(|| StrictJsonError::InvalidValue(field))?);",
        ".set(index.checked_add(1).ok_or(StrictJsonError::InvalidValue(field))?);",
    )'''
    new_wire = '''    replace_once(
        "codex-rs/hepta-wire/src/platform_manifest_json.rs",
        """                depth = depth.checked_add(1).ok_or_else(|| {
                    PlatformManifestWireError::Wire(PlatformTypesWireError::DepthExceeded)
                })?;""",
        """                depth = depth.checked_add(1).ok_or(
                    PlatformManifestWireError::Wire(PlatformTypesWireError::DepthExceeded),
                )?;""",
    )'''
    if text.count(old_wire) != 1:
        raise SystemExit("closure patch: wire lint anchor drifted")
    text = text.replace(old_wire, new_wire)

    start = text.index("def repair_rama_manifest() -> None:\n")
    end = text.index("\n\ndef repair_registry_indexes() -> None:\n", start)
    rama_block = '''def repair_rama_manifest() -> None:
    replace_once(
        "codex-rs/network-proxy/Cargo.toml",
        """rama-core = { version = "=0.3.0-alpha.4" }
rama-http = { version = "=0.3.0-alpha.4" }
rama-http-backend = { version = "=0.3.0-alpha.4", features = ["tls"] }
rama-net = { version = "=0.3.0-alpha.4", features = ["http", "tls"] }
rama-socks5 = { version = "=0.3.0-alpha.4" }
rama-tcp = { version = "=0.3.0-alpha.4", features = ["http"] }
rama-tls-rustls = { version = "=0.3.0-alpha.4", features = ["http"] }""",
        """# Rama 0.3.0 is one coherent release train. Exact direct constraints
# prevent a later lock refresh from mixing private support APIs.
rama-core = { version = "=0.3.0" }
rama-error = "=0.3.0"
rama-http = { version = "=0.3.0" }
rama-http-backend = { version = "=0.3.0", features = ["tls"] }
rama-macros = "=0.3.0"
rama-net = { version = "=0.3.0", features = ["http", "tls"] }
rama-socks5 = { version = "=0.3.0" }
rama-tcp = { version = "=0.3.0", features = ["http"] }
rama-tls-rustls = { version = "=0.3.0", features = ["http"] }
rama-utils = "=0.3.0"""",
    )
    replace_once(
        "codex-rs/network-proxy/Cargo.toml",
        'rama-unix = { version = "=0.3.0-alpha.4" }',
        'rama-unix = { version = "=0.3.0" }',
    )
'''
    text = text[:start] + rama_block + text[end:]
    path.write_text(text, encoding="utf-8")


def rewrite_lock_guard() -> None:
    guard = Path("scripts/platform_types_rama_lock_guard.py")
    replace_once(
        guard,
        '"""Reject incoherent Rama prerelease selections in platform.types qualification."""',
        '"""Reject incoherent Rama release selections in platform.types qualification."""',
    )
    replace_once(guard, 'EXPECTED_VERSION = "0.3.0-alpha.4"', 'EXPECTED_VERSION = "0.3.0"')

    tests = Path("scripts/test_platform_types_rama_lock_guard.py")
    text = tests.read_text(encoding="utf-8")
    text = text.replace("exact Rama prerelease graph", "exact Rama release graph")
    text = text.replace("stable_error", "wrong_error")
    text = text.replace('version = "0.3.0" if wrong_error', 'version = "0.3.0-alpha.4" if wrong_error')
    text = text.replace("test_coherent_exact_prerelease_graph_passes", "test_coherent_exact_release_graph_passes")
    text = text.replace("test_stable_support_crate_is_rejected", "test_mixed_support_crate_version_is_rejected")
    tests.write_text(text, encoding="utf-8")


def main() -> None:
    rewrite_closure_patch()
    rewrite_lock_guard()
    subprocess.run(
        [sys.executable, "scripts/platform_types_apply_closure_repair.py"],
        check=True,
    )
    print("platform.types stable Rama preparation: applied")


if __name__ == "__main__":
    main()
