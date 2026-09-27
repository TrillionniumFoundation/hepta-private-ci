#!/usr/bin/env python3
"""One-shot, PR1065-scoped editing helper. Not a qualification or ref writer.

The assistant must inspect the retained diff, apply the immutable blobs through
an explicit Git commit, remove this helper, and requalify that NEW candidate.
No production security check is weakened, no failed test is removed, and no
permission, commit, ref, approval, release or acceptance is created here.
"""
from __future__ import annotations

import argparse
import base64
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import urllib.request

REPO = "TrillionniumFoundation/hepta-private-ci"
WORKER = "codex-rs/hepta-infer-worker-host/"
AGENTD = "codex-rs/hepta-agentd/src/"
ALLOWED = {
    AGENTD + "test_support.rs",
    AGENTD + "cognitive_context_hnmf_tests.rs",
    AGENTD + "state_isolation_tests.rs",
    "codex-rs/.config/nextest.toml",
    ".github/workflows/hepta-lane-b-truth.yml",
    "docs/modules/inference.worker/TECHNICAL.md",
    "qualification/module-execution-dossiers/detail/inference.worker.md",
    "docs/modules/MODULE_DOCS.json",
    "docs/modules/SOURCE_BINDINGS.json",
    "qualification/module-execution-dossiers/DETAILS.json",
}


def run(root: Path, *args: str) -> str:
    return subprocess.check_output(args, cwd=root, text=True).strip()


def replace_once(root: Path, path: str, before: str, after: str) -> None:
    target = root / path
    text = target.read_text()
    if before == after:
        raise ValueError("no-op edit")
    if text.count(before) == 1:
        target.write_text(text.replace(before, after, 1))
    elif text.count(after) == 1 and before not in text:
        return
    else:
        raise ValueError(f"unexpected source context: {path}: {before[:70]}")


