#!/usr/bin/env python3
"""Hostile probes for the temporary r7 dependency-inference repair."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

EXECUTOR = Path("scripts/hepta-global-finalizer-r7.py")
spec = importlib.util.spec_from_file_location("hepta_r7_scope_cycle_test", EXECUTOR)
if spec is None or spec.loader is None:
    raise SystemExit("could not load patched r7 executor")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

sanitized = module.rust_code_only(
    '''
    // use codex_comment::Wrong;
    /* codex_block::wrong(); /* use codex_nested::Wrong; */ */
    const TEXT: &str = "codex_string::wrong";
    const RAW: &str = r###"codex_raw::wrong"###;
    const BYTE: &[u8] = b"codex_byte::wrong";
    use codex_real::Thing;
    extern crate codex_external;
    fn call() { codex_path::run(); }
    '''
)
for forbidden in (
    "codex_comment",
    "codex_block",
    "codex_nested",
    "codex_string",
    "codex_raw",
    "codex_byte",
):
    if forbidden in sanitized:
        raise SystemExit(f"Rust lexical sanitizer retained non-code token: {forbidden}")
for required in ("codex_real", "codex_external", "codex_path"):
    if required not in sanitized:
        raise SystemExit(f"Rust lexical sanitizer removed code token: {required}")

with tempfile.TemporaryDirectory(prefix="hepta-r7-scope-") as directory:
    root = Path(directory)
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "benches").mkdir()
    (root / "examples").mkdir()
    (root / "src" / "lib.rs").write_text(
        'use codex_prod::Api;\nconst FILTER: &str = "codex_false_positive::target";\n',
        encoding="utf-8",
    )
    (root / "src" / "lib_tests.rs").write_text(
        "use codex_src_test::Fixture;\n", encoding="utf-8"
    )
    (root / "src" / "test_support.rs").write_text(
        "codex_test_support::fixture();\n", encoding="utf-8"
    )
    (root / "tests" / "integration.rs").write_text(
        "use codex_integration::Fixture;\n", encoding="utf-8"
    )
    (root / "benches" / "bench.rs").write_text(
        "codex_bench::run();\n", encoding="utf-8"
    )
    (root / "examples" / "demo.rs").write_text(
        "codex_example::run();\n", encoding="utf-8"
    )
    (root / "build.rs").write_text("codex_build::emit();\n", encoding="utf-8")
    observed = module.imported_workspace_crates_by_kind(root)
    if observed["dependencies"] != {"codex_prod"}:
        raise SystemExit(f"normal dependency scope mismatch: {observed!r}")
    expected_dev = {
        "codex_src_test",
        "codex_test_support",
        "codex_integration",
        "codex_bench",
        "codex_example",
    }
    if observed["dev-dependencies"] != expected_dev:
        raise SystemExit(f"dev dependency scope mismatch: {observed!r}")
    if observed["build-dependencies"] != {"codex_build"}:
        raise SystemExit(f"build dependency scope mismatch: {observed!r}")

with tempfile.TemporaryDirectory(prefix="hepta-r7-manifest-") as directory:
    root = Path(directory)
    package = root / "consumer"
    package.mkdir()
    normal = root / "normal"
    development = root / "development"
    build = root / "build"
    for dependency in (normal, development, build):
        dependency.mkdir()
    manifest = package / "Cargo.toml"
    manifest.write_text(
        '''
        [package]
        name = "consumer"
        version = "0.0.0"

        [dependencies.codex-table]
        path = "../table"

        [target.'cfg(windows)'.dev-dependencies]
        renamed = { package = "codex-renamed", path = "../renamed" }
        '''.replace("        ", ""),
        encoding="utf-8",
    )
    declarations = module.dependency_declarations(manifest.read_text(encoding="utf-8"))
    if "codex-table" not in declarations["dependencies"]:
        raise SystemExit("table-form dependency was not discovered")
    if "codex-renamed" not in declarations["dev-dependencies"]:
        raise SystemExit("renamed target-specific dependency was not discovered")
    if module.add_dependency(manifest, "codex-table", normal, "dependencies"):
        raise SystemExit("table-form dependency was duplicated")
    if module.add_dependency(manifest, "codex-renamed", development, "dev-dependencies"):
        raise SystemExit("renamed dev dependency was duplicated")
    if not module.add_dependency(manifest, "codex-normal", normal, "dependencies"):
        raise SystemExit("normal dependency was not added")
    if not module.add_dependency(
        manifest, "codex-development", development, "dev-dependencies"
    ):
        raise SystemExit("dev dependency was not added")
    if not module.add_dependency(manifest, "codex-build", build, "build-dependencies"):
        raise SystemExit("build dependency was not added")
    final = module.dependency_declarations(manifest.read_text(encoding="utf-8"))
    expected_by_kind = {
        "dependencies": {"codex-table", "codex-normal"},
        "dev-dependencies": {"renamed", "codex-renamed", "codex-development"},
        "build-dependencies": {"codex-build"},
    }
    for kind, expected in expected_by_kind.items():
        if not expected.issubset(final[kind]):
            raise SystemExit(f"section insertion mismatch for {kind}: {final!r}")
    before = manifest.read_text(encoding="utf-8")
    for dependency, dependency_path, kind in (
        ("codex-normal", normal, "dependencies"),
        ("codex-development", development, "dev-dependencies"),
        ("codex-build", build, "build-dependencies"),
    ):
        if module.add_dependency(manifest, dependency, dependency_path, kind):
            raise SystemExit(f"idempotence failed for {kind}:{dependency}")
    if manifest.read_text(encoding="utf-8") != before:
        raise SystemExit("idempotence probe mutated a complete manifest")

metadata = {
    "workspace_members": ["state-id", "core-id", "graph-id", "leaf-id"],
    "packages": [
        {"id": "state-id", "name": "codex-state"},
        {"id": "core-id", "name": "codex-core"},
        {"id": "graph-id", "name": "codex-agent-graph-store"},
        {"id": "leaf-id", "name": "codex-leaf"},
    ],
    "resolve": {
        "nodes": [
            {"id": "state-id", "deps": []},
            {
                "id": "core-id",
                "deps": [
                    {
                        "pkg": "graph-id",
                        "dep_kinds": [{"kind": None, "target": None}],
                    }
                ],
            },
            {
                "id": "graph-id",
                "deps": [
                    {
                        "pkg": "state-id",
                        "dep_kinds": [{"kind": None, "target": None}],
                    }
                ],
            },
            {"id": "leaf-id", "deps": []},
        ]
    },
}
graph = module.workspace_dependency_graph(metadata)
cycle = module.dependency_cycle_path(graph, "codex-state", "codex-core")
if cycle != [
    "codex-state",
    "codex-core",
    "codex-agent-graph-store",
    "codex-state",
]:
    raise SystemExit(f"cycle path mismatch: {cycle!r}")
if module.dependency_cycle_path(graph, "codex-state", "codex-leaf") is not None:
    raise SystemExit("acyclic dependency was rejected")

print("PASS_HEPTA_R7_SCOPE_AWARE_CYCLE_SAFE_DEPENDENCY_REPAIR")
