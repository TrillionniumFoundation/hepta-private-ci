#!/usr/bin/env python3
"""Transfer reviewed immutable bytes to Git objects; never update a ref."""

import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import urllib.error
import urllib.request

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
ORIGIN_RESULT = "cd88dc0a753dedc84a7f9e6cad1a903a569d34eb661f471d1fb430ad434d4252"
MANIFEST = "experiments/multimodal_output_portfolio/closure_20261028/ci/object-transfer/MANIFEST.json"
MAX_RAW_BYTES = 2_000_000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular_bytes(root, relative):
    path = Path(relative)
    require(not path.is_absolute() and ".." not in path.parts, "Unsafe input path")
    current = root
    for part in path.parts:
        current = current / part
        require(not current.is_symlink(), "Symlink input refused")
    require(stat.S_ISREG(current.stat().st_mode), "Nonregular input refused")
    return current.read_bytes()


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob_sha": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def checked_payloads(repository, artifact):
    manifest = json.loads(regular_bytes(repository, MANIFEST))
    require(
        manifest.get("schema") == "hepta.reviewed-object-transfer.v1", "Wrong schema"
    )
    require(manifest.get("repository") == REPOSITORY, "Wrong repository")
    origin = manifest["origin"]
    require(
        origin
        == {
            "run_id": 40656660435,
            "artifact_id": 12801988362,
            "result_sha256": ORIGIN_RESULT,
        },
        "Wrong producer",
    )
    result = regular_bytes(artifact, "RESULT.json")
    require(
        hashlib.sha256(result).hexdigest() == ORIGIN_RESULT, "Producer result mismatch"
    )
    rows = []
    seen = set()
    for entry in manifest["files"]:
        require(entry["path"] not in seen, "Duplicate object path")
        seen.add(entry["path"])
        require(0 < entry["bytes"] <= MAX_RAW_BYTES, "Object exceeds reviewed bound")
        source = entry["source"]
        if source["kind"] == "artifact":
            require(
                entry["path"] in ("MODULE.bazel.lock", "codex-rs/Cargo.lock"),
                "Unexpected artifact payload",
            )
            require(source["path"] == "files/" + entry["path"], "Wrong artifact path")
            raw = regular_bytes(artifact, source["path"])
        elif source["kind"] == "gzip-base64-parts":
            encoded = []
            for part in source["parts"]:
                value = regular_bytes(repository, part["path"])
                require(
                    len(value) == part["bytes"]
                    and hashlib.sha256(value).hexdigest() == part["sha256"],
                    "Encoded part mismatch",
                )
                encoded.append(value.strip())
            compressed = base64.b64decode(b"".join(encoded), validate=True)
            import io

            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
                raw = stream.read(MAX_RAW_BYTES + 1)
                require(
                    len(raw) <= MAX_RAW_BYTES and not stream.read(1),
                    "Decoded object exceeds bound",
                )
        else:
            raise ValueError("Unknown payload encoding")
        require(
            identity(raw)
            == {key: entry[key] for key in ("bytes", "sha256", "git_blob_sha")},
            "Object identity mismatch",
        )
        rows.append((entry, raw))
    require(bool(rows), "Empty transfer refused")
    return rows


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise ValueError("Authenticated API redirect refused")


def publish_blob(raw, expected_sha, token):
    body = json.dumps(
        {"content": base64.b64encode(raw).decode(), "encoding": "base64"}
    ).encode()
    request = urllib.request.Request(
        "https://api.github.com/repos/" + REPOSITORY + "/git/blobs",
        data=body,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(
            request, timeout=60
        ) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError("Git object API returned HTTP " + str(error.code)) from None
    require(result.get("sha") == expected_sha, "Remote Git object identity mismatch")
    return result["sha"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    payloads = checked_payloads(args.repository.resolve(), args.artifact.resolve())
    record = {
        "schema": "hepta.reviewed-object-transfer-result.v1",
        "published": False,
        "ref_updates": 0,
        "files": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n")
    token = ""
    if args.publish:
        require(
            os.environ.get("GITHUB_REPOSITORY") == REPOSITORY,
            "Unexpected execution repository",
        )
        token = os.environ.get("GH_TOKEN", "")
        require(bool(token), "Job token is missing")
    for entry, raw in payloads:
        if args.publish:
            publish_blob(raw, entry["git_blob_sha"], token)
        record["files"].append(
            {"path": entry["path"], **identity(raw), "published": args.publish}
        )
        args.output.write_text(json.dumps(record, indent=2) + "\n")
    record["published"] = args.publish
    args.output.write_text(json.dumps(record, indent=2) + "\n")
    print(
        json.dumps(
            {"objects": len(payloads), "published": args.publish, "ref_updates": 0}
        )
    )


if __name__ == "__main__":
    main()
