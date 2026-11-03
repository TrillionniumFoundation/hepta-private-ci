"""SHA-verified non-UTF8 source blob for the frozen public-project PR cohort.

No model inference, PR review, human gold labels, historical discussion, or
production qualification. Fetches one precommitted LATIN-1 file as base64 from
GitHub's Git object API without lossy Unicode conversion.
"""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess

SCHEMA = "hepta.memorycell.heldout-nonutf8-blob-recovery.v1"
REPOSITORY = "denoland/deno"
COMMIT = "707fd96fabc462d710b129e54dbbbb71b51fcd5e"
ROOT_TREE = "5568faeb6fb11a6eadb70e7b07638a4ab1ddaee5"
PATH = "tests/testdata/encoding/iso-8859-1.ts"
BLOB = "a772b57bdd5aa26fbedd07cb057b9006239e784e"
CUTOFF = "2026-10-12T16:05:00Z"
MANIFEST_SHA256 = "cf2b783325d0f1b483953336041476e61877cdb547ad173adcd402f578bf3277"
MAX_BLOB = 65536


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate API JSON key")
            result[key] = value
        return result

    return json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite API JSON")),
    )


def git_blob_sha(value):
    return hashlib.sha1(
        b"blob " + str(len(value)).encode("ascii") + b"\0" + value
    ).hexdigest()


def recover_blob(response, expected_sha=BLOB):
    if (
        response.get("sha") != expected_sha
        or response.get("encoding") != "base64"
        or type(response.get("size")) is not int
        or not 0 < response["size"] <= MAX_BLOB
        or not isinstance(response.get("content"), str)
    ):
        raise ValueError("original binary Git object identity mismatch")
    try:
        data = base64.b64decode(
            response["content"].replace("\n", ""), validate=True
        )
    except (ValueError, base64.binascii.Error):
        raise ValueError("invalid original base64 blob") from None
    if len(data) != response["size"] or git_blob_sha(data) != expected_sha:
        raise ValueError("canonical original Git SHA-1 mismatch")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        raise ValueError("non-UTF8 source control unexpectedly became UTF-8")
    return data


def tree_entry(tree, expected_sha, entry_name, expected_type):
    if (
        tree.get("sha") != expected_sha
        or tree.get("truncated") is True
        or not isinstance(tree.get("tree"), list)
    ):
        raise ValueError("Git tree or nontruncated inventory mismatch")
    matches = [x for x in tree["tree"] if x.get("path") == entry_name]
    if len(matches) != 1 or matches[0].get("type") != expected_type:
        raise ValueError("original tree path/type binding missing")
    sha = matches[0].get("sha")
    if not isinstance(sha, str) or len(sha) != 40:
        raise ValueError("invalid bound original object SHA")
    return sha


def validate_manifest(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("regular frozen source manifest required")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError("original task manifest SHA-256 changed")
    manifest = strict_json(raw)
    if manifest.get("source_cut_utc") != CUTOFF:
        raise ValueError("source cut drift")
    cases = [c for c in manifest["cases"] if c.get("repo") == REPOSITORY]
    if len(cases) != 1:
        raise ValueError("unique pinned Deno repository task required")
    case = cases[0]
    if case.get("head_sha") != COMMIT or case.get("tree_sha") != ROOT_TREE:
        raise ValueError("original Deno PR head changed")
    matching = [x for x in case["files"] if x.get("path") == PATH]
    if len(matching) != 1 or matching[0].get("blob_sha") != BLOB:
        raise ValueError("original Deno binary file path changed")
    return manifest


def capture(gh_api, manifest_path):
    validate_manifest(manifest_path)
    commit = gh_api(f"/repos/{REPOSITORY}/git/commits/{COMMIT}")
    if (
        commit.get("sha") != COMMIT
        or commit.get("tree", {}).get("sha") != ROOT_TREE
        or commit.get("committer", {}).get("date", "") > CUTOFF
    ):
        raise ValueError("original historical Git commit/cut changed")
    cursor = ROOT_TREE
    parts = PATH.split("/")
    for segment in parts[:-1]:
        response = gh_api(f"/repos/{REPOSITORY}/git/trees/{cursor}")
        cursor = tree_entry(response, cursor, segment, "tree")
    leaves = gh_api(f"/repos/{REPOSITORY}/git/trees/{cursor}")
    actual = tree_entry(leaves, cursor, parts[-1], "blob")
    if actual != BLOB:
        raise ValueError("original file tree/blob mismatch")
    binary = recover_blob(gh_api(f"/repos/{REPOSITORY}/git/blobs/{BLOB}"))
    return {
        "schema": SCHEMA,
        "source_cut_utc": CUTOFF,
        "original_task_manifest_sha256": MANIFEST_SHA256,
        "original_repository": REPOSITORY,
        "pinned_head_commit": COMMIT,
        "pinned_head_tree": ROOT_TREE,
        "original_path": PATH,
        "original_blob_sha1": BLOB,
        "verified_binary_bytes": len(binary),
        "latin1_decodable": True,
        "utf8_recode_forbidden": True,
        "head_tree_path_binding_verified": True,
        "canonical_original_git_blob_hash_recomputed": True,
        "source_bytes_reuploaded": False,
        "other_31_extension_blobs_newly_checked": False,
        "model_inference_calls": 0,
        "task_answers_or_gold_labels_produced": False,
        "human_source_sufficiency_certified": False,
        "source_families_independent_review_certified": False,
        "parameter_memory_gain_established": False,
        "production_accepted": False,
    }


def github_api(path):
    command = ["gh", "api", "-H", "Accept: application/vnd.github+json", path]
    reply = subprocess.run(
        command, capture_output=True, check=True, timeout=30
    )
    if len(reply.stdout) > 1024 * 1024:
        raise ValueError("bounded GitHub response required")
    return strict_json(reply.stdout)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError("refuse to overwrite immutable receipt")
    receipt = capture(github_api, args.manifest)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
