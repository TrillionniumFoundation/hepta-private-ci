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

Production publication uses complementary physical and durable fences. A
nonblocking OS lock on the canonical private Agent home serializes publication
processes for the entire request. The SQLite owner lease binds identity and
generation across restart. After the exact Dispatching record has committed,
`with_publication_dispatch_guard` takes a `BEGIN IMMEDIATE` writer reservation.
It checks the enrolled store, exact prepared snapshot/proposal, currently
accepted predecessor, owner identity/expiry and accepted issuer trust generation
in that one transaction. The reservation remains held across the synchronous
external recovery/CAS call, so another database connection cannot commit owner
or trust replacement halfway through dispatch. The callback must not re-enter
this SQLite store. Agentd uses `try_compare_and_swap`, whose active/store lock
admission fails immediately on contention; the ordinary CAS interface retains
its previous blocking contention contract. Neither path invents a conflict or
a durable acknowledgement when the backend is merely unavailable.

The process directory descriptor stays alive through external I/O, policy
rechecks, acknowledgement and store close. It is never unlinked as a lock-file
recovery technique. Identity/private mode, current issuer file and lease are
rechecked at the effect boundary. A lease or policy change after an external
write leaves the SAME batch unresolved. Filesystem read/fsync latency still
requires target-platform measurement and fault qualification; a nonblocking
lock alone is not a wall-clock I/O SLA.

`acknowledge_publication_with_trust` checks current trust, owner and the exact
backend observation in the same transaction that accepts the frontier and
acknowledges every batch intent. A commit whose result is unknown is explicitly
indeterminate. The raw compatibility acknowledgement API is not Agentd's
production path. An already acknowledged batch enters `RecoverOnly`: the
external record must be found and re-synchronized. Missing historical data is
corruption requiring reconciliation, never permission to issue a new CAS.

Durable acknowledgement JSON uses exactly `backendId`,
`backendIdentitySha256`, `storeId`, `frontierGeneration`, `frontierSha256` and
`auditSequence`. Serialization does not make arbitrary inbound JSON a verified
backend handle, and it carries no activation, acceptance or release flag.

`publication_dispatch_tests.rs` uses real migrated stores and authenticated
append to cover stale owner, replaced proposal, unknown external result,
policy replacement, acknowledged-only recovery, durable trust rollback and a
second SQLite connection attempting to enter the held write epoch. The Agentd
lease-boundary and backend acknowledgement-wire/lock regressions remain
separate. These are source tests until executed on the exact candidate.

Local receipt commit and external anchoring are separate states. Preparation,
immutable batch identity, dispatch, uncertain result and accepted frontier are
durable. A matching latest record is not itself an ACK: reconciliation must
synchronize the exact external record before acknowledging the batch. Normal
writes do not silently promise zero-loss external anchoring.

Cursor paging is a bounded live query, not a frozen historical snapshot unless
the caller binds a retained frontier. A verification summary proves only its
registered profile; consumers must require the profile appropriate to their
decision rather than accepting any `supported` value.

The A-D diagnostic workflow tests exact source and a deterministic merge against
fixed main `a126987b84737dbc2ee2592442a314117bddb4a2`. It never repairs the
working tree under test. Formatter output becomes a new source only through a
separate bounded delivery commit. Standalone solver, Python/SQLite probes,
evidence package, Agentd product, doctest, strict lint, build, Lane-A, documents
and implementation-map records remain distinct. Failed, missing, skipped or
queued commands cannot qualify either candidate. SQLite probes do not replace
Rust execution or external crash/power-loss drills.

Canonical status binds source/workflow files to an immutable code commit;
generated projections and the guide may be metadata-only descendants. The map
then binds the actual documentation commit. This avoids self-referential Git
identities without transferring old test results. Independent acceptance,
external storage, witnessed backup/restore and power-loss drills, capacity,
canary, promotion and release require their own exact authority receipts.
"""

STORE_NOTE = """## Publication process ownership and durable epochs

The owner publication CLI holds a nonblocking OS lock on the canonical private
Agent home for its entire request. The lease remains required. A second process
with the same logical owner cannot enter. The descriptor is not inherited by
exec and is released by close/exit, never by unlinking a lock file.

After durable Dispatching, the production path reserves one SQLite write epoch
across current trust/owner/predecessor/batch checks and external recovery/CAS.
Backend lock contention fails immediately. The callback cannot re-enter SQLite.
The transaction writes no rows and cannot erase the earlier dispatch record on
rollback, crash or uncertain I/O. The separate production acknowledgement
transaction checks current trust again and commits frontier acceptance plus
all exact batch intents atomically. Unknown commit results remain unresolved.

