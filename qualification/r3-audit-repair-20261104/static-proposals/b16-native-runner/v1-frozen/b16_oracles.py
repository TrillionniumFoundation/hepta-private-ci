"""Classify only the approved physical counterfactual endpoints, per exact case.

These predicates are not new product assertions. Original Rust assertions stay
unchanged. An unexpected failure stops the epoch after exact source restoration.
"""

import re
from pathlib import Path

from b16_guard import need


def clean(text):
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return re.sub(r"(?:\\x1b|\\u001b|\\u\{1b\})\[[0-?]*[ -/]*[@-~]", "", text)


def ordered(text, markers):
    position = 0
    locations = []
    for marker in markers:
        match = re.search(r"(?m)^" + re.escape(marker) + r"\s*$", text[position:])
        need(match is not None, "missing or misordered physical endpoint: " + marker)
        position += match.end()
        locations.append(position)
    return locations


def panic_at(text, tree, relative, needle):
    source = (Path(tree) / relative).read_text()
    need(source.count(needle) == 1, "panic source anchor is ambiguous: " + relative + " / " + needle)
    line = source[:source.index(needle)].count("\n") + 1
    pattern = r"panicked at [^\n]*" + re.escape(Path(relative).name) + r":" + str(line) + r":\d+:"
    need(re.search(pattern, text) is not None, "failure did not hit the approved physical assertion")
    return {"path": relative, "line": line, "needle": needle}


def qualify(kind, case, tree):
    need(case["result"] == "FAIL", "negative must be a real assertion failure")
    text, name = clean(case["captured"]), case["name"]
    need(not re.search(r"(?m)^\s*(?:TIMEOUT|LEAK)\s*\[", text), "timeout/leak is not physical proof")
    memory = "codex-rs/hepta-memory/src/objective_sender_connection_custody_tests.rs"
    state = "codex-rs/state/src/sqlite_native_custody_tests.rs"
    driver = "codex-rs/third_party/sqlx-sqlite-0.9.0/src/options/connection_lifetime_tests.rs"
    markers = []
    if kind == "barrier":
        match = re.search(r"(?m)^cancelled barrier: SQLite callback entered; replacement query_only=(\d+), busy_timeout=(\d+)\s*$", text)
        need(match is not None, "actual SQLite progress/cancel observation missing")
        query_only, busy_timeout = map(int, match.groups())
        need(query_only != 1 or busy_timeout != 5000, "counterfactual did not retain the changed connection")
        needle = 'assert_eq!(query_only, 1,' if query_only != 1 else 'assert_eq!(busy_timeout, 5_000,'
        anchor = panic_at(text, tree, "codex-rs/state/src/sqlite_read_barrier_tests.rs", needle)
    elif kind == "interlock":
        markers = ["commit_interlock: commit_succeeded=true sqlite_code=None"]
        anchor = panic_at(text, tree, "codex-rs/hepta-memory/src/objective_sender_commit_interlock_tests.rs",
                          'assert_eq!(code.as_deref(), Some("531"))')
    elif kind in ("custody", "anchor") or (kind == "pool" and "connection_custody_tests" in name):
        if kind == "anchor" or kind == "pool":
            markers += ["connection_custody: physical_connection_rows=1", "connection_custody: competing_exclusive_acquired=false"]
            markers += (["connection_custody: commit_hook_removed=true native_close_started=false"] if kind == "anchor" else
                        ["native_custody: both_registered_anchors_removed=true native_close_started=false"])
        if name.endswith("cancelled_close_retains_custody_after_a_cancelled_checkpoint"):
            markers += ["connection_custody: checkpoint_entered=true", "connection_custody: original_close_pending=true pool_closed=true"]
        markers += ["connection_custody: physical_connection_rows=1", "connection_custody: competing_exclusive_acquired=true"]
        anchor = panic_at(text, tree, memory, "assert!(matches!(\n        competing,")
    elif kind in ("driver-worker", "driver-close", "pool"):
        if kind == "driver-close":
            markers = ["owned lifetime checkpoint=initialization_error_preserved_and_closed",
                       "physical custody expected=Released result=Ok(())", "owned lifetime checkpoint=gate_status=-1",
                       "owned lifetime checkpoint=busy_close_failed_and_native_statement_still_runs",
                       "physical custody expected=Held result=Ok(())", "owned lifetime checkpoint=gate_status=-1"]
            need("original failed-close result=WorkerCrashed" in text, "original close error missing")
            anchor = panic_at(text, tree, driver, 'panic!("unexpected physical lock result:')
        else:
            if kind == "pool":
                stage = "cancelled_guarded_native_open" if "guarded_pool" in name else "cancelled_coordinated_initial_pragma"
                source = state
            else:
                stage = "cancelled_inside_native_open" if "native_open" in name else "cancelled_inside_initial_pragma"
                source = driver
            markers = ["owned lifetime checkpoint=" + stage, "physical custody expected=Held result=Ok(())",
                       "owned lifetime checkpoint=gate_status=0"]
            anchor = panic_at(text, tree, source, 'panic!("unexpected physical lock result:')
    elif kind == "checkpoint":
        markers = ["actual recovery stage=cancelled_at_actual_checkpoint_progress",
                   "recovery checkpoint cancelled: actual_cross_process_lock=Ok(())", "actual recovery stage=gate_status=0"]
        anchor = panic_at(text, tree, "codex-rs/hepta-memory/src/cognitive_store_recovery_custody_tests.rs",
                          "assert!(matches!(actual, Err(TryLockError::WouldBlock))")
    else:
        raise RuntimeError("unreviewed negative oracle: " + str(kind))
    locations = ordered(text, markers)
    return {"name": name, "kind": kind, "qualified": True, "physical_markers": markers,
            "marker_end_offsets_in_ansi_stripped_case_output": locations, "actual_panic_anchor": anchor,
            "scope": "Exact selected case output + unchanged Rust physical assertion; no inferred platform/Current closure."}


EARLY = ("requires a remote test environment", "requires remote test environment",
         "Skipping test because it cannot execute when network is disabled", "python not found; skipping",
         "setsid not available; skipping", "skipping zsh-fork test:", "unable to resolve `codex-execve-wrapper` binary",
         "failed to fetch zsh via dotslash", "skipping sandbox test:")


def early_notices(raw, cases):
    """Keep notices bound to complete nextest blocks, with unbound notices explicit."""
    lines = clean(raw).splitlines()
    summary = max((i for i, x in enumerate(lines) if re.match(r"^\s*Summary\s+\[", x)), default=len(lines))
    headers = []
    for i, line in enumerate(lines[:summary]):
        m = re.match(r"^\s*(PASS|FAIL|TIMEOUT|LEAK|SKIP)\s+\[\s*[0-9.]+s\]\s+(\S+)\s+(.+?)\s*$", line)
        if m:
            headers.append((i, m.group(2), m.group(3)))
    keys = {(x["classname"], x["name"]) for x in cases}
    observations = []
    for i, line in enumerate(lines):
        if not any(marker in line for marker in EARLY):
            continue
        matches = [h for j, h in enumerate(headers) if h[0] <= i < (headers[j + 1][0] if j + 1 < len(headers) else summary)]
        h = matches[0] if len(matches) == 1 else None
        observations.append({"line": i + 1, "text": line,
                             "case": [h[1], h[2]] if h else None,
                             "bound_to_exact_junit": bool(h and (h[1], h[2]) in keys)})
    return observations
