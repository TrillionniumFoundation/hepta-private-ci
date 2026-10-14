"""Fail-closed GitHub publisher-byte attestation *before* independent video labels.

New v2 eligibility requires verified Git commit/tree, publisher CC0 declaration,
bounded original video bytes, derived source identities and the full legacy+CC0
exposure inventory. No video files are written. This is NOT a quality, rights,
pretraining-contamination, source-family-independence or production certificate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

from source_gate import SourceGateError, verify

REPO_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z")
SHA1_RE = re.compile(r"[0-9a-f]{40}\Z")
MAX_TREE_BYTES = 2 * 1024 * 1024
MAX_LICENSE_BYTES = 20 * 1024
MAX_MEDIA_BYTES = 40 * 1024 * 1024
MAX_TOTAL_MEDIA_BYTES = 120 * 1024 * 1024
MAX_TREE_MEMBERS = 10000

# Exact previous stage() source-id constructors, reproduced without importing
# PyTorch or allowing the submitter to replace the old cohort.
_OLD_360_REV = "6e99f3e7393ef3fa690b43f38fd4ea261a16a804"
_OLD_360 = {
    "Scene1A_14.mp4": "29fe53ba7da904313663eef6d4c0cafe88640105",
    "Scene1B_84.mp4": "eb2500dc321d8b0ad082db71ee3064831ddfe230",
    "Scene2_22.mp4": "1fb7540fe6e225de34b4d042199ac99f19691fe4",
    "Scene3A_55.mp4": "f52aa01c3a3edf3a813205a9be7b56d15f43b26a",
    "Scene4A_4.mp4": "18cfc6bfcca25a06a3ff036425a576b878f276f6",
    "Scene4B_17.mp4": "810e09720435c52dddb08b11bea824c288b02849",
    "Scene5A_48.mp4": "f51133145194c9beaf3743275bf1fea742e2e1e3",
    "Scene5B_20.mp4": "b9016469bc9a73dd1e94058185faeff2806387d8",
    "Scene6A_47.mp4": "a7807a5a3fa0b0d1054a2b4eaf9c586d94df967e",
    "Scene6B_59.mp4": "846b26cd75edf08d710a5a58dd60ba19d1b85c5c",
}
# These two CC0 recordings were already examined in a separate exploratory
# branch. Treat them as exposed even before that study is merged.
_EXPOSED_CC0_REPO = "shotstack/test-media"
_EXPOSED_CC0_REV = "b790a2b72325feecd189291c52663ed8123b1839"
_EXPOSED_CC0 = {
    "captioning/scott-ko.mp4": "6a7fcaae6d30c66fd6c40ea76379676499f40276",
    "orientation/h1080_w1920_f30_a16-9_r0.mp4": "13086393eaa72d194edd224611af95f4e0e365a5",
}


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def _sha1(value, label):
    if not isinstance(value, str) or SHA1_RE.fullmatch(value) is None:
        raise SourceGateError("canonical Git SHA-1 required: " + label)
    return value


def prior_ids():
    previous = [sha256(canonical([_OLD_360_REV, name, blob]))
                for name, blob in _OLD_360.items()]
    previous.extend(sha256(canonical([_EXPOSED_CC0_REPO, _EXPOSED_CC0_REV, path, blob]))
                    for path, blob in _EXPOSED_CC0.items())
    return sorted(previous)


def prior_pin():
    # Matches source_gate.verify's sorted compact JSON precommitment.
    return sha256(json.dumps(prior_ids(), separators=(",", ":")).encode())


def checked_path(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 200 or
            value.startswith("/") or "\\" in value or "?" in value or
            "#" in value or any(part in ("", ".", "..") for part in value.split("/")) or
            any(ord(c) < 33 or ord(c) > 126 for c in value)):
        raise SourceGateError("noncanonical immutable publisher path")
    return value


def _int(value, lo, hi, name):
    if type(value) is not int or not lo <= value <= hi:
        raise SourceGateError("invalid bounded " + name)
    return value


def _pairs(items):
    record = {}
    for key, value in items:
        if key in record:
            raise SourceGateError("duplicate JSON key")
        record[key] = value
    return record


def _decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=lambda x: (_ for _ in ()).throw(SourceGateError("invalid JSON constant")))
    except (UnicodeError, ValueError) as exc:
        raise SourceGateError("invalid publisher JSON") from exc


def read_url(url, maximum):
    """HTTPS GitHub endpoints are constructed locally; never taken from a plan."""
    if not (url.startswith("https://api.github.com/repos/") or
            url.startswith("https://raw.githubusercontent.com/")):
        raise SourceGateError("non-publisher acquisition URL")
    with urlopen(Request(url, headers={"User-Agent": "hepta-independent-video-attestation", "Accept": "application/vnd.github+json"}),
                 timeout=45) as response:
        raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise SourceGateError("bounded publisher response exceeded")
    return raw


def _exact_media(row):
    if not isinstance(row, dict) or set(row) != {"path", "git_blob_sha1", "byte_count", "split", "group_id"}:
        raise SourceGateError("exact no-label source declaration required")
    path = checked_path(row["path"])
    if not path.endswith((".mp4", ".webm", ".mov")):
        raise SourceGateError("supported video file extension required")
    _sha1(row["git_blob_sha1"], "declared media")
    _int(row["byte_count"], 1024, MAX_MEDIA_BYTES, "source bytes")
    if not isinstance(row["group_id"], str) or not 1 <= len(row["group_id"]) <= 100 or not all(
            c.isascii() and (c.isalnum() or c in "-_./") for c in row["group_id"]):
        raise SourceGateError("bounded no-label source family required")
    if row["split"] not in ("train", "calibration", "holdout"):
        raise SourceGateError("noncanonical source split")
    return path


def verify_attested_plan(plan, *, fetch=None, expected_prior_sha256=None):
    """Verify complete REAL source bytes; returns only receipts, never samples.

    fetch(url, maximum) is injectable for offline deterministic tests; a
    production caller always uses read_url with bounded public GitHub URLs.
    Do not invoke a Head, decoder, labels, user-controlled URLs or training.
    """
    if fetch is None:
        fetch = read_url
    if not isinstance(plan, dict) or set(plan) != {"schema", "repository", "revision", "prior_source_ids",
                                                 "license_path", "license_git_blob_sha1",
                                                 "readme_path", "readme_git_blob_sha1", "sources"}:
        raise SourceGateError("exact attested-source-plan.v1 schema required")
    if plan["schema"] != "hepta.independent-video-source-attestation.v1":
        raise SourceGateError("unsupported attested source schema")
    repo = plan["repository"]
    if not isinstance(repo, str) or REPO_RE.fullmatch(repo) is None:
        raise SourceGateError("canonical owner/repository required")
    rev = _sha1(plan["revision"], "commit revision")
    license_path = checked_path(plan["license_path"])
    readme_path = checked_path(plan["readme_path"])
    license_blob = _sha1(plan["license_git_blob_sha1"], "license")
    readme_blob = _sha1(plan["readme_git_blob_sha1"], "readme")
    if license_path == readme_path:
        raise SourceGateError("distinct license and media attribution required")
    if plan["prior_source_ids"] != prior_ids() or expected_prior_sha256 != prior_pin():
        raise SourceGateError("actual full exposed-history inventory and external pin required")
    rows = plan["sources"]
    if not isinstance(rows, list) or not 6 <= len(rows) <= 64:
        raise SourceGateError("at least six prospective independent source declarations required")
    paths = [_exact_media(row) for row in rows]
    if len(set(paths)) != len(paths):
        raise SourceGateError("duplicate source path")
    known_blobs = set(_OLD_360.values()) | set(_EXPOSED_CC0.values())
    candidate_blobs = [row["git_blob_sha1"] for row in rows]
    if any(blob in known_blobs for blob in candidate_blobs):
        # Old source-id constructors differ from the current canonical one;
        # an exact byte-identical video must not acquire a new ID via its path.
        raise SourceGateError("exposed original video Git blob cannot be relabeled as new")
    if len(set(candidate_blobs)) != len(candidate_blobs):
        raise SourceGateError("duplicate original Git blob across candidate paths")
    if sum(row["byte_count"] for row in rows) > MAX_TOTAL_MEDIA_BYTES:
        raise SourceGateError("total original bytes exceed bounded research acquisition")
    # Inspect authority and complete Git-tree identities before any media acquisition.
    commit_url = f"https://api.github.com/repos/{repo}/git/commits/{rev}"
    commit = _decode(fetch(commit_url, MAX_TREE_BYTES))
    if not isinstance(commit, dict) or commit.get("sha") != rev or not isinstance(commit.get("tree"), dict):
        raise SourceGateError("publisher git commit drift")
    tree_sha = _sha1(commit["tree"].get("sha"), "commit tree")
    tree_url = f"https://api.github.com/repos/{repo}/git/trees/{tree_sha}?recursive=1"
    tree = _decode(fetch(tree_url, MAX_TREE_BYTES))
    if (not isinstance(tree, dict) or tree.get("sha") != tree_sha or tree.get("truncated") is not False or
            not isinstance(tree.get("tree"), list) or len(tree["tree"]) > MAX_TREE_MEMBERS):
        raise SourceGateError("complete exact immutable publisher tree required")
    entries = {}
    for entry in tree["tree"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise SourceGateError("malformed Git tree entry")
        path = entry["path"]
        if path in entries:
            raise SourceGateError("duplicate path in publisher tree")
        entries[path] = entry
    needed = [(license_path, license_blob, None), (readme_path, readme_blob, None)]
    needed += [(row["path"], row["git_blob_sha1"], row["byte_count"]) for row in rows]
    for path, expected_blob, expected_size in needed:
        ent = entries.get(path)
        if (not isinstance(ent, dict) or ent.get("mode") != "100644" or
                ent.get("type") != "blob" or ent.get("sha") != expected_blob or
                type(ent.get("size")) is not int or ent["size"] < 1 or
                (expected_size is not None and ent["size"] != expected_size)):
            raise SourceGateError("publisher Git tree identity/size drift: " + path)
    att = {}
    for kind, path, blob in (("LICENSE", license_path, license_blob), ("README", readme_path, readme_blob)):
        raw = fetch(f"https://raw.githubusercontent.com/{repo}/{rev}/{path}", MAX_LICENSE_BYTES)
        if not isinstance(raw, bytes) or not raw or git_blob(raw) != blob:
            raise SourceGateError("publisher exact license/attribution bytes drift")
        if kind == "LICENSE" and b"CC0 1.0 Universal" not in raw:
            raise SourceGateError("expected publisher CC0 1.0 declaration absent")
        if kind == "README" and b"CC0" not in raw and b"Creative Commons Zero" not in raw:
            raise SourceGateError("publisher all-assets CC0 declaration absent")
        att[kind] = {"path": path, "git_blob_sha1": blob, "sha256": sha256(raw)}
    candidates = []
    for row in rows:
        path = row["path"]
        raw = fetch(f"https://raw.githubusercontent.com/{repo}/{rev}/{path}", MAX_MEDIA_BYTES)
        if (not isinstance(raw, bytes) or len(raw) != row["byte_count"] or
                git_blob(raw) != row["git_blob_sha1"] or
                raw.startswith(b"version https://git-lfs.github.com/spec/v1")):
            raise SourceGateError("exact original publisher media bytes drift: " + path)
        source_id = sha256(canonical([repo, rev, path, row["git_blob_sha1"]]))
        candidates.append({"source_id": source_id, "media_sha256": sha256(raw),
                           "split": row["split"], "group_id": row["group_id"]})
    # Reuse the strict v1 identity-family check with identities ONLY derived
    # from actual Git-object and original bytes, never from user declarations.
    v1 = {"schema": "hepta.independent-video-source-gate.v1",
          "prior_source_ids": plan["prior_source_ids"], "candidate_sources": candidates,
          "candidate_repository": repo, "candidate_revision": rev}
    result = verify(v1, expected_prior_sha256=expected_prior_sha256)
    return {"schema": "hepta.independent-video-source-attestation-result.v1",
            "input_plan_sha256": sha256(canonical(plan)), "publisher_repository": repo,
            "publisher_commit": rev, "publisher_tree_sha1": tree_sha,
            "publisher_declared_license": "CC0-1.0", "license_provenance": att,
            "source_receipts": [dict(candidate, path=row["path"], git_blob_sha1=row["git_blob_sha1"],
                                     original_file_bytes=row["byte_count"])
                                for candidate, row in zip(candidates, rows)],
            "legacy_and_exposed_cc0_prior_count": len(prior_ids()),
            "original_video_bytes_read": sum(row["byte_count"] for row in rows),
            "publisher_original_bytes_verified": True,
            "identity_preflight": result,
            "legal_rights_independently_verified": False,
            "semantic_de_duplication_checked": False,
            "source_family_independence_certified": False,
            "pretraining_contamination_checked": False,
            "labels_accessed": False, "independent_model_quality_established": False,
            "production_accepted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--prior-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = _decode(args.plan.read_bytes())
    receipt = verify_attested_plan(plan, expected_prior_sha256=args.prior_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f:
        f.write(json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=True))
        f.write("\n")


if __name__ == "__main__":
    main()
