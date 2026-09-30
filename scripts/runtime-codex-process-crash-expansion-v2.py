#!/usr/bin/env python3
"""Corrected wrapper for pre-fsync runtime.codex SIGKILL scenarios."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "scripts/runtime-codex-process-crash-expansion.py"


def load_original():
    spec = importlib.util.spec_from_file_location(
        "runtime_codex_process_crash_expansion",
        ORIGINAL,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load process-crash expansion migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def corrected_tests(text: str, original) -> str:
    text = original.tests(text)
    old = '''    let committed_marker = directory.path().join("dispatch-committed.json");
    let mut child = spawn_fixture("dispatch", &store, &committed_marker);
    wait_for_file(&committed_marker, &mut child);
    child.kill().expect("kill committed dispatch fixture");
    child.wait().expect("wait committed dispatch fixture");

    let abort_cut = committed_marker.with_extension("abort-uncommitted");
    let mut child = spawn_fixture("abort_uncommitted", &store, &committed_marker);
    wait_for_file(&abort_cut, &mut child);
    child.kill().expect("kill pre-abort-fsync fixture");
    child.wait().expect("wait pre-abort-fsync fixture");

    let recovered = AgentRunCoordinator::open_durable(composition(), store)
        .expect("recover dispatched owner after uncommitted abort");
'''
    new = '''    let committed_store = directory.path().join("agent-runs-committed.json");
    let committed_marker = directory.path().join("dispatch-committed.json");
    let mut child = spawn_fixture("dispatch", &committed_store, &committed_marker);
    wait_for_file(&committed_marker, &mut child);
    child.kill().expect("kill committed dispatch fixture");
    child.wait().expect("wait committed dispatch fixture");

    let abort_cut = committed_marker.with_extension("abort-uncommitted");
    let mut child = spawn_fixture(
        "abort_uncommitted",
        &committed_store,
        &committed_marker,
    );
    wait_for_file(&abort_cut, &mut child);
    child.kill().expect("kill pre-abort-fsync fixture");
    child.wait().expect("wait pre-abort-fsync fixture");

    let recovered = AgentRunCoordinator::open_durable(composition(), committed_store)
        .expect("recover dispatched owner after uncommitted abort");
'''
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError("process crash: ambiguous committed-store block")
        text = text.replace(old, new, 1)
    elif "agent-runs-committed.json" not in text:
        raise RuntimeError("process crash: committed-store block absent")
    return text


def main() -> None:
    original = load_original()
    fixture_path = ROOT / "codex-rs/hepta-agentd/src/bin/runtime-codex-crash-fixture.rs"
    fixture_path.write_text(
        original.fixture(fixture_path.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    test_path = ROOT / "codex-rs/hepta-agentd/tests/runtime_codex_process_crash.rs"
    test_path.write_text(
        corrected_tests(test_path.read_text(encoding="utf-8"), original),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
