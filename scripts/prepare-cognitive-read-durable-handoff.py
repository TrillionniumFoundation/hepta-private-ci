#!/usr/bin/env python3
"""Author the durable read-request handoff and refresh exact source bindings.

This workflow helper is intentionally separate from read-only qualification.
It performs ordinary, reviewable commits on the dedicated cognitive.read branch,
then delegates immutable map refresh to the existing preparation script.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE_PREPARER = "scripts/prepare-cognitive-read-source.py"
HANDOFF_APPLIER = "scripts/apply-cognitive-read-durable-handoff.py"
DELIVERY_GUIDE = ROOT / "docs/modules/cognitive.read/DELIVERY_EVIDENCE.md"
FINAL_USE_GUIDE = ROOT / "docs/modules/cognitive.read/FINAL_USE_CLOSURE.md"

SOURCE_PATHS = {
    "codex-rs/hepta-agentd/src/client.rs",
    "codex-rs/hepta-agentd/src/lib.rs",
    "codex-rs/hepta-agentd/src/cognitive_retrieval_delivery_tests.rs",
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    "codex-rs/hepta-infer-core/src/cognitive_delivery.rs",
    "codex-rs/hepta-infer-core/src/cognitive_delivery_tests.rs",
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "codex-rs/hepta-infer-worker-host/src/native_run_control.rs",
    "codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs",
}


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "--literal-pathspecs", *args], cwd=ROOT, text=True
    ).strip()


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def replace_once(path: Path, old: str, new: str) -> None:
    body = path.read_text()
    if old not in body and body.count(new) == 1:
        return
    if body.count(old) != 1:
        raise ValueError(f"documentation shape drift: {path.relative_to(ROOT)}")
    path.write_text(body.replace(old, new, 1))


def commit_source() -> None:
    current = git("rev-parse", "HEAD")
    run("python3", HANDOFF_APPLIER, "--expected-sha", current)
    run("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all")
    run("git", "diff", "--check")
    changed = set(git("diff", "--name-only").splitlines())
    unexpected = changed - SOURCE_PATHS
    if unexpected:
        raise ValueError(f"durable handoff escaped reviewed source paths: {sorted(unexpected)}")
    if changed:
        run("git", "add", "--", *sorted(changed))
        run(
            "git",
            "commit",
            "-m",
            "feat(cognitive.read): persist exact preparation identity to native dispatch",
        )


def update_docs() -> None:
    replace_once(
        DELIVERY_GUIDE,
        """cache or execution capability. No journal schema or wire format is changed here.
""",
        """cache or execution capability. No second journal or cross-process wire method is
added. The existing native journal receives one additive optional read-request identity;
historical rows remain decodable but cannot be upgraded into a modern delivery join.
""",
    )
    replace_once(
        DELIVERY_GUIDE,
        """`AppServerModelDriver::inspect_cognitive_assignment` joins the active witnessed preparation
to native evidence under those existing owners. It verifies this driver's principal,
generation and model, then hashes the exact learning event/chain/sequence/support and
native evidence into an authority-free inspection result. It neither sends a request
nor appends a second event. Both read-RPC identity and native-attempt identity must be
independently pinned by the trusted host: matching a content digest alone is insufficient.

This is an implemented local inspection surface, not automatic product learning ingestion.
The current normal read client does not by itself supply a persisted read-RPC-to-native-run
handoff for every learning consumer. That explicit product composition, its revalidation
at training admission and actual physical-worker evidence remain required. An inspection
fixture is not a replacement for a real model/provider boundary test.
""",
        """`AgentdClient::cognitive_context_prepared` retains the already authenticated control
request ID without changing the control response shape. The normal native worker writes that
ID beside the exact owner-context digest in the existing dispatch record before physical
`TurnStart`. `AppServerModelDriver::inspect_cognitive_assignment` now requires the supplied
read ID to equal the persisted value, while `inspect_persisted_cognitive_assignment` derives
the value from the independently pinned native request. Both methods join the active witnessed
preparation to native evidence and hash the exact learning event/chain/sequence/support and
native evidence into an authority-free inspection result. Matching a content digest alone is
insufficient, and historical dispatches without the additive ID fail closed.

