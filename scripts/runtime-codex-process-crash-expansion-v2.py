#!/usr/bin/env python3
"""Corrected wrapper for pre-fsync runtime.codex SIGKILL scenarios."""

from __future__ import annotations

import subprocess
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_BLOB = "98ab9f31cf9d0ec716210b24154ddc4c3aeacdd1"


def load_original():
    source = subprocess.check_output(
        ["git", "cat-file", "blob", HISTORICAL_BLOB],
        cwd=ROOT,
    ).decode("utf-8")
    module = types.ModuleType("runtime_codex_process_crash_historical")
    module.__file__ = f"<git-blob:{HISTORICAL_BLOB}>"
    exec(compile(source, module.__file__, "exec"), module.__dict__)
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
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
