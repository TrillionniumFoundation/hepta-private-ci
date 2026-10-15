#!/usr/bin/env python3
"""Fail closed if native Neuron qualification misses its direct local inputs.

GitHub path filters select whether an exact-head Rust CI run exists at all.
An omitted local dependency can leave an old green check after code changes.
This check discovers the direct Cargo dependencies of the two owner crates,
including workspace aliases and test-only dependencies, from actual manifests.
It does not replace the independent whole-repository blocking-ci.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OWNER_MANIFESTS = (
    "codex-rs/hepta-infer-core/Cargo.toml",
    "codex-rs/hepta-infer-worker-host/Cargo.toml",
)
WORKFLOW = ".github/workflows/hepta-neuron-shared-feature-batch.yml"
STATIC_INPUTS = frozenset(
    {
        "codex-rs/Cargo.toml",
        "codex-rs/Cargo.lock",
        "codex-rs/rust-toolchain.toml",
        "codex-rs/.cargo/**",
        "codex-rs/clippy.toml",
        "codex-rs/rustfmt.toml",
        WORKFLOW,
        "scripts/check_neuron_qualification_triggers.py",
        "scripts/tests/test_neuron_qualification_triggers.py",
    }
)


def workflow_path_rules(workflow_source: str) -> set[str]:
    """Read only pull_request.paths; never confuse steps/strings with globs."""
    rules: list[str] = []
    in_paths = False
    for line in workflow_source.splitlines():
        if not in_paths:
            if line == "    paths:":
                in_paths = True
            continue
        match = re.fullmatch(r'      - "([^"\r\n]+)"', line)
        if match:
            rule = match.group(1)
            if rule.startswith("!"):
                raise ValueError("negated native qualification path filter")
            rules.append(rule)
        elif line.startswith("      #") or not line.strip():
            continue
        else:
            break
    if not rules or len(rules) != len(set(rules)):
        raise ValueError("missing or duplicated native qualification path rules")
    return set(rules)


def direct_local_inputs(root: Path) -> set[str]:
    """Resolve the owners' direct Cargo path and workspace-local dependencies."""
    workspace = tomllib.loads((root / "codex-rs/Cargo.toml").read_text())
    aliases = workspace["workspace"]["dependencies"]
    required: set[str] = set()
    for manifest_relative in OWNER_MANIFESTS:
        manifest = root / manifest_relative
        owner = tomllib.loads(manifest.read_text())
        required.add(f"{manifest.parent.relative_to(root).as_posix()}/**")
        dependency_sections = [owner]
        # Include target-specific dependency sections as well as ordinary ones.
        dependency_sections.extend(owner.get("target", {}).values())
        for section in dependency_sections:
            for kind in ("dependencies", "dev-dependencies", "build-dependencies"):
                for name, spec in section.get(kind, {}).items():
                    if not isinstance(spec, dict):
                        continue
                    if spec.get("workspace") is True:
                        inherited = aliases.get(name)
                        if inherited is None:
                            raise ValueError(f"missing workspace dependency definition: {name}")
                        # Registry workspace dependencies may be strings (for
                        # example serde_json = "1") and have no local path.
                        if isinstance(inherited, str):
                            continue
                        if not isinstance(inherited, dict):
                            raise ValueError(f"invalid workspace dependency definition: {name}")
                        dependency = inherited
                        dependency_base = root / "codex-rs"
                    else:
                        dependency = spec
                        dependency_base = manifest.parent
                    relative = dependency.get("path")
                    if relative is None:
                        continue
                    if not isinstance(relative, str) or not relative:
                        raise ValueError(f"invalid path dependency: {name}")
                    resolved = (dependency_base / relative).resolve(strict=True)
                    try:
                        package_dir = resolved.relative_to(root.resolve(strict=True))
                    except ValueError as exc:
                        raise ValueError(f"dependency escapes repository: {name}") from exc
                    if not (resolved / "Cargo.toml").is_file():
                        raise ValueError(f"missing local dependency manifest: {name}")
                    required.add(f"{package_dir.as_posix()}/**")
    return required


def missing_trigger_paths(root: Path, workflow_source: str) -> list[str]:
    rules = workflow_path_rules(workflow_source)
    required = direct_local_inputs(root) | STATIC_INPUTS
    return sorted(required - rules)


def main() -> int:
    root = REPO_ROOT
    workflow_source = (root / WORKFLOW).read_text(encoding="utf-8")
    missing = missing_trigger_paths(root, workflow_source)
    if missing:
        for rule in missing:
            print(f"UNQUALIFIED upstream input: {rule}")
        return 1
    print("Native Neuron qualification includes every direct local Cargo input and policy file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