Already-acknowledged batches are recovery-only: missing external history cannot
be recreated by another CAS. Reconciliation re-synchronizes the exact matching
record before recovering an ACK. A latest-frontier read alone is insufficient.
Do not clear a batch, restore old trust, remove lock paths or force a new owner
to hide an uncertain result. File/fsync delay and crash behavior still require
physical platform qualification; the source does not claim a latency bound.
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
    # These files select the live mode and dispatch the product requests. A
    # complete evidence leaf implementation cannot compensate for omitting them.
    required_product_paths = {
        "codex-rs/hepta-agentd/src/client.rs",
        "codex-rs/hepta-agentd/src/config.rs",
        "codex-rs/hepta-agentd/src/runtime.rs",
        "codex-rs/hepta-agentd/src/evidence_host.rs",
        "codex-rs/hepta-agentd/src/evidence_production.rs",
        "codex-rs/hepta-agentd/src/evidence_production_checks.rs",
        "codex-rs/hepta-agent-protocol/src/evidence.rs",
    }
    missing = required_product_paths - set(paths)
    if missing:
        raise ValueError(
            f"source anchor lacks product admission paths: {sorted(missing)}"
        )
    exact = required_product_paths | {
        ".github/workflows/blocking-ci.yml",
        "codex-rs/Cargo.toml",
        "codex-rs/Cargo.lock",
        "codex-rs/hepta-agentd/Cargo.toml",
        "codex-rs/hepta-agentd/src/lib.rs",
        "codex-rs/hepta-agentd/src/main.rs",
        "codex-rs/hepta-agentd/build.rs",
        "codex-rs/hepta-agent-protocol/Cargo.toml",
        "codex-rs/state/Cargo.toml",
        "codex-rs/state/src/lib.rs",
        "codex-rs/state/src/sqlite.rs",
        "codex-rs/state/src/sqlite_evidence_runtime.rs",
    }
    selected = []
    for path in paths:
        if (
            path in exact
            or path.startswith("codex-rs/hepta-evidence/")
            or path.startswith("codex-rs/hepta-agent-protocol/src/")
            or path.startswith("codex-rs/hepta-agentd/src/evidence_")
            or path.startswith("codex-rs/hepta-agentd/tests/kernel_evidence_")
            or path.startswith("scripts/kernel_evidence_")
            or path.startswith("scripts/build_kernel_evidence_")
            or path.startswith("scripts/tests/test_kernel_evidence_")
            or path.startswith(".github/actions/setup-ci/")
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
    parent_path = "codex-rs/hepta-agentd/src/evidence_production.rs"
    checks_path = "codex-rs/hepta-agentd/src/evidence_production_checks.rs"
    marker = "kernel.evidence recovery_required"
    if 'include!("evidence_production_checks.rs");' not in git(
        "show", f"{anchor}:{parent_path}"
    ):
        raise ValueError("production verifier no longer includes its recovery checks")
    if marker not in git("show", f"{anchor}:{checks_path}"):
        raise ValueError(
            "production recovery checks lost their fail-closed error boundary"
        )
    bindings = [
        entry
        for entry in mapping["productionWriterBindings"]
        if entry.get("mustContain") == marker
    ]
    if len(bindings) != 1 or bindings[0]["sourcePath"] not in (
        parent_path,
        checks_path,
    ):
        raise ValueError("ambiguous production recovery writer binding")
    # Keep the verifier itself as a product caller, but bind the error oracle
    # to its actual included source. Do not invent a marker in the caller.
    bindings[0]["sourcePath"] = checks_path
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
    new_operations = [
        (
            "guard_publication_dispatch",
            "HeptaEvidenceStore::with_publication_dispatch_guard",
            "codex-rs/hepta-evidence/src/publication_dispatch.rs",
            "codex-rs/hepta-evidence/src/publication_dispatch_tests.rs",
            "current_trust_and_owner_fenced_publication_dispatch",
        ),
        (
            "acknowledge_publication_with_trust",
            "HeptaEvidenceStore::acknowledge_publication_with_trust",
            "codex-rs/hepta-evidence/src/publication_dispatch.rs",
            "codex-rs/hepta-evidence/src/publication_dispatch_tests.rs",
            "atomic_current_trust_frontier_and_batch_acknowledgement",
        ),
        (
            "frontier_try_compare_and_swap",
            "LockedFileEvidenceFrontierBackend::try_compare_and_swap",
            "codex-rs/hepta-evidence/src/frontier_backend_file/segmented/trait.rs",
            "codex-rs/hepta-evidence/src/frontier_backend_file/segmented/trait.rs",
            "nonblocking_lock_admission_for_existing_durable_cas",
        ),
    ]
    for operation, symbol, source, test, authority in new_operations:
        entry = {
            "operation": operation,
            "nativeSymbol": symbol,
            "sourcePath": source,
            "state": "source_implemented_product_composed",
            "authority": authority,
            "tests": [test],
            "sourcePathExists": True,
        }
        existing = [
            item for item in mapping["operations"] if item["operation"] == operation
        ]
        if len(existing) > 1:
            raise ValueError(f"ambiguous operation mapping: {operation}")
        if existing:
            existing[0].update(entry)
        else:
            mapping["operations"].append(entry)
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