This closes the normal read-RPC-to-native-attempt identity handoff without appending another
log or treating dispatch as acceptance. It is still not automatic product learning ingestion:
delivery observations are not written back as training facts, and training admission must
reacquire both owners and reject missing or `AcceptanceUnknown` evidence. The real physical
worker gate remains mandatory; an inspection fixture is not a provider-boundary receipt.
""",
    )
    replace_once(
        DELIVERY_GUIDE,
        """- `delivery-join-tests`: external library integration across the existing learning and
  native owners, including exact read RPC/context/generation rejection and journal reopen.
""",
        """- `delivery-join-tests`: external library integration across the existing learning and
  native owners, including the persisted normal-product read request, exact
  context/generation rejection and journal reopen.
""",
    )
    replace_once(
        DELIVERY_GUIDE,
        """`context.compiler` verified V2 ingress, the other consumers' distinct lifecycle/host gaps,
automatic delivery-learning composition, exact-source/merge checks, target-host resource
qualification, independent review, canary and release remain separate work. Existing
""",
        """`context.compiler` verified V2 ingress, the other consumers' distinct lifecycle/host gaps,
automatic delivery-observation ingestion and training-admission revalidation,
exact-source/merge checks, target-host resource qualification, independent review, canary
and release remain separate work. Existing
""",
    )
    replace_once(
        FINAL_USE_GUIDE,
        """must not be upgraded into a confirmed exposure merely because preparation was
recorded. This candidate does not claim that all downstream learning consumers
already enforce that join; the migration remains a separately tracked gap.
""",
        """must not be upgraded into a confirmed exposure merely because preparation was
recorded. The normal worker now persists the exact Agentd read request in the existing native
dispatch and the local inspection API verifies that identity against the witnessed preparation.
Downstream delivery-observation ingestion and training admission must still reacquire both
owners; they may not infer exposure from preparation or an unknown dispatch.
""",
    )
    replace_once(
        FINAL_USE_GUIDE,
        """package pass is relabeled as a completed normal-product migration. Delivery/use
learning correlation, exact source/merge CI, target-host measurements,
independent review and controlled acceptance remain required.
""",
        """package pass is relabeled as a completed normal-product migration. Automatic
delivery-observation ingestion and training-admission revalidation, exact source/merge CI,
target-host measurements, independent review and controlled acceptance remain required.
""",
    )
    run("git", "diff", "--check")
    changed = [
        str(DELIVERY_GUIDE.relative_to(ROOT)),
        str(FINAL_USE_GUIDE.relative_to(ROOT)),
    ]
    staged = [path for path in changed if git("status", "--short", "--", path)]
    if staged:
        run("git", "add", "--", *staged)
        run(
            "git",
            "commit",
            "-m",
            "docs(cognitive.read): define durable preparation handoff boundary",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha):
        raise ValueError("expected SHA must be lowercase hexadecimal")
    if git("rev-parse", "HEAD") != args.expected_sha:
        raise ValueError("durable handoff preparation requires the exact authored candidate")
    if git("status", "--porcelain"):
        raise ValueError("durable handoff preparation requires a clean checkout")

    # First retain all existing selected-cut/lock preparation invariants.
    run("python3", BASE_PREPARER, "--expected-sha", args.expected_sha)
    if git("status", "--porcelain"):
        raise ValueError("base preparation left an uncommitted worktree")

    commit_source()
    update_docs()

    # Rebind every mapped source/document object to the final immutable parent.
    current = git("rev-parse", "HEAD")
    run("python3", BASE_PREPARER, "--expected-sha", current)
    if git("status", "--porcelain"):
        raise ValueError("final map refresh left an uncommitted worktree")
    print(f"DURABLE_HANDOFF_PREPARED_HEAD={git('rev-parse', 'HEAD')}")


if __name__ == "__main__":
    main()
