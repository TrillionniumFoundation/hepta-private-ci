"""Verify exact immutable spelling contexts before applying reviewed exceptions.

Only identified archive payloads and complete reviewed literal lines are exempt.
The normal word dictionaries, regular expressions and existing skips stay fixed.
"""

import argparse
import base64
import configparser
import hashlib
import json
from pathlib import Path, PurePosixPath


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def checked_bytes(root, record):
    relative = PurePosixPath(record["path"])
    if relative.is_absolute() or ".." in relative.parts or any(c in record["path"] for c in "*?[]\\"):
        raise ValueError("Review paths must be exact repository-relative paths")
    path = root.joinpath(*relative.parts)
    path.resolve().relative_to(root.resolve())
    data = path.read_bytes()
    if sha256(data) != record["sha256"]:
        raise ValueError("Reviewed file changed: " + record["path"])
    if "bytes" in record and len(data) != record["bytes"]:
        raise ValueError("Reviewed byte count changed: " + record["path"])
    identity = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if identity != record["git_blob"]:
        raise ValueError("Reviewed Git identity changed: " + record["path"])
    return data


def verify(root):
    root = Path(root)
    review = json.loads((root / "tools/codespell_frozen_review.json").read_text())
    if review["schema"] != "codespell.frozen-context-review.v1":
        raise ValueError("Unknown review schema")
    literal_file = root / review["literal_file"]
    raw_literals = literal_file.read_bytes()
    if sha256(raw_literals) != review["literal_file_sha256"]:
        raise ValueError("The reviewed literal list changed")
    actual_literals = raw_literals.decode("utf-8").splitlines()
    expected_literals, findings = [], 0
    for entry in review["text_files"]:
        lines = checked_bytes(root, entry).decode("utf-8").splitlines()
        for line in entry["lines"]:
            number = line["line"]
            if not 1 <= number <= len(lines):
                raise ValueError("Invalid reviewed line number")
            literal = lines[number - 1].rstrip()
            if not literal or sha256(literal.encode()) != line["sha256"]:
                raise ValueError("Reviewed literal context changed: " + entry["path"])
            expected_literals.append(literal)
            findings += line["findings"]
    if (len(actual_literals) != len(set(actual_literals))
            or set(actual_literals) != set(expected_literals)
            or len(actual_literals) != review["unique_literal_lines"]
            or findings != review["text_findings"]):
        raise ValueError("Literal exclusions differ from the exact reviewed contexts")

    manifest_paths = set()
    for entry in review["transport_manifests"]:
        checked_bytes(root, entry)
        manifest_paths.add(entry["path"])
    payload_paths, decoded_count = set(), 0
    for entry in review["payloads"]:
        if entry["path"] in payload_paths:
            raise ValueError("Duplicate reviewed payload path")
        payload_paths.add(entry["path"])
        data = checked_bytes(root, entry)
        if entry["manifest"] is not None and entry["manifest"] not in manifest_paths:
            raise ValueError("Unverified transport manifest reference")
        if entry["kind"] == "base64":
            decoded = base64.b64decode(data, validate=True)
            if len(decoded) != entry["decoded_bytes"] or sha256(decoded) != entry["decoded_sha256"]:
                raise ValueError("Decoded payload identity changed")
            decoded_count += 1
        elif entry["kind"] == "binary":
            if not entry["invalid_utf8"] or data.count(b"\0") != entry["nul_bytes"] or not entry["nul_bytes"]:
                raise ValueError("Binary payload classification changed")
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                raise ValueError("Reviewed binary part is now UTF-8 text")
        else:
            raise ValueError("Unknown payload classification")

    config = configparser.ConfigParser()
    config.read(root / ".codespellrc")
    settings = dict(config["codespell"])
    skips = {item.strip() for item in settings.pop("skip").split(",") if item.strip()}
    additions = {"./" + path for path in payload_paths}
    if not additions <= skips:
        raise ValueError("A reviewed payload is missing its exact skip")
    if sha256(canonical(sorted(skips - additions))) != review["existing_skip_set_sha256"]:
        raise ValueError("Unreviewed skip additions or changes to existing scope")
    if sha256(canonical(settings)) != review["non_skip_configuration_sha256"]:
        raise ValueError("Word dictionaries or other spelling settings changed")
    if sha256((root / ".codespellignore").read_bytes()) != review["ignore_words_file_sha256"]:
        raise ValueError("The existing global word list changed")
    return dict(text_files=len(review["text_files"]), reviewed_findings=findings,
                exact_literal_lines=len(actual_literals), payload_files=len(payload_paths),
                decoded_base64_payloads=decoded_count, binary_payloads=len(payload_paths) - decoded_count,
                ordinary_text_checks_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(verify(args.repository_root), sort_keys=True))


if __name__ == "__main__":
    main()
