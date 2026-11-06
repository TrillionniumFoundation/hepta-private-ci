"""Retain original proposal logs only after the established credential/URI gate."""

import base64
import hashlib
import json
import os
import re
import stat
import urllib.parse


class ProposalError(Exception):
    pass


def require(condition, code):
    if not condition:
        raise ProposalError(code)


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def scanner(fixed_bazel_source_uris=()):
    # The syntax and four percent-decoding layers follow the accepted cargo-deny collector.
    secret_name = re.compile(
        r"token|password|passwd|secret|credential|api.?key|access.?key|auth", re.I
    )
    secrets = {
        value for key, value in os.environ.items() if value and secret_name.search(key)
    }
    require(all(len(value) >= 8 for value in secrets), "AMBIGUOUS_SHORT_CREDENTIAL")
    needles = set(secrets)
    for value in secrets:
        needles.add(base64.b64encode(value.encode()).decode())
        needles.add(json.dumps(value, ensure_ascii=True)[1:-1])
    syntax = re.compile(
        r"(?i)\b(?:authorization|proxy[-_ ]?authorization|cookie|set[-_ ]?cookie|"
        r"password|passwd|access[-_ ]?token|refresh[-_ ]?token|token|"
        r"api[-_ ]?key|client[-_ ]?secret|secret)\b[\"']?\s*[:=]\s*\S|"
        r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}|"
        r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----|"
        r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b"
    )
    uri = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s<>\"']+")
    ansi = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

    def scan(raw, fixed_source=False):
        try:
            view = raw.decode("utf-8", "strict")
        except UnicodeError:
            raise ProposalError("NON_UTF8_EVIDENCE") from None
        for layer in range(5):
            view = ansi.sub("", view)
            require(
                not any(value in view for value in needles), "KNOWN_CREDENTIAL_FOUND"
            )
            require(
                all(
                    (ord(c) >= 32 and not 127 <= ord(c) <= 159) or c in "\n\r\t"
                    for c in view
                ),
                "UNSUPPORTED_CONTROL_BYTES",
            )
            if not fixed_source:
                require(not syntax.search(view), "CREDENTIAL_SYNTAX_FOUND")
                for match in uri.finditer(view):
                    try:
                        parsed = urllib.parse.urlsplit(match.group().rstrip(".,);]}"))
                    except ValueError:
                        raise ProposalError("UNPARSEABLE_URI") from None
                    require(
                        not parsed.username and not parsed.password, "URI_CREDENTIALS"
                    )
                    if parsed.query:
                        try:
                            query = urllib.parse.parse_qsl(
                                parsed.query, strict_parsing=True
                            )
                        except ValueError:
                            raise ProposalError("URI_UNRECOGNIZED_QUERY") from None
                        require(
                            len(query) == 1
                            and query[0][0] in ("branch", "tag", "rev")
                            and re.fullmatch(r"[A-Za-z0-9._/+~^-]{1,256}", query[0][1]),
                            "URI_UNRECOGNIZED_QUERY",
                        )
                    if parsed.fragment:
                        cargo = re.fullmatch(
                            r"(?:[0-9a-fA-F]{40}|(?:[A-Za-z0-9_-]+[@:])?"
                            r"[0-9]+(?:\.[0-9]+){0,2}(?:[-+][A-Za-z0-9.+-]+)?)",
                            parsed.fragment,
                        )
                        docs = (
                            parsed.hostname == "embarkstudios.github.io"
                            and parsed.path.startswith("/cargo-deny/")
                        ) or (
                            parsed.hostname == "doc.rust-lang.org"
                            and parsed.path.startswith("/cargo/")
                        )
                        known_source = (
                            match.group().rstrip(".,);]}") in fixed_bazel_source_uris
                        )
                        require(
                            cargo
                            or (
                                docs
                                and re.fullmatch(
                                    r"[A-Za-z0-9_.-]{1,128}", parsed.fragment
                                )
                            )
                            or known_source,
                            "URI_UNRECOGNIZED_FRAGMENT",
                        )
            if layer == 4:
                break
            try:
                decoded = urllib.parse.unquote(view, encoding="utf-8", errors="strict")
            except UnicodeError:
                raise ProposalError("UNPARSEABLE_PERCENT_ENCODING") from None
            if decoded == view:
                break
            view = decoded

    return scan


