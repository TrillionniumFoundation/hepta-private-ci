from __future__ import annotations

import difflib
import hashlib
import json
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
REL = pathlib.Path("codex-rs/core/tests/suite/multi_agent_resume.rs")
PREIMAGE = ROOT / "source" / REL
OUT = ROOT / "core-diagnostic-proposal"


def identity(data: bytes) -> dict:
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def run() -> None:
    before = PREIMAGE.read_text()
    assert identity(before.encode())["git_blob"] == "5cffeb3a7683c6654bbfe5474296b5458659aeec"
    replacements = []
    for role in ("worker", "sibling"):
        old = f"    let {role}_thread = initial.thread_manager.get_thread({role}_thread_id).await?;"
        new = f'''    let {role}_thread = initial
        .thread_manager
        .get_thread({role}_thread_id)
        .await
        .inspect_err(|error| {{
            eprintln!(
                "COLD_ROOT_RESUME_STAGE_ERROR stage=lookup_{role} thread_id={{{role}_thread_id}} error={{error:?}}"
            );
        }})?;'''
        replacements.append((f"lookup_{role}", old, new))
    for role, receiver, thread_id in (
        ("sibling", "sibling_thread", "sibling_thread_id"),
        ("worker", "worker_thread", "worker_thread_id"),
        ("root", "initial.codex", "root_thread_id"),
    ):
        old = f"    {receiver}.flush_rollout().await?;"
        new = f'''    {receiver}.flush_rollout().await.inspect_err(|error| {{
        eprintln!(
            "COLD_ROOT_RESUME_STAGE_ERROR stage=flush_{role} thread_id={{{thread_id}}} error={{error:?}}"
        );
    }})?;'''
        replacements.append((f"flush_{role}", old, new))
    old = "    let resumed = resume_builder.restart(&server, &initial).await?;"
    new = '''    let resumed = resume_builder
        .restart(&server, &initial)
        .await
        .inspect_err(|error| {
            eprintln!(
                "COLD_ROOT_RESUME_STAGE_ERROR stage=restart_root thread_id={root_thread_id} error={error:?}"
            );
        })?;'''
    replacements.append(("restart_root", old, new))
    after = before
    sites = []
    for stage, old, new in replacements:
        assert after.count(old) == 1, stage
        sites.append({"stage": stage, "old_line": before[:before.index(old)].count("\n") + 1,
                      "preimage": old, "postimage": new})
        after = after.replace(old, new, 1)
    restored = after
    for _, old, new in reversed(replacements):
        assert restored.count(new) == 1
        restored = restored.replace(new, old, 1)
    assert restored == before
    unchanged = {}
    for token in (".await", "assert!(", "assert_eq!(", "Duration::", "sleep(", ".expect(", "shutdown_and_wait("):
        assert before.count(token) == after.count(token), token
        unchanged[token] = before.count(token)
    diff = "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                         fromfile=f"a/{REL}", tofile=f"b/{REL}"))
    patch = f"diff --git a/{REL} b/{REL}\n" + diff
    OUT.mkdir(exist_ok=True)
    target = OUT / "candidate" / REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(after)
    (OUT / "core-cold-root-stage-diagnostic.patch").write_text(patch)
    with tempfile.TemporaryDirectory(prefix="core-cold-static-", dir=OUT) as temp:
        checkout = pathlib.Path(temp)
        p = checkout / REL
        p.parent.mkdir(parents=True)
        p.write_text(before)
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        subprocess.run(["git", "-C", str(checkout), "apply", "--check", "-"], input=patch.encode(), check=True)
        subprocess.run(["git", "-C", str(checkout), "apply", "-"], input=patch.encode(), check=True)
        assert p.read_bytes() == after.encode()
        subprocess.run(["git", "-C", str(checkout), "apply", "--reverse", "--check", "-"], input=patch.encode(), check=True)
        subprocess.run(["git", "-C", str(checkout), "apply", "--reverse", "-"], input=patch.encode(), check=True)
        assert p.read_bytes() == before.encode()
    manifest = {
        "schema": "hepta.core-cold-root-stage-diagnostic.v1",
        "status": "DIAGNOSTIC_ONLY_STATIC_NOT_APPLIED_OR_EXECUTED",
        "source_tree": "fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff",
        "path": str(REL), "preimage": identity(before.encode()), "postimage": identity(after.encode()),
        "patch": {"path": "core-cold-root-stage-diagnostic.patch", **identity(patch.encode())},
        "sites": sites,
        "mechanism": "Result::inspect_err adds only an error-path stderr line; the same original Err is propagated by the same ?; no error conversion/context replacement.",
        "unchanged_token_counts": unchanged,
        "original_source_exactly_restored_by_reversing_six_insertions": True,
        "isolated_git_apply_check_apply_reverse_check_reverse_exact": True,
        "original_case": "suite::multi_agent_resume::cold_root_resume_restores_agent_identity_and_role_on_followup",
        "gate": "Run only on a future root-approved exact source through the existing codex-core integration target, original timeout/profile/retries unchanged; require exact selected case and raw stderr/XML. This proposal itself is not a fix or a test result.",
        "limits": [
            "No production source, runtime settings, persistence semantics, request filters, capacity, assertion, wait, retry or timeout is changed.",
            "No extra HTTP, thread-store or manager request is made. No shared logs, credentials, home contents or process state are inspected.",
            "The six sites cover the source-supported persistence/error hypotheses, not every possible ? in external dependencies. Absence of the new marker would leave that broader propagation path open.",
            "Static apply/reverse checks do not prove Rust compilation, formatting or native behavior. No native lane was started.",
        ],
    }
    (OUT / "repair-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"postimage": manifest["postimage"], "patch": manifest["patch"], "sites": len(sites)}, indent=2))


if __name__ == "__main__":
    run()
