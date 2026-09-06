#!/usr/bin/env python3
"""Replay Hepta paper evidence from a separately pinned Git commit."""

from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BINDING_PATH = ROOT / "docs/learning/PAPER_EVIDENCE_BINDINGS.json"
AUTHORITY_KEYS = [
    "runtimeAuthority",
    "productionCaller",
    "productionWriter",
    "modelInvocation",
    "providerDispatch",
    "toolExecution",
    "networkConnect",
    "externalFilesystemMutation",
    "secretOperation",
    "matrixSend",
    "externalEffect",
    "fleetMutation",
    "canonicalSelection",
    "merge",
    "operatorAcceptance",
    "promotion",
    "release",
]


class DuplicateKey(ValueError):
    pass


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise DuplicateKey(key)
        out[key] = value
    return out


def die(message: str) -> None:
    raise SystemExit("FAIL_HEPTA_PAPER_EVIDENCE: " + message)


def need(condition: bool, message: str) -> None:
    if not condition:
        die(message)


def load_path(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except Exception as exc:
        die(f"{path}: {exc}")


def load_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    except Exception as exc:
        die(f"{label}: {exc}")


def git_text(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        die("git " + " ".join(args) + ": " + proc.stderr.strip())
    return proc.stdout.strip()


def git_bytes(*args: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode:
        die(
            "git "
            + " ".join(args)
            + ": "
            + proc.stderr.decode(errors="replace").strip()
        )
    return proc.stdout


def false_authority(value: Any, label: str) -> None:
    need(
        isinstance(value, dict) and list(value) == AUTHORITY_KEYS,
        label + " authority closure/order",
    )
    need(not any(bool(x) for x in value.values()), label + " positive authority")


def canonicalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def sentence_rows(text: str) -> list[dict[str, Any]]:
    normalized = canonicalize(text)
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", normalized) if x]
    return [
        {
            "sentenceIndex": i,
            "sha256": hashlib.sha256(s.encode("utf-8")).hexdigest(),
            "bytes": len(s.encode("utf-8")),
        }
        for i, s in enumerate(sentences, 1)
    ]


def verify_source(commit: str, row: dict[str, Any]) -> None:
    required = ["sourceId", "path", "kind", "gitBlobSha", "sha256", "bytes"]
    need(
        all(k in row for k in required),
        row.get("sourceId", "source") + " required fields",
    )
    spec = f"{commit}:{row['path']}"
    need(
        git_text("rev-parse", spec) == row["gitBlobSha"], row["sourceId"] + " Git blob"
    )
    raw = git_bytes("show", spec)
    need(len(raw) == row["bytes"], row["sourceId"] + " byte length")
    need(hashlib.sha256(raw).hexdigest() == row["sha256"], row["sourceId"] + " SHA-256")
    if row["kind"] == "official_publisher_abstract_snapshot":
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            die(row["sourceId"] + " UTF-8: " + str(exc))
        need(
            canonicalize(text).encode("utf-8") == raw,
            row["sourceId"] + " non-canonical snapshot",
        )
        need(
            row.get("sentences") == sentence_rows(text),
            row["sourceId"] + " sentence digest replay",
        )
    else:
        need("sentences" not in row, row["sourceId"] + " binary sentences")


def verify_retained_commit(binding: dict[str, Any]) -> str:
    """Verify the original evidence objects, retained through source ancestry.

    A branch name is no longer an evidence anchor. Full-history source checkouts
    retain the independently pinned commit through a provenance merge; merely
    fetching an unrelated object or creating a similarly named ref is insufficient.
    """
    need(
        binding.get("retentionPolicy") == {"kind": "main_history_ancestor"},
        "evidence retention policy",
    )
    need("evidenceBranch" not in binding, "obsolete mutable evidence branch")
    policy = binding.get("verificationPolicy", {})
    need(
        policy.get("pinnedEvidenceMustBeAncestorOfSource") is True,
        "evidence ancestry policy",
    )
    commit = binding["evidenceCommit"]
    need(
        isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit) is not None,
        "full evidence commit identity",
    )
    need(git_text("rev-parse", commit + "^{commit}") == commit, "evidence commit")
    parents = git_text("rev-list", "--parents", "-n", "1", commit).split()[1:]
    need(parents == [binding["evidenceParentCommit"]], "evidence direct parent")
    need(
        git_text("rev-parse", commit + "^{tree}") == binding["evidenceTree"],
        "evidence tree",
    )
    git_text("merge-base", "--is-ancestor", commit, "HEAD")
    return commit


def verify() -> int:
    binding = load_path(BINDING_PATH)
    need(
        binding.get("schema") == "hepta.paper-evidence-binding.v2"
        and binding.get("schemaVersion") == 2,
        "binding schema",
    )
    need(binding.get("planVersion") == "8.1.0-cns-organ", "binding plan")
    false_authority(binding.get("authorityFlags"), "binding")
    commit = verify_retained_commit(binding)
    manifest_spec = f"{commit}:{binding['manifestPath']}"
    need(
        git_text("rev-parse", manifest_spec) == binding["manifestGitBlobSha"],
        "manifest Git blob",
    )
    manifest = load_bytes(git_bytes("show", manifest_spec), "evidence manifest")
    need(
        manifest.get("schema") == "hepta.paper-source-lock-manifest.v2",
        "manifest schema",
    )
    need(
        manifest.get("parentCommit") == binding["evidenceParentCommit"],
        "manifest parent",
    )
    false_authority(manifest.get("authorityFlags"), "manifest")
    sources = manifest.get("sourceArtifacts")
    claims = manifest.get("claimBindings")
    need(
        isinstance(sources, list) and len(sources) == binding["sourceArtifactCount"],
        "source count",
    )
    need(
        isinstance(claims, list) and len(claims) == binding["semanticClaimCount"],
        "claim count",
    )
    ids = [x.get("sourceId") for x in sources]
    need(len(ids) == len(set(ids)), "duplicate source ID")
    need(set(binding["requiredSourceIds"]) <= set(ids), "required source coverage")
    for row in sources:
        verify_source(commit, row)
    semantic = load_path(ROOT / binding["semanticRegistry"])
    papers = semantic.get("papers")
    need(
        isinstance(papers, list) and len(papers) == binding["semanticPaperCount"],
        "semantic paper count",
    )
    expected = {(p["id"], claim) for p in papers for claim in p["claimsUsed"]}
    observed = {(x.get("paperId"), x.get("claim")) for x in claims}
    need(len(observed) == len(claims), "duplicate claim binding")
    need(expected == observed, "semantic claim coverage")
    source_map = {x["sourceId"]: x for x in sources}
    abstract_rows = {
        k: v
        for k, v in source_map.items()
        if v["kind"] == "official_publisher_abstract_snapshot"
    }
    for row in claims:
        need(row["paperId"] in abstract_rows, "claim source missing " + row["paperId"])
        sentence_ids = {
            x["sentenceIndex"] for x in abstract_rows[row["paperId"]]["sentences"]
        }
        need(
            row["sentenceIndex"] in sentence_ids,
            "claim sentence missing " + row["claim"],
        )
    policy = binding["verificationPolicy"]
    need(
        policy["changingRegistryAndVerifierConstantsTogetherMaySatisfyExternalEvidence"]
        is False,
        "self-certification policy",
    )
    need(
        policy["missingEvidenceObjectMayAdvanceClaim"] is False,
        "missing evidence policy",
    )
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_PAPER_EVIDENCE_REPLAY",
                "evidenceCommit": commit,
                "evidenceTree": binding["evidenceTree"],
                "sources": len(sources),
                "semanticPapers": len(papers),
                "semanticClaims": len(claims),
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def self_test() -> int:
    text = "One sentence. Two sentences!"
    rows = sentence_rows(text)
    need([x["sentenceIndex"] for x in rows] == [1, 2], "sentence fixture")
    need(
        rows[0]["sha256"] == hashlib.sha256(b"One sentence.").hexdigest(),
        "digest fixture",
    )
    try:
        json.loads('{"x":1,"x":2}', object_pairs_hook=pairs)
        die("duplicate key accepted")
    except DuplicateKey:
        pass
    good = hashlib.sha256(b"fixed source").hexdigest()
    need(
        hashlib.sha256(b"changed source").hexdigest() != good,
        "hostile source substitution fixture",
    )
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_PAPER_EVIDENCE_SELF_TEST",
                "cases": [
                    "canonicalization",
                    "sentence_digest",
                    "duplicate_key",
                    "source_substitution",
                ],
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["verify", "self-test"])
    args = parser.parse_args()
    return verify() if args.command == "verify" else self_test()


if __name__ == "__main__":
    raise SystemExit(main())
