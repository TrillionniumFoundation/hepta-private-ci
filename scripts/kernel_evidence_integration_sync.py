#!/usr/bin/env python3
"""Synchronize only kernel.evidence integration metadata without granting gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import kernel_evidence_status as status_tools

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/modules/kernel.evidence/TECHNICAL.md"
MAP = ROOT / "docs/modules/kernel.evidence/IMPLEMENTATION_MAP.json"
INDEX = ROOT / "docs/modules/MODULE_DOCS.json"
BEGIN = "<!-- BEGIN KERNEL EVIDENCE INTEGRATION 20260928 -->"
END = "<!-- END KERNEL EVIDENCE INTEGRATION 20260928 -->"

INTEGRATION_GUIDE = """## 20. Integrated candidate and publisher ownership

The integration candidate is `work/kernel-evidence-ad-integration-20260928`
(PR #1148). It preserves the actual source from #1092 and the separate
2026-09-28 follow-up. Do not add the capabilities of unmerged branches together
or count a source-rewriting script as compiled implementation.

Production publication uses two complementary fences. The durable SQLite lease
binds owner and generation across restart; a nonblocking OS lock on the canonical
private Agent home serializes publication/reconciliation processes for the
entire prepare or publish request. A reused logical owner ID does not permit a
second process to enter. The directory descriptor remains alive through external
CAS/recovery, policy rechecks, SQLite acknowledgement and store close. Identity
and private mode are rechecked before external dispatch and acknowledgement.
The descriptor lifetime releases ownership; no process unlinks a lock file.

`evidence_publication_process_lock_tests.rs` includes separate-open, real
subprocess contention, successor acquisition, directory replacement and mode
mutation tests. The subprocess must produce an observed-disposition record;
a child that executes zero tests cannot satisfy the test. These source tests
require execution on the exact candidate. File-lock semantics on a different
storage platform still require independent operational qualification.

Local receipt commit and external anchoring are separate states. Publication
preparation, immutable batch identity, dispatch, uncertain result and accepted
frontier are durable. A matching latest record is not by itself a durable ACK:
reconciliation must recover and synchronize the matching external record before
acknowledging the batch. Changed policy, expired ownership or uncertain I/O
leave the same batch unresolved; they never allocate a replacement successful
history. Normal writes do not silently promise zero-loss external anchoring.

Cursor paging is a bounded live query, not a frozen historical snapshot unless
the caller binds a separately retained frontier. A verification summary proves
only its registered profile; consumers must require the profile appropriate to
the decision they are making, rather than accepting any `supported` value.

The A-D diagnostic workflow tests exact source and a deterministic merge against
fixed main `a126987b84737dbc2ee2592442a314117bddb4a2`. It never repairs the
working tree under test. Formatter suggestions are created in a separate
worktree and become new source only after review/commit. Standalone solver,
Python, evidence package, Agentd library/product, doctest, strict lint, build,
Lane-A, documents and implementation-map records remain distinct. A failed,
missing or skipped command does not qualify either candidate.

Canonical status anchors source and workflow files to an immutable code commit;
generated projections and the guide may be metadata-only descendants. The
implementation map is then bound to the actual documentation commit. This
avoids self-referential Git identities without transferring old test results.
Independent acceptance, external storage, real backup/restore and power-loss
drills, canary, promotion and release remain separate external receipts.
"""

STORE_NOTE = """## Publication process ownership

The owner-bound publication CLI also holds a nonblocking OS lock on the private
canonical Agent home for its entire request. The durable lease is still required;
the physical lock prevents two processes sharing the same logical owner from
simultaneously entering external CAS. The lock descriptor is not inherited across
exec and is released by close or process exit, never by unlinking a lock file.
Directory replacement or mode drift before dispatch/acknowledgement fails closed.

If another publisher is active, retry the same request after it completes; do not
remove files, clear a batch, change the owner registry or force a new generation.
After an uncertain external write, use the same batch reconciliation path, which
re-synchronizes the exact matching record before recovering an acknowledgement.
A latest-frontier read alone is not evidence of durable acknowledgement.
"""


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "--literal-pathspecs", *args], cwd=ROOT, text=True, timeout=60
    ).strip()


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def anchored_commit(value: str) -> dict[str, str]:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("anchor must be an exact commit OID")
    if git("rev-parse", f"{value}^{{commit}}") != value:
        raise ValueError("anchor is not a commit")
    git("merge-base", "--is-ancestor", value, "HEAD")
    return {"commit": value, "tree": git("rev-parse", f"{value}^{{tree}}")}


def replace_block(path: Path, body: str) -> None:
    text = path.read_text(encoding="utf-8")
    block = BEGIN + "\n" + body.rstrip() + "\n" + END
    if BEGIN in text or END in text:
        pattern = re.escape(BEGIN) + r".*?" + re.escape(END)
        text, count = re.subn(pattern, lambda _: block, text, flags=re.S)
        if count != 1:
            raise ValueError(f"ambiguous integration block in {path}")
    elif status_tools.STATUS_BEGIN in text:
        text = text.replace(
            status_tools.STATUS_BEGIN, block + "\n\n" + status_tools.STATUS_BEGIN, 1
        )
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text, encoding="utf-8")


def source_inventory(anchor: str) -> list[str]:
    paths = git("ls-tree", "-r", "--name-only", anchor).splitlines()
    exact = {
        ".github/workflows/blocking-ci.yml",
        "codex-rs/Cargo.toml",
        "codex-rs/Cargo.lock",
        "codex-rs/hepta-agentd/Cargo.toml",
        "codex-rs/hepta-agentd/src/lib.rs",
        "codex-rs/hepta-agentd/src/main.rs",
        "codex-rs/hepta-agentd/build.rs",
        "codex-rs/hepta-agent-protocol/Cargo.toml",
        "codex-rs/hepta-agent-protocol/src/evidence.rs",
        "codex-rs/state/src/lib.rs",
        "codex-rs/state/src/sqlite.rs",
        "codex-rs/state/src/sqlite_evidence_runtime.rs",
    }
    selected = []
    for path in paths:
        if (
            path in exact
            or path.startswith("codex-rs/hepta-evidence/")
            or path.startswith("codex-rs/hepta-agentd/src/evidence_")
            or path.startswith("codex-rs/hepta-agentd/tests/kernel_evidence_")
            or path.startswith("scripts/kernel_evidence_")
            or path.startswith("scripts/build_kernel_evidence_")
            or path.startswith("scripts/tests/test_kernel_evidence_")
            or path.startswith(".github/workflows/hepta-kernel-evidence-")
            or path.startswith(".github/workflows/kernel-evidence-")
        ):
            selected.append(path)
    return sorted(set(selected))


def sync_metadata(anchor: str) -> None:
    identity = anchored_commit(anchor)
    status = status_tools.load_json(status_tools.STATUS_PATH)
    status["asOfCommit"] = identity["commit"]
    status["asOfTree"] = identity["tree"]
    status["sourcePaths"] = source_inventory(anchor)
    # This tool cannot authenticate execution or external acceptance receipts.
    if any(status[gate] for gate, _ in status_tools.GATES):
        raise ValueError("qualified status requires a separate reviewed transition")
    if (
        status["evidenceReceipts"]
        or status["workflowRunId"]
        or status["artifactDigest"]
    ):
        raise ValueError("do not overwrite existing authority receipts")
    dump(status_tools.STATUS_PATH, status)
    replace_block(GUIDE, INTEGRATION_GUIDE)
    replace_block(
        ROOT / "docs/lane-a-foundation/kernel.evidence/STORE_V1.md", STORE_NOTE
    )
    store_path = ROOT / "docs/lane-a-foundation/kernel.evidence/STORE_V1.md"
    store_text = store_path.read_text(encoding="utf-8")
    store_text = store_text.replace(
        "- latest equals the proposed frontier: recover acknowledgement;",
        "- latest equals the proposed frontier: synchronize the exact stored record and recover its durable acknowledgement;",
    )
    store_path.write_text(store_text, encoding="utf-8")
    status_tools.validate_status(status)
    status_tools.sync(status)
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    entries = [
        entry for entry in index["modules"] if entry["module"] == "kernel.evidence"
    ]
    if len(entries) != 1:
        raise ValueError("ambiguous kernel.evidence document registry")
    data = GUIDE.read_bytes()
    entries[0].update(
        {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "words": len(re.findall(r"\b[\w.-]+\b", data.decode("utf-8"))),
            "production_implementation": False,
        }
    )
    dump(INDEX, index)
    status_tools.verify(status)


def bind_map(anchor: str) -> None:
    identity = anchored_commit(anchor)
    mapping = json.loads(MAP.read_text(encoding="utf-8"))
    mapping["sourceBase"] = identity
    mapping["productionImplementation"] = False
    for key in (
        "productionImplementation",
        "productExecutionProved",
        "independentAcceptance",
        "activation",
        "release",
    ):
        mapping["claimBoundary"][key] = False
    dump(MAP, mapping)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("metadata", "map"))
    parser.add_argument("anchor")
    args = parser.parse_args()
    if args.command == "metadata":
        sync_metadata(args.anchor)
    else:
        bind_map(args.anchor)


if __name__ == "__main__":
    main()
