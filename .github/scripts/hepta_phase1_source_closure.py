#!/usr/bin/env python3
"""Expand the canonical source-closure verifier after exact package qualification."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"{label}: expected one replacement, found {count}")
    return updated


def replace_literal_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one marker, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: hepta_phase1_source_closure.py <repository-root>")
    root = Path(sys.argv[1]).resolve()

    registry_path = root / "scripts/hepta_source_registry_closure.py"
    registry = registry_path.read_text(encoding="utf-8")
    registry = replace_once(
        registry,
        r"SOURCE_ROOTS: dict\[str, tuple\[str, \.\.\.\]\] = \{\n.*?\n\}\n\nSOURCE_STATUS",
        "SOURCE_ROOTS: dict[str, tuple[str, ...]] = {\n    \"automation.taskflow\": (\"codex-rs/hepta-automation\",),\n    \"browser.servo\": (\"apps/hepta-browser\", \"third_party/servo-patches\"),\n    \"channel.matrix\": (\"codex-rs/hepta-matrix-sdk\", \"codex-rs/hepta-matrixd\"),\n    \"cognitive.read\": (\"codex-rs/hepta-cognitive-read\",),\n    \"cognitive.store\": (\"codex-rs/hepta-cognitive-store\",),\n    \"cognitive.types\": (\"codex-rs/hepta-cognitive-types\",),\n    \"compact.engine\": (\"codex-rs/hepta-compact-engine\",),\n    \"context.compiler\": (\"codex-rs/hepta-context-compiler\",),\n    \"control.engineering\": (\"tools/hepta-engineering-control\",),\n    \"inference.control\": (\"codex-rs/hepta-infer-core\", \"codex-rs/hepta-inferd\"),\n    \"inference.worker\": (\"codex-rs/hepta-infer-worker-host\",),\n    \"intelligence.control\": (\"codex-rs/hepta-intelligence\",),\n    \"intuition.policy\": (\"codex-rs/hepta-intuition\",),\n    \"kernel.authority\": (\"codex-rs/hepta-contracts\",),\n    \"kernel.operations\": (\"codex-rs/hepta-operations\",),\n    \"knowledge.graph\": (\"codex-rs/hepta-kg\",),\n    \"learning.artifacts\": (\"codex-rs/hepta-learning-artifacts\",),\n    \"learning.eval\": (\"codex-rs/hepta-intelligence-eval\",),\n    \"learning.ledger\": (\"codex-rs/hepta-learning-ledger\",),\n    \"learning.operator\": (\"codex-rs/hepta-bellman-operator\",),\n    \"learning.plasticity\": (\"codex-rs/hepta-plasticity\",),\n    \"memory.federation\": (\"codex-rs/hepta-memory-federation\",),\n    \"memory.retrieval\": (\"codex-rs/hepta-memory-retrieval\",),\n    \"neuron.runtime\": (\"codex-rs/hepta-neuron\",),\n    \"objective.compiler\": (\"codex-rs/hepta-objective\",),\n    \"platform.types\": (\"codex-rs/hepta-types\",),\n    \"platform.wire\": (\"codex-rs/hepta-wire\",),\n    \"prompt.optimizer\": (\"codex-rs/hepta-prompt-optimizer\",),\n    \"prompt.registry\": (\"codex-rs/hepta-prompt-registry\",),\n    \"runtime.agentd\": (\"codex-rs/hepta-agentd\",),\n    \"runtime.codex\": (\"codex-rs/codex-app-server\", \"codex-rs/hepta-codex-adapter\"),\n    \"runtime.fleet\": (\"codex-rs/hepta-fleet\",),\n    \"runtime.supervisor\": (\"codex-rs/hepta-supervisor\",),\n    \"ui.control\": (\"apps/hepta-control-ui\",),\n    \"ui.native\": (\"apps/hepta-native\",),\n    \"utility.ndu\": (\"codex-rs/hepta-ndu\",),\n}\n\nADDITIONAL_SOURCE_IMPLEMENTED_PACKAGES = frozenset(\n    {\n        \"INFER-V4-T1\",\n        \"INFER-V4-T2\",\n        \"INFER-V4-T3\",\n        \"LRN-1-DURABLE-EPISODE-LEDGER\",\n        \"NDU-1-DETERMINISTIC-UTILITY-BASELINE\",\n        \"OBJ-1-OBJECTIVE-COMPILER\",\n        \"P0.7B-B2-TOOL-NET-FS\",\n        \"P0.7B-B3-BOUNDARIES\",\n        \"P0.7B-B4-CALLSITE-PROOF\",\n        \"P0.8A-AST-RATCHET\",\n        \"P0.8C-RESOURCE-BUDGETS\",\n        \"P0.8D-VERTICAL-SLICE\",\n    }\n)\n\nSOURCE_STATUS",
        "source-root registry",
    )
    old_receipt = (
        "The source candidate is checked by `.github/workflows/hepta-gap-closure.yml`, "
        "including closed-world inventory, package tests, all-target compilation, strict "
        "Clippy and clean tracked state."
    )
    new_receipt = (
        "The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml` "
        "on the exact source head and prospective merge candidate, including closed-world "
        "inventory, package tests, all-target compilation, strict Clippy and clean tracked state."
    )
    registry = replace_literal_once(
        registry,
        old_receipt,
        new_receipt,
        "source receipt workflow",
    )

    normalize_old = (
        '    packages_by_id = _index(packages, "id", "WORK_PACKAGES.json")\n\n'
        "    bootstrap_packages: dict[str, str] = {}\n"
    )
    normalize_new = (
        '    packages_by_id = _index(packages, "id", "WORK_PACKAGES.json")\n\n'
        "    for package_id in ADDITIONAL_SOURCE_IMPLEMENTED_PACKAGES:\n"
        "        package = packages_by_id.get(package_id)\n"
        "        if package is None:\n"
        "            raise RegistryClosureError(\n"
        '                f"qualified source package is not registered: {package_id}"\n'
        "            )\n"
        '        if package.get("state") == "blocked_external":\n'
        "            raise RegistryClosureError(\n"
        '                f"external package cannot be normalized as source implemented: {package_id}"\n'
        "            )\n"
        '        package["state"] = "source_implemented"\n\n'
        "    bootstrap_packages: dict[str, str] = {}\n"
    )
    registry = replace_literal_once(
        registry,
        normalize_old,
        normalize_new,
        "normalize qualified-package insertion",
    )

    manifest_old = "    changed_paths: list[Path] = []\n"
    manifest_new = (
        "    manifest_document = _load_json(QUALIFICATION_MANIFEST_PATH)\n"
        '    manifest_document["source_roots"] = sorted(\n'
        "        {root for roots in SOURCE_ROOTS.values() for root in roots}\n"
        "    )\n\n"
        "    changed_paths: list[Path] = []\n"
    )
    registry = replace_literal_once(
        registry,
        manifest_old,
        manifest_new,
        "qualification manifest normalization",
    )
    manifest_write_old = (
        "    if _write_json(WORK_PACKAGES_PATH, packages_document):\n"
        "        changed_paths.append(WORK_PACKAGES_PATH)\n\n"
    )
    manifest_write_new = (
        "    if _write_json(WORK_PACKAGES_PATH, packages_document):\n"
        "        changed_paths.append(WORK_PACKAGES_PATH)\n"
        "    if _write_json(QUALIFICATION_MANIFEST_PATH, manifest_document):\n"
        "        changed_paths.append(QUALIFICATION_MANIFEST_PATH)\n\n"
    )
    registry = replace_literal_once(
        registry,
        manifest_write_old,
        manifest_write_new,
        "qualification manifest write",
    )

    verify_post_old = (
        "    except RegistryClosureError as error:\n"
        "        return [str(error)]\n\n"
        "    bootstrap_packages: dict[str, str] = {}\n"
    )
    verify_post_new = (
        "    except RegistryClosureError as error:\n"
        "        return [str(error)]\n\n"
        "    for package_id in ADDITIONAL_SOURCE_IMPLEMENTED_PACKAGES:\n"
        "        package = packages_by_id.get(package_id)\n"
        "        if package is None:\n"
        '            failures.append(f"qualified source package is missing: {package_id}")\n'
        '        elif package.get("state") != "source_implemented":\n'
        "            failures.append(\n"
        '                f"qualified source package is not implemented: {package_id}"\n'
        "            )\n\n"
        "    bootstrap_packages: dict[str, str] = {}\n"
    )
    registry = replace_literal_once(
        registry,
        verify_post_old,
        verify_post_new,
        "verify qualified-package insertion",
    )
    registry_path.write_text(registry, encoding="utf-8")

    gap_path = root / "scripts/hepta-gap-closure.py"
    gap = gap_path.read_text(encoding="utf-8")
    import_old = (
        "from hepta_source_registry_closure import normalize as normalize_source_registries\n"
    )
    import_new = (
        "from hepta_source_registry_closure import SOURCE_ROOTS\n"
        "from hepta_source_registry_closure import normalize as normalize_source_registries\n"
    )
    gap = replace_literal_once(gap, import_old, import_new, "SOURCE_ROOTS import")
    gap = replace_once(
        gap,
        r"RUST_PACKAGES = \{\n.*?\n\}\n\nREQUIRED_OTHER_FILES = \(\n.*?\n\)",
        "RUST_PACKAGES = {\n    \"hepta-agentd\": \"codex-hepta-agentd\",\n    \"hepta-automation\": \"codex-hepta-automation\",\n    \"hepta-bellman-operator\": \"codex-hepta-bellman-operator\",\n    \"hepta-codex-adapter\": \"codex-hepta-codex-adapter\",\n    \"hepta-cognitive-read\": \"codex-hepta-cognitive-read\",\n    \"hepta-cognitive-store\": \"codex-hepta-cognitive-store\",\n    \"hepta-cognitive-types\": \"codex-hepta-cognitive-types\",\n    \"hepta-compact-engine\": \"codex-hepta-compact-engine\",\n    \"hepta-context-compiler\": \"codex-hepta-context-compiler\",\n    \"hepta-contracts\": \"codex-hepta-contracts\",\n    \"hepta-fleet\": \"codex-hepta-fleet\",\n    \"hepta-infer-core\": \"codex-hepta-infer-core\",\n    \"hepta-infer-worker-host\": \"codex-hepta-infer-worker-host\",\n    \"hepta-inferd\": \"codex-hepta-inferd\",\n    \"hepta-intelligence\": \"codex-hepta-intelligence\",\n    \"hepta-intelligence-eval\": \"codex-hepta-intelligence-eval\",\n    \"hepta-intuition\": \"codex-hepta-intuition\",\n    \"hepta-kg\": \"codex-hepta-kg\",\n    \"hepta-learning-artifacts\": \"codex-hepta-learning-artifacts\",\n    \"hepta-learning-ledger\": \"codex-hepta-learning-ledger\",\n    \"hepta-matrix-sdk\": \"codex-hepta-matrix-sdk\",\n    \"hepta-matrixd\": \"codex-hepta-matrixd\",\n    \"hepta-memory-federation\": \"codex-hepta-memory-federation\",\n    \"hepta-memory-retrieval\": \"codex-hepta-memory-retrieval\",\n    \"hepta-ndu\": \"codex-hepta-ndu\",\n    \"hepta-neuron\": \"codex-hepta-neuron\",\n    \"hepta-objective\": \"codex-hepta-objective\",\n    \"hepta-operations\": \"codex-hepta-operations\",\n    \"hepta-plasticity\": \"codex-hepta-plasticity\",\n    \"hepta-prompt-optimizer\": \"codex-hepta-prompt-optimizer\",\n    \"hepta-prompt-registry\": \"codex-hepta-prompt-registry\",\n    \"hepta-supervisor\": \"codex-hepta-supervisor\",\n    \"hepta-types\": \"codex-hepta-types\",\n    \"hepta-wire\": \"codex-hepta-wire\",\n}\n\nREQUIRED_OTHER_FILES = (\n    \"apps/hepta-browser/package.json\",\n    \"apps/hepta-browser/src/browser.js\",\n    \"apps/hepta-browser/test/browser.test.js\",\n    \"apps/hepta-control-ui/package.json\",\n    \"apps/hepta-control-ui/src/control.js\",\n    \"apps/hepta-control-ui/test/control.test.js\",\n    \"apps/hepta-native/package.json\",\n    \"apps/hepta-native/src/native.js\",\n    \"apps/hepta-native/test/native.test.js\",\n    \"third_party/servo-patches/MANIFEST.json\",\n    \"third_party/servo-patches/README.md\",\n    \"tools/hepta-engineering-control/hepta_engineering_control.py\",\n    \"tools/hepta-engineering-control/test_hepta_engineering_control.py\",\n    \"docs/readiness/GAP_CLOSURE_IMPLEMENTATION.md\",\n    \"qualification/gap-closure/MANIFEST.json\",\n    \"qualification/gap-closure/PLAN_AUDIT.json\",\n    \"scripts/hepta_source_registry_closure.py\",\n    \"scripts/test_hepta_gap_closure.py\",\n    \"scripts/verify_hepta_callers.py\",\n    \"qa/b4-no-bypass/test_verify_hepta_callers.py\",\n    \"qa/performance/test_resource_budget.py\",\n    \"qa/vertical-slice/test_vertical_slice.py\",\n    \".github/workflows/hepta-consolidated-source.yml\",\n)",
        "Rust package and required-file inventory",
    )
    old_tests = '        test_files = tuple((root / "src").glob("*_tests.rs"))\n'
    new_tests = (
        '        test_files = tuple((root / "src").glob("*_tests.rs")) + '
        'tuple((root / "tests").rglob("*.rs"))\n'
    )
    gap = replace_literal_once(gap, old_tests, new_tests, "focused Rust tests")
    old_roots = (
        '            expected_roots = sorted(f"codex-rs/{name}" for name in RUST_PACKAGES)\n'
        "            expected_roots.extend(\n"
        '                ["apps/hepta-control-ui", "tools/hepta-engineering-control"]\n'
        "            )\n"
    )
    new_roots = (
        "            expected_roots = sorted(\n"
        "                {root for roots in SOURCE_ROOTS.values() for root in roots}\n"
        "            )\n"
    )
    gap = replace_literal_once(
        gap,
        old_roots,
        new_roots,
        "closed-world source roots",
    )
    gap_path.write_text(gap, encoding="utf-8")

    workflow_path = root / ".github/workflows/hepta-consolidated-source.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    package_lines = [
        "codex-hepta-agentd codex-hepta-automation",
        "codex-hepta-bellman-operator codex-hepta-codex-adapter",
        "codex-hepta-cognitive-read codex-hepta-cognitive-store",
        "codex-hepta-cognitive-types codex-hepta-compact-engine",
        "codex-hepta-context-compiler codex-hepta-contracts",
        "codex-hepta-fleet codex-hepta-infer-core",
        "codex-hepta-infer-worker-host codex-hepta-inferd",
        "codex-hepta-intelligence codex-hepta-intelligence-eval",
        "codex-hepta-intuition codex-hepta-kg",
        "codex-hepta-learning-artifacts codex-hepta-learning-ledger",
        "codex-hepta-matrix-sdk codex-hepta-matrixd",
        "codex-hepta-memory-federation codex-hepta-memory-retrieval",
        "codex-hepta-ndu codex-hepta-neuron",
        "codex-hepta-objective codex-hepta-operations",
        "codex-hepta-plasticity codex-hepta-prompt-optimizer",
        "codex-hepta-prompt-registry codex-hepta-supervisor",
        "codex-hepta-types codex-hepta-wire",
    ]
    packages_rendered = "      PACKAGES: >-\n" + "\n".join(
        f"        {line}" for line in package_lines
    )
    workflow = replace_once(
        workflow,
        r"      PACKAGES: >-\n(?:        .*\n)+?    steps:",
        packages_rendered + "\n    steps:",
        "consolidated package matrix",
    )
    workflow = replace_literal_once(
        workflow,
        "    timeout-minutes: 45\n",
        "    timeout-minutes: 90\n",
        "consolidated timeout",
    )
    old_node = (
        "          node --test apps/hepta-browser/test/*.js apps/hepta-native/test/*.js\n"
    )
    new_node = (
        "          node --test apps/hepta-browser/test/*.js "
        "apps/hepta-control-ui/test/*.js apps/hepta-native/test/*.js\n"
        "          python3 -m unittest discover -v -s qa/b4-no-bypass -p 'test_*.py'\n"
        "          python3 -m unittest discover -v -s qa/performance -p 'test_*.py'\n"
        "          python3 -m unittest discover -v -s qa/vertical-slice -p 'test_*.py'\n"
        "          python3 scripts/verify_hepta_callers.py\n"
    )
    workflow = replace_literal_once(
        workflow,
        old_node,
        new_node,
        "non-Rust qualification",
    )
    old_clippy = (
        '          cargo clippy --locked "${args[@]}" --all-targets -- -D warnings\n'
    )
    new_clippy = (
        '          cargo clippy --locked --no-deps "${args[@]}" '
        '--all-targets -- -D warnings\n'
    )
    workflow = replace_literal_once(
        workflow,
        old_clippy,
        new_clippy,
        "consolidated Clippy",
    )
    workflow_path.write_text(workflow, encoding="utf-8")

    packages_document = json.loads(
        (root / "docs/delivery/WORK_PACKAGES.json").read_text(encoding="utf-8")
    )
    known = {item.get("id") for item in packages_document.get("packages", [])}
    missing = sorted(set(['INFER-V4-T1', 'INFER-V4-T2', 'INFER-V4-T3', 'LRN-1-DURABLE-EPISODE-LEDGER', 'NDU-1-DETERMINISTIC-UTILITY-BASELINE', 'OBJ-1-OBJECTIVE-COMPILER', 'P0.7B-B2-TOOL-NET-FS', 'P0.7B-B3-BOUNDARIES', 'P0.7B-B4-CALLSITE-PROOF', 'P0.8A-AST-RATCHET', 'P0.8C-RESOURCE-BUDGETS', 'P0.8D-VERTICAL-SLICE']) - known)
    if missing:
        raise SystemExit(f"qualified work package ids are missing: {missing}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
