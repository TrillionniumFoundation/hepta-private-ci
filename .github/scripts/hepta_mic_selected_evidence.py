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


def read_regular(path):
    before = path.lstat()
    require(
        stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "NON_REGULAR_EVIDENCE"
    )
    require(before.st_size <= 64 * 1024 * 1024, "EVIDENCE_TOO_LARGE")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        require(
            (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
            "EVIDENCE_REPLACED",
        )
        raw = stream.read(64 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    require(
        before.st_size == len(raw) == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns,
        "EVIDENCE_CHANGED",
    )
    return raw


def collect(private):
    from hepta_mic_selected import diagnostic
    from hepta_mic_selected import scanner_gate
    from hepta_mic_selected_contract import expected_commands
    from hepta_mic_selected_contract import outcome_guard
    from hepta_mic_selected_contract import selected_cases
    from hepta_mic_selected_contract import version_guard
    from hepta_mic_selected_guard import source_guard

    payload = private / "payload"
    scan = scanner_gate("collect")
    expected = expected_commands()
    log_names = {
        "logs/" + stage + suffix
        for stage in expected
        for suffix in (".stdout.log", ".stderr.log")
    }
    required = {
        "source-before.json",
        "readiness.json",
        "source-after.json",
        "result.json",
        "junit.xml",
    } | log_names
    files, rejected = {}, {}
    for path in sorted(payload.rglob("*")):
        require(not path.is_symlink() and not path.is_junction(), "LINK_IN_EVIDENCE")
        if path.is_dir():
            continue
        name = path.relative_to(payload).as_posix()
        require(name in required, "UNEXPECTED_EVIDENCE_PATH")
        scan(name.encode())
        raw = read_regular(path)
        try:
            scan(raw)
        except ProposalError as error:
            rejected[name] = {"identity": identity(raw), "rejection_code": str(error)}
        files[name] = raw
    result = json.loads(files.get("result.json", b'{"validated":false}'))
    validated = result.get("validated") is True and not rejected
    validation_failure = None
    try:
        if validated:
            require(files.keys() == required, "INCOMPLETE_SUCCESS_EVIDENCE")
            require(
                [item["stage"] for item in result["commands"]] == list(expected)
                and all(item["exit_code"] == 0 for item in result["commands"]),
                "INCOMPLETE_NATIVE_COMMANDS",
            )
            require(
                all(
                    item["argv"] == expected[item["stage"]]
                    and item.get("cwd_relative_to_bound_source") == "codex-rs"
                    for item in result["commands"]
                ),
                "NATIVE_ARGV_MISMATCH",
            )
            require(result.get("native_started") is True, "NATIVE_NOT_STARTED")
            require(
                files["source-before.json"] == files["source-after.json"],
                "SOURCE_CHANGED",
            )
            version_guard(files)
            selected_cases(files["logs/list.stdout.log"])
            proof = outcome_guard(
                files["logs/run.stdout.log"],
                files["logs/run.stderr.log"],
                files["junit.xml"],
            )
            require(
                all(result.get(key) == value for key, value in proof.items()),
                "OUTCOME_CHANGED_BEFORE_COLLECTION",
            )
            require(
                json.loads(files["source-after.json"]) == source_guard(),
                "SOURCE_PROOF_MISMATCH",
            )
            source = json.loads(files["source-after.json"])
            require(
                json.loads(files["readiness.json"])
                == {
                    "head": source["head"],
                    "tree": source["tree"],
                    "scanner_ready_after_tools": True,
                },
                "SCANNER_READINESS_MISMATCH",
            )
    except Exception as error:
        validated = False
        validation_failure = (
            str(error) if isinstance(error, ProposalError) else type(error).__name__
        )
    accepted = {name: raw for name, raw in files.items() if name not in rejected}
    inventory = {
        name: {
            "identity": identity(files[name]) if name in files else None,
            "status": "REJECTED"
            if name in rejected
            else "ACCEPTED"
            if name in files
            else "MISSING",
            "rejection_code": rejected.get(name, {}).get("rejection_code"),
        }
        for name in sorted(required)
    }
    receipt = {
        "validated": validated,
        "validation_failure": validation_failure,
        "raw_logs_rewritten": False,
        "raw_logs_uploaded": accepted.keys() == required,
        "partial_evidence_available": bool(accepted) and accepted.keys() != required,
        "file_inventory": inventory,
        "uploaded_files": {name: identity(raw) for name, raw in accepted.items()},
        "scanner_rejections": rejected,
        "original_files": {name: identity(raw) for name, raw in files.items()},
        "raw_rejected_bytes_encoded_or_uploaded": False,
        "final_passed_cases": result.get("final_passed_cases") if validated else None,
        "total_native_attempts": result.get("total_native_attempts")
        if validated
        else None,
        "cases_with_retries": result.get("cases_with_retries") if validated else None,
    }
    files = accepted
    receipt_raw = (json.dumps(receipt, indent=2) + "\n").encode()
    scan(receipt_raw)
    files["evidence-manifest.json"] = receipt_raw
    public = private / "public"
    public.mkdir()
    for name, raw in files.items():
        target = public / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
        require(target.read_bytes() == raw, "PUBLIC_COPY_MISMATCH")
    require(
        {
            path.relative_to(public).as_posix()
            for path in public.rglob("*")
            if path.is_file()
        }
        == set(files),
        "PUBLIC_INVENTORY_MISMATCH",
    )
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(
            "safe_for_upload=true\npublic_dir="
            + str(public)
            + "\nvalidated="
            + str(validated).lower()
            + "\n"
        )
    diagnostic(
        "collect",
        "PASS" if validated else "FAIL",
        "OK" if validated else "EVIDENCE_REJECTED",
    )
    return 0