def collect(private, spec, original_manifest):
    scan = scanner(spec["fixed_bazel_source_uris"])
    payload = private / "payload"
    require(payload.is_dir() and not payload.is_symlink(), "MISSING_PAYLOAD")
    archive_hashes = {
        "archives/" + c["name"] + "-" + c["version"] + ".crate": c["checksum"]
        for c in spec["crates"]
    }
    result = json.loads((payload / "result.json").read_bytes())
    require(type(result.get("proposal_validated")) is bool, "INVALID_VALIDATION_FLAG")
    require(
        identity(original_manifest)["git_blob"]
        == spec["baseline_blobs"]["codex-rs/Cargo.toml"],
        "FIXED_MANIFEST_AUTHORITY_MISMATCH",
    )
    # Only the unchanged, committed workspace manifest is fixed source.
    # Raw logs, generated locks and the generated patch use every syntax/URI gate.
    fixed = {"before/Cargo.toml", "after/Cargo.toml"}
    stages = {
        "cargo-version",
        "rustc-version",
        "deny-version",
        "just-version",
        "bazel-version",
        "workspace-before",
        "workspace-after",
        "baseline-bazel-lock-check",
        "cargo-lock-update",
        "cargo-lock-repeat",
        "cargo-existing-itertools-update",
        "cargo-existing-getrandom-update",
        "cargo-existing-itertools-repeat",
        "cargo-existing-getrandom-repeat",
        "bazel-lock-update",
        "bazel-lock-check",
        "bazel-lock-repeat",
        "bazel-lock-check-repeat",
        "cargo-deny-original",
        "proposal-failure",
        "workspace-before.stderr",
        "workspace-after.stderr",
        "cargo-version.stderr",
        "rustc-version.stderr",
        "deny-version.stderr",
        "just-version.stderr",
        "bazel-version.stderr",
        "features-after",
        "features-after.stderr",
    }
    allowed = (
        set(archive_hashes)
        | {"logs/" + s + ".log" for s in stages}
        | {
            phase + "/" + n
            for phase in ("before", "after")
            for n in ("Cargo.toml", "Cargo.lock", "MODULE.bazel.lock")
        }
        | {
            "source-before.json",
            "source-after.json",
            "result.json",
            "upgrade-spec.json",
            "archive-receipts.json",
            "upstream-proof.json",
            "feature-proof.json",
            "lock-graph-proof.json",
            "module-lock-proof.json",
            "proposal.patch",
        }
    )
    files = {}
    for path in sorted(payload.rglob("*")):
        require(not path.is_symlink(), "SYMLINK_IN_PAYLOAD")
        if path.is_dir():
            continue
        name = path.relative_to(payload).as_posix()
        require(name in allowed, "UNEXPECTED_PAYLOAD_PATH")
        scan(name.encode())
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            before = os.fstat(stream.fileno())
            require(
                stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                "NON_REGULAR_PAYLOAD",
            )
            require(before.st_size <= 64 * 1024 * 1024, "PAYLOAD_FILE_TOO_LARGE")
            raw = stream.read(64 * 1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
            require(
                before.st_size == len(raw) == after.st_size
                and before.st_mtime_ns == after.st_mtime_ns,
                "PAYLOAD_CHANGED_DURING_READ",
            )
        if name in archive_hashes:
            require(
                identity(raw)["sha256"] == archive_hashes[name],
                "ARCHIVE_CHECKSUM_MISMATCH",
            )
        else:
            if name == "before/Cargo.toml":
                require(raw == original_manifest, "BEFORE_MANIFEST_NOT_FIXED_SOURCE")
            if name == "after/Cargo.toml":
                require(raw == original_manifest, "AFTER_MANIFEST_NOT_FIXED_TRANSFORM")
            if name == "proposal.patch":
                require(
                    result["proposal_validated"] is True
                    and identity(raw) == result["validated_payload_identities"][name],
                    "UNVALIDATED_PATCH",
                )
            scan(raw, fixed_source=name in fixed)
        files[name] = raw
        require(
            sum(len(b) for b in files.values()) <= 256 * 1024 * 1024,
            "PAYLOAD_TOTAL_TOO_LARGE",
        )
    require(
        "result.json" in files and "source-before.json" in files, "INCOMPLETE_RECEIPT"
    )
    if result["proposal_validated"]:
        require(
            set(result["validated_payload_identities"])
            == {
                "proposal.patch",
                "after/Cargo.toml",
                "after/Cargo.lock",
                "after/MODULE.bazel.lock",
            },
            "INCOMPLETE_VALIDATED_OUTPUT_SET",
        )
        require(
            all(
                name in files and identity(files[name]) == digest
                for name, digest in result["validated_payload_identities"].items()
            ),
            "VALIDATED_OUTPUT_CHANGED",
        )
    receipt = {
        "schema": "vodozemac-proposal-upload-gate-v1",
        "safe_for_upload": True,
        "proposal_validated": result["proposal_validated"],
        "files": {n: identity(b) for n, b in files.items()},
        "raw_logs_rewritten": False,
        "credential_fingerprints_recorded": False,
        "privacy_scope": "Known credential values plus four percent-decoding layers; raw logs and generated locks also use the original authorization/URI gate. Only the byte-identical original workspace manifest uses fixed-source provenance, not a claim of general unknown-secret detection. Official binary archives require their exact independently checked crate-index checksum.",
    }
    raw = (json.dumps(receipt, indent=2) + "\n").encode()
    scan(raw)
    files["artifact-manifest.json"] = raw
    public = private / "public"
    scan(str(public).encode())
    public.mkdir(mode=0o700)
    for name, raw in files.items():
        target = public / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
        require(target.read_bytes() == raw, "PUBLIC_COPY_MISMATCH")
    require(
        {p.relative_to(public).as_posix() for p in public.rglob("*") if p.is_file()}
        == set(files),
        "PUBLIC_INVENTORY_MISMATCH",
    )
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write("safe_for_upload=true\npublic_dir=" + str(public) + "\n")
        output.write(
            "proposal_validated=" + str(result["proposal_validated"]).lower() + "\n"
        )
    print(
        json.dumps(
            {
                "safe_for_upload": True,
                "proposal_validated": result["proposal_validated"],
                "files": len(files),
            }
        )
    )
