#!/usr/bin/env python3
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def write(name: str, value: str) -> None:
    (ROOT / name).write_text(value, encoding="utf-8")


def replace_once(name: str, old: str, new: str) -> None:
    value = read(name)
    count = value.count(old)
    if count != 1:
        raise RuntimeError(f"{name}: expected one match, found {count}: {old!r}")
    write(name, value.replace(old, new, 1))


replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "#[cfg(unix)]\nuse std::path::PathBuf;\n",
    "#[cfg(any(unix, feature = \"qualification\"))]\nuse std::path::PathBuf;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "        let daemon = tokio::spawn(run_supervisord_inner(\n"
    "            fleet_root.clone(),\n"
    "            cancellation.clone(),\n"
    "            None,\n"
    "        ));\n",
    "        let daemon = tokio::spawn(run_supervisord_inner(\n"
    "            fleet_root.clone(),\n"
    "            cancellation.clone(),\n"
    "            None,\n"
    "            None,\n"
    "        ));\n",
)

publish_name = "codex-rs/hepta-supervisor/src/signed_intent_publish.rs"
publish = read(publish_name)
expected = (
    "//! Shared same-directory durable publication for signed intents.\n\n"
    "use std::io;\n"
    "use std::path::Path;\n\n"
    "pub(crate) fn publish(staging: &Path, destination: &Path) -> io::Result<()> {\n"
    "    crate::durable_publish::publish(staging, destination)\n"
    "}\n"
)
if publish != expected:
    raise RuntimeError("signed_intent_publish.rs wrapper changed unexpectedly")
write(
    publish_name,
    expected
    + "\n#[cfg(test)]\n"
    + "#[path = \"signed_intent_publish_tests.rs\"]\n"
    + "mod tests;\n",
)

lease_name = "codex-rs/hepta-supervisor/src/lease.rs"
lease = read(lease_name)
lease = lease.replace("#[cfg(unix)]\nuse std::fs::File;\n", "", 1)
if "use std::fs::File;" in lease:
    raise RuntimeError("lease.rs retained an unexpected File import")
write(lease_name, lease)

workflow_name = ".github/workflows/hepta-lane-b-truth.yml"
workflow = read(workflow_name)
path_anchor = '      - "codex-rs/hepta-retrieval/**"\n'
if workflow.count(path_anchor) != 2:
    raise RuntimeError("Lane B workflow path anchors changed")
workflow = workflow.replace(
    path_anchor,
    path_anchor + '      - "codex-rs/hepta-supervisor/**"\n',
)
test_anchor = "          cargo test -p codex-hepta-supervisor --lib\n"
if workflow.count(test_anchor) != 1:
    raise RuntimeError("Lane B supervisor test anchor changed")
workflow = workflow.replace(
    test_anchor,
    test_anchor
    + "          cargo test -p codex-hepta-supervisor --test authority_distribution\n",
    1,
)
write(workflow_name, workflow)
