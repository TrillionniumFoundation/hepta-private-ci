"""Observe one original Windows test without changing production or assertions."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PATH = "codex-rs/windows-sandbox-rs/src/token_tests.rs"
EXPECTED = {
    "codex-rs/windows-sandbox-rs/src/token.rs": "8945d75fe172679479b738e6266cac99a6f7ed16",
    "codex-rs/windows-sandbox-rs/src/acl.rs": "71cdde8fff5622ad77888f6ebe865c2169fe8a89",
    PATH: "2f69533094097dc6f02695858215809784575fbe",
}
CASE = "token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def write(output, name, value):
    (output / name).write_text(json.dumps(value, indent=2) + "\n")


def source():
    return {
        "head": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "trackedChanges": git("status", "--porcelain", "--untracked-files=no"),
        "originalObjects": {
            path: git("hash-object", "--path=" + path, path) for path in EXPECTED
        },
    }


def prepare(output):
    before = source()
    if before["trackedChanges"] or before["originalObjects"] != EXPECTED:
        raise RuntimeError("measured production or original test changed")
    write(output, "source-before.json", before)
    path = ROOT / PATH
    text = path.read_text()
    needle = """    let (outside_read, refused) = {
        let _impersonation = unsafe { Impersonation::enter(token.0)? };"""
    assert text.count(needle) == 1
    insert = """
        let observed = delete_probe::record(&allowed, &outside, &[
            ("cap_a", cap_a.as_ptr()), ("cap_b", cap_b.as_ptr()),
            ("other_cap", other_cap.as_ptr()),
            ("logon", logon.as_mut_ptr().cast()),
            ("everyone", everyone.as_mut_ptr().cast()),
        ]);
        if let Err(error) = observed {
            eprintln!("HEPTA_DELETE_OBSERVATION_ERROR={error}");
        }"""
    text = text.replace(needle, needle + insert, 1)
    text = (
        '#[path = "../../../.github/scripts/windows_token_delete_probe.rs"]\nmod delete_probe;\n'
        + text
    )
    path.write_text(text)
    write(
        output,
        "injection.json",
        {
            "schema": "hepta.original-token-observation-injection.v1",
            "productionTokenAndAclGitObjects": EXPECTED,
            "instrumentedTestSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "scope": "Read-only observation; original operations and assertions unchanged",
            "qualification": False,
        },
    )


def run(output):
    command = [
        "just",
        "test",
        "--locked",
        "-p",
        "codex-windows-sandbox",
        "--lib",
        "--cargo-profile",
        "dev-small",
        "-E",
        "test(=" + CASE + ")",
        "--test-threads",
        "1",
        "--no-tests",
        "fail",
        "--retries",
        "0",
    ]
    with (output / "original-case.log").open("w") as stream:
        process = subprocess.run(
            command,
            cwd=ROOT / "codex-rs",
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
        )
    write(
        output,
        "execution.json",
        {
            "command": command,
            "exitCode": process.returncode,
            "case": CASE,
            "testRetries": 0,
            "securityQualification": False,
        },
    )
    return process.returncode


def collect(output):
    try:
        text = (output / "original-case.log").read_text(errors="replace")
        lines = re.findall(r"HEPTA_DELETE_FACTS=(\{[^\n]+\})", text)
        if len(lines) != 1:
            raise RuntimeError(f"expected one observation, got {len(lines)}")
        facts = json.loads(lines[0])
        assert len(facts["nodes"]) == 8
        assert facts["productionAuthorityGranted"] is False
        assert facts["securityQualification"] is False
        write(output, "facts.json", facts)
    finally:
        subprocess.run(
            ["git", "restore", "--source=HEAD", "--worktree", "--", PATH],
            cwd=ROOT,
            check=True,
        )
        after = source()
        write(output, "source-after.json", after)
        before = json.loads((output / "source-before.json").read_text())
        write(
            output,
            "receipt.json",
            {
                "schema": "hepta.original-token-delete-facts-receipt.v1",
                "status": "OBSERVATION_ONLY",
                "sourceRestored": before == after,
                "originalSourceUnchanged": after["originalObjects"] == EXPECTED,
                "originalCaseAssertionsUnchanged": True,
                "testRetries": 0,
                "productionAuthorityGranted": False,
                "securityQualification": False,
            },
        )
        if before != after:
            raise RuntimeError("source was not restored exactly")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run", "collect"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.action == "prepare":
        prepare(args.output)
    elif args.action == "run":
        return run(args.output)
    else:
        collect(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