def repair(root: Path) -> None:
    tests = WORKER + "src/native_app_server_tests.rs"
    replace_once(root, tests,
        '.find("client.request_typed::<TurnStartResponse>(ClientRequest::TurnStart")',
        '.find("send_authorized_turn_start(&mut client, entered_use, turn_params)")')
    replace_once(root, tests,
        '    assert!(revalidation < turn_start);',
        '    let authority_entry = source\n'
        '        .find("verified_use.enter(&authority_binding)")\n'
        '        .expect("physical final-use authority entry");\n'
        '    assert!(revalidation < authority_entry);\n'
        '    assert!(authority_entry < turn_start);')
    replace_once(root, tests,
        '    let host =\n'
        '        CognitiveTestHost::start(root, agent_id, MODEL, &format!("{}/v1", server.uri())).await?;',
        '    #[cfg(target_os = "linux")]\n'
        '    let sandbox_exe = Some(core_test_support::find_codex_linux_sandbox_exe()\n'
        '        .expect("Linux sandbox helper for the real App Server fixture"));\n'
        '    #[cfg(not(target_os = "linux"))]\n'
        '    let sandbox_exe = None;\n'
        '    // core_test_support installs arg0 dispatch in this test executable.\n'
        '    // Passing the configured helper is not substituting a dummy process.\n'
        '    let host = CognitiveTestHost::start(\n'
        '        root, agent_id, MODEL, &format!("{}/v1", server.uri()),\n'
        '        std::env::current_exe()?, sandbox_exe,\n'
        '    ).await?;')
    replace_once(root, AGENTD + "test_support.rs",
        '        provider_base_url: &str,\n    ) -> TestResult<Self>',
        '        provider_base_url: &str,\n'
        '        codex_self_exe: PathBuf,\n'
        '        codex_linux_sandbox_exe: Option<PathBuf>,\n'
        '    ) -> TestResult<Self>')
    replace_once(root, AGENTD + "test_support.rs",
        '            Arg0DispatchPaths::default(),',
        '            Arg0DispatchPaths {\n'
        '                codex_self_exe: Some(codex_self_exe.canonicalize()?),\n'
        '                codex_linux_sandbox_exe,\n'
        '                ..Arg0DispatchPaths::default()\n'
        '            },')
    replace_once(root, AGENTD + "cognitive_context_hnmf_tests.rs",
        '    let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&owner);',
        '    // Darwin temp roots can traverse /tmp or /var aliases. Canonicalize\n'
        '    // the fixture, not the production owner validation.\n'
        '    let fleet = fleet.canonicalize().unwrap();\n'
        '    let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&owner);')
    replace_once(root, AGENTD + "state_isolation_tests.rs",
        '    let checkpoint_file = temp.path().join("run-start-replay-checkpoint.json");',
        '    let checkpoint_file = temp.path().canonicalize()\n'
        '        .expect("canonical external checkpoint fixture root")\n'
        '        .join("run-start-replay-checkpoint.json");')
    replace_once(root, "codex-rs/.config/nextest.toml",
        '[profile.local]\ninherits = "default"',
        '[profile.local]\n\n'
        '# Explicit JUnit configuration for the pinned nextest 0.9.103.\n'
        '# The newer `inherits` key is not understood by that version.\n'
        '[profile.local.junit]\npath = "junit.xml"')
    lane_path = root / ".github/workflows/hepta-lane-b-truth.yml"
    lane = lane_path.read_text()
    needle = '      - "codex-rs/hepta-agentd/**"\n'
    addition = needle + '      - "codex-rs/hepta-infer-core/**"\n      - "codex-rs/hepta-infer-worker-host/**"\n'
    if lane.count(needle) != 2:
        raise ValueError("unexpected Lane B path-filter structure")
    if '      - "codex-rs/hepta-infer-worker-host/**"' not in lane:
        lane_path.write_text(lane.replace(needle, addition))
    guide = "docs/modules/inference.worker/TECHNICAL.md"
    replace_once(root, guide,
        '# inference.worker technical development guide\n',
        '# inference.worker technical development guide\n\n'
        'Current remediation boundaries and exact-candidate evidence: '
        '[hardening status](../../../codex-rs/hepta-infer-worker-host/HARDENING_STATUS.md).\n'
        'Reconcile-only operating procedure: '
        '[recovery operations](../../../codex-rs/hepta-infer-worker-host/RECOVERY_OPERATIONS.md).\n')
    replace_once(root, guide,
        'and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification.',
        'and are subject to the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. '
        'Source presence and documentation closure do not assert that the current candidate has passed those checks; '
        'read the current source-head and merge-candidate receipts, including failures and skips.')
    dossier = "qualification/module-execution-dossiers/detail/inference.worker.md"
    replace_once(root, dossier,
        'Trusted provider recovery and missing-usage reconciliation remain open.',
        'Exact surviving App Server thread-history reconciliation is implemented, including a no-dispatch reconcile-only entrypoint. '
        'Missing-history resolution and authenticated late token-usage amendments remain open. '
        'The local driver is feature-gated experimental; its process-local aggregate resource accounting '
        'is not verified local authority, a physical device proof or durable operation recovery.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--publish-blobs", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = run(root, "git", "rev-parse", "HEAD")
    if source != os.environ.get("SOURCE_SHA") or not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("exact source mismatch")
    if args.publish_blobs:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        pr = event.get("pull_request", {})
        if (os.environ.get("GITHUB_REPOSITORY") != REPO
                or event.get("number") != 1065
                or pr.get("head", {}).get("repo", {}).get("full_name") != REPO
                or pr.get("head", {}).get("ref") != "codex/inference-worker-hardening-20260927"
                or pr.get("head", {}).get("sha") != source):
            raise ValueError("preparation is restricted to the authorized exact PR head")
    args.output.mkdir(parents=True, exist_ok=True)
    run(root, "git", "archive", "--format=tar.gz",
        f"--output={args.output / 'original-source.tar.gz'}", source)
    with tempfile.TemporaryDirectory(prefix="inference-prepare-") as directory:
        copy = Path(directory) / "candidate"
        run(root, "git", "worktree", "add", "--detach", str(copy), source)
        try:
            repair(copy)
            for command in ("refresh-derived", "refresh-indexes"):
                output = run(copy, "python3", "scripts/hepta-module-docs.py", command)
                (args.output / f"{command}.log").write_text(output + "\n")
            subprocess.run(
                ["cargo", "fmt", "-p", "codex-hepta-infer-worker-host"],
                cwd=copy / "codex-rs", check=True, timeout=300,
            )
            for name in ("test_support.rs", "cognitive_context_hnmf_tests.rs", "state_isolation_tests.rs"):
                subprocess.run(
                    ["rustfmt", "--edition", "2024", str(copy / AGENTD / name)],
                    cwd=copy / "codex-rs", check=True, timeout=60,
                )
            changed = run(copy, "git", "diff", "--name-only").splitlines()
            if any(not (path.startswith(WORKER) or path in ALLOWED) for path in changed):
                raise ValueError("proposed changes escaped their exact file allowlist")
            patch = run(copy, "git", "diff", "--binary")
            (args.output / "proposed.patch").write_text(patch + "\n")
            entries = []
            with tarfile.open(args.output / "proposed-files.tar.gz", "w:gz") as archive:
                for path in changed:
                    archive.add(copy / path, arcname=path, recursive=False)
                    data = (copy / path).read_bytes()
                    expected_blob = hashlib.sha1(
                        f"blob {len(data)}\0".encode() + data, usedforsecurity=False,
                    ).hexdigest()
                    if args.publish_blobs:
                        request = urllib.request.Request(
                            f"https://api.github.com/repos/{REPO}/git/blobs",
                            data=json.dumps({"encoding": "base64", "content": base64.b64encode(data).decode()}).encode(),
                            headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                                     "Accept": "application/vnd.github+json", "Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(request, timeout=30) as response:
                            actual_blob = json.load(response)["sha"]
                        if actual_blob != expected_blob:
                            raise ValueError("GitHub blob identity mismatch")
                    entries.append({"path": path, "mode": "100644", "type": "blob",
                                    "sha": expected_blob, "sha256": hashlib.sha256(data).hexdigest()})
            (args.output / "blob-manifest.json").write_text(json.dumps({
                "source_head": source,
                "source_tree": run(root, "git", "rev-parse", "HEAD^{tree}"),
                "blobs_published": args.publish_blobs,
                "tree_elements": entries,
                "qualification": False,
                "refs_modified": False,
                "independent_acceptance": False,
            }, indent=2) + "\n")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(copy)], cwd=root, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
