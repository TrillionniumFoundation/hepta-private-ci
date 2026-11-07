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


COMMAND_SLOTS = {}


def register_command_slots(private, payload, expected_commands):
    require(len(expected_commands) == 24, "DIAGNOSTIC_COMMAND_COUNT_CHANGED")
    slots = {}
    for index, row in enumerate(expected_commands):
        phase = row["metadata_phase"]
        stdout = (
            private / ("metadata-" + phase + ".json")
            if phase
            else payload / "logs" / (row["stage"] + ".log")
        )
        stderr = payload / "logs" / (row["stage"] + ".stderr.log")
        slots[stdout] = 2 * index
        slots[stderr] = 2 * index + 1
    require(len(slots) == 48, "DIAGNOSTIC_SLOT_COLLISION")
    COMMAND_SLOTS.clear()
    COMMAND_SLOTS.update(slots)


def observe_command_stat(path, info):
    slot = COMMAND_SLOTS.get(path)
    if slot is not None:
        message = json.dumps(
            {
                "diagnostic": "sha256-command-read-stat-v1",
                "slot": slot,
                "regular": stat.S_ISREG(info.st_mode),
                "nlink": info.st_nlink,
                "size": info.st_size,
            }
        )
        try:
            print(message, flush=True)
        except (OSError, ValueError):
            return


def validate_command_custody(private, payload, result, stages, expected_commands):
    require(
        [entry["stage"] for entry in result["command_exits"]] == list(stages[:-1])
        and all(
            type(entry["exit_code"]) is int and entry["exit_code"] == 0
            for entry in result["command_exits"]
        ),
        "INCOMPLETE_ACTUAL_COMMANDS",
    )
    require(
        len(result["command_exits"]) == len(expected_commands),
        "COMMAND_COUNT_CHANGED",
    )
    for actual, expected in zip(
        result["command_exits"], expected_commands, strict=True
    ):
        require(
            set(actual)
            == (set(expected) - {"metadata_phase"})
            | {"exit_code", "stdout_identity", "stderr_identity"},
            "COMMAND_RECEIPT_FIELDS_CHANGED",
        )
        require(
            {key: actual[key] for key in expected if key != "metadata_phase"}
            == {
                key: value for key, value in expected.items() if key != "metadata_phase"
            },
            "COMMAND_ARGUMENTS_CHANGED",
        )
        phase = expected["metadata_phase"]
        stdout = (
            private / ("metadata-" + phase + ".json")
            if phase
            else payload / "logs" / (expected["stage"] + ".log")
        )
        require(
            identity(read_checked(stdout)) == actual["stdout_identity"],
            "COMMAND_STDOUT_CHANGED",
        )
        require(
            identity(
                read_checked(payload / "logs" / (expected["stage"] + ".stderr.log"))
            )
            == actual["stderr_identity"],
            "COMMAND_STDERR_CHANGED",
        )


def validate_upload_custody(files, result, expected_commands, originals, checked_bytes):
    require(
        all(files[name] == raw for name, raw in checked_bytes.items()),
        "VALIDATED_PAYLOAD_BYTES_CHANGED",
    )
    for actual, expected in zip(
        result["command_exits"], expected_commands, strict=True
    ):
        stage, phase = expected["stage"], expected["metadata_phase"]
        raw = originals[phase] if phase else files["logs/" + stage + ".log"]
        require(
            identity(raw) == actual["stdout_identity"], "UPLOAD_STDOUT_IDENTITY_CHANGED"
        )
        require(
            identity(files["logs/" + stage + ".stderr.log"])
            == actual["stderr_identity"],
            "UPLOAD_STDERR_IDENTITY_CHANGED",
        )


def collect(private, spec, stages, expected_commands):
    payload = private / "payload"
    require(payload.is_dir() and not payload.is_symlink(), "MISSING_PAYLOAD")
    scan = scanner(spec["fixed_bazel_source_uris"])
    register_command_slots(private, payload, expected_commands)
    result_raw = read_checked(payload / "result.json")
    result = json.loads(result_raw)
    checked_bytes = {"result.json": result_raw}
    require(type(result.get("proposal_validated")) is bool, "INVALID_VALIDATION_FLAG")
    source = {item["path"]: item for item in spec["source_files"]}
    allowed = {
        "readiness.json",
        "source-before.json",
        "source-after.json",
        "result.json",
        "proposal-spec.json",
        "cargo-proof.json",
        "metadata-proof.json",
        "module-proof.json",
        "platform-proof.json",
        "proposal.patch",
        "metadata-before-projection.json",
        "metadata-after-projection.json",
        "metadata-custody.json",
    }
    allowed |= {
        "logs/" + name + suffix for name in stages for suffix in (".log", ".stderr.log")
    }
    allowed |= {
        phase + "/" + path
        for phase in ("before", "after")
        for path in source.keys() | set(spec["locks"])
    }
    custody = {}
    originals = {}
    for phase in ("before", "after", "repeat"):
        path = private / ("metadata-" + phase + ".json")
        if not path.exists():
            continue
        raw = read_checked(path)
        outcome = "PASS"
        try:
            scan(raw)
        except ProposalError as error:
            outcome = str(error)
        custody[phase] = {
            "raw_identity": identity(raw),
            "original_scanner_outcome": outcome,
            "raw_uploaded": False,
            "retained_only_in_private_job_storage": True,
        }
        originals[phase] = raw
    if result["proposal_validated"]:
        from sha256_asm_lock_guards import canonical_metadata, metadata_guard

        require(
            set(originals) == {"before", "after", "repeat"}, "MISSING_PRIVATE_METADATA"
        )
        metadata_guard(json.loads(originals["before"]), json.loads(originals["after"]))
        require(
            canonical_metadata(json.loads(originals["repeat"]))
            == canonical_metadata(json.loads(originals["after"])),
            "PRIVATE_METADATA_NOT_REPEATABLE",
        )
        checked_bytes["metadata-proof.json"] = read_checked(
            payload / "metadata-proof.json"
        )
        proof = json.loads(checked_bytes["metadata-proof.json"])
        require(
            proof["raw_identities"]
            == {phase: identity(originals[phase]) for phase in ("before", "after")},
            "RAW_METADATA_IDENTITY_MISMATCH",
        )
        validate_command_custody(private, payload, result, stages, expected_commands)
        for phase in ("before", "after"):
            raw = originals[phase]
            name = "metadata-" + phase + "-projection.json"
            checked_bytes[name] = read_checked(payload / name)
            projection = json.loads(checked_bytes[name])
            require(
                projection == metadata_projection(raw), "METADATA_PROJECTION_NOT_EXACT"
            )
        custody["complete_metadata_compared_before_upload"] = True
    custody["projection_is_lossless"] = False
    custody["full_metadata_not_reconstructable_from_artifact"] = True
    checked_bytes["metadata-custody.json"] = (
        json.dumps(custody, indent=2) + "\n"
    ).encode()
    (payload / "metadata-custody.json").write_bytes(
        checked_bytes["metadata-custody.json"]
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
        fixed_source = False
        if name.startswith(("before/", "after/")):
            phase, relative = name.split("/", 1)
            if relative in source:
                expected = {source[relative]["before_blob"]}
                if phase == "after":
                    expected = (
                        {source[relative]["after_blob"]}
                        if result["proposal_validated"]
                        else expected | {source[relative]["after_blob"]}
                    )
                require(
                    identity(raw)["git_blob"] in expected, "SOURCE_PAYLOAD_NOT_FIXED"
                )
                fixed_source = True
            elif phase == "before":
                require(
                    identity(raw)["git_blob"] == spec["baseline_blobs"][relative],
                    "BASE_LOCK_MISMATCH",
                )
        if name == "proposal.patch":
            require(
                result["proposal_validated"] is True
                and identity(raw) == result["validated_payload_identities"][name],
                "UNVALIDATED_PATCH",
            )
            fixed_source = True
        scan(raw, fixed_source=fixed_source)
        files[name] = raw
        require(
            sum(len(value) for value in files.values()) <= 256 * 1024 * 1024,
            "PAYLOAD_TOTAL_TOO_LARGE",
        )
    require(
        all(files[name] == raw for name, raw in checked_bytes.items()),
        "VALIDATED_PAYLOAD_BYTES_CHANGED",
    )
    require(
        {"result.json", "source-before.json", "proposal-spec.json"} <= files.keys(),
        "MISSING_RECEIPT",
    )
    if result["proposal_validated"]:
        expected = {"proposal.patch"} | {
            "after/" + path for path in source.keys() | set(spec["locks"])
        }
        require(
            set(result["validated_payload_identities"]) == expected,
            "INCOMPLETE_VALIDATED_OUTPUT_SET",
        )
        require(
            all(
                name in files and identity(files[name]) == digest
                for name, digest in result["validated_payload_identities"].items()
            ),
            "OUTPUT_CHANGED",
        )
        require(
            {
                "cargo-proof.json",
                "metadata-proof.json",
                "module-proof.json",
                "platform-proof.json",
                "metadata-before-projection.json",
                "metadata-after-projection.json",
            }
            <= files.keys(),
            "MISSING_GRAPH_PROOF",
        )
    if result["proposal_validated"]:
        from sha256_asm_lock_guards import cargo_guard, module_guard
        from sha256_asm_platform_guards import platform_guard

        required = {
            "source-before.json",
            "source-after.json",
            "readiness.json",
            "result.json",
            "proposal-spec.json",
            "cargo-proof.json",
            "metadata-proof.json",
            "module-proof.json",
            "platform-proof.json",
            "proposal.patch",
            "metadata-before-projection.json",
            "metadata-after-projection.json",
            "metadata-custody.json",
        }
        required |= {
            "before/" + path
            for path, item in source.items()
            if item["before_blob"] is not None
        }
        required |= {"before/" + path for path in spec["locks"]}
        required |= {"after/" + path for path in source.keys() | set(spec["locks"])}
        required |= {
            "logs/" + row["stage"] + ".stderr.log" for row in expected_commands
        }
        required |= {
            "logs/" + row["stage"] + ".log"
            for row in expected_commands
            if not row["stdout_private_only"]
        }
        require(set(files) == required, "INCOMPLETE_OR_EXTRA_VALIDATED_EVIDENCE")
        validate_upload_custody(
            files, result, expected_commands, originals, checked_bytes
        )
        require(json.loads(files["proposal-spec.json"]) == spec, "PAYLOAD_SPEC_CHANGED")
        require(
            files["readiness.json"] == files["source-before.json"],
            "READINESS_SOURCE_CHANGED",
        )
        require(
            json.loads(files["cargo-proof.json"])
            == cargo_guard(
                files["before/codex-rs/Cargo.lock"], files["after/codex-rs/Cargo.lock"]
            ),
            "CARGO_PROOF_NOT_REPRODUCIBLE",
        )
        require(
            json.loads(files["module-proof.json"])
            == module_guard(
                files["before/MODULE.bazel.lock"], files["after/MODULE.bazel.lock"]
            ),
            "MODULE_PROOF_NOT_REPRODUCIBLE",
        )
        require(
            json.loads(files["platform-proof.json"]) == platform_guard(files),
            "PLATFORM_PROOF_NOT_REPRODUCIBLE",
        )
    receipt = {
        "schema": "sha256-asm-proposal-upload-v1",
        "safe_for_upload": True,
        "proposal_validated": result["proposal_validated"],
        "files": {name: identity(raw) for name, raw in files.items()},
        "raw_logs_rewritten": False,
        "credential_fingerprints_recorded": False,
        "full_metadata_uploaded": False,
        "metadata_custody": "Native raw metadata retained only in private job storage and hashed; "
        "the artifact contains separately labelled graph projections. "
        "The complete raw metadata is compared before projection. "
        "Raw stderr, command statuses and both lock files retain the original scanner.",
    }
    manifest = (json.dumps(receipt, indent=2) + "\n").encode()
    scan(manifest)
    files["artifact-manifest.json"] = manifest
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
        == files.keys(),
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
            }
        )
    )


def read_checked(path):
    require(not path.is_symlink(), "SYMLINK_IN_PRIVATE_METADATA")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        before = os.fstat(stream.fileno())
        observe_command_stat(path, before)
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and before.st_size <= 64 * 1024 * 1024,
            "INVALID_PRIVATE_METADATA_FILE",
        )
        raw = stream.read(64 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
        require(
            before.st_size == len(raw) == after.st_size
            and before.st_mtime_ns == after.st_mtime_ns,
            "PRIVATE_METADATA_CHANGED_DURING_READ",
        )
    return raw


def metadata_projection(raw):
    value = json.loads(raw)
    dependency_keys = {
        "name",
        "source",
        "req",
        "kind",
        "rename",
        "optional",
        "uses_default_features",
        "features",
        "target",
        "registry",
        "path",
    }
    for package in value["packages"]:
        require(
            all(set(dep) <= dependency_keys for dep in package["dependencies"]),
            "UNKNOWN_DEPENDENCY_FIELD",
        )
    require(set(value["resolve"]) == {"nodes", "root"}, "UNKNOWN_RESOLVE_FIELD")
    require(
        all(
            set(node) == {"id", "dependencies", "deps", "features"}
            for node in value["resolve"]["nodes"]
        ),
        "UNKNOWN_RESOLVE_NODE_FIELD",
    )
    require(
        all(
            set(dep) == {"name", "pkg", "dep_kinds"}
            for node in value["resolve"]["nodes"]
            for dep in node["deps"]
        ),
        "UNKNOWN_RESOLVED_DEPENDENCY_FIELD",
    )
    require(
        all(
            set(kind) == {"kind", "target"}
            for node in value["resolve"]["nodes"]
            for dep in node["deps"]
            for kind in dep["dep_kinds"]
        ),
        "UNKNOWN_DEPENDENCY_KIND_FIELD",
    )
    return {
        "schema": "sha256-asm-metadata-graph-projection-v1",
        "raw_identity": identity(raw),
        "projection_is_lossless": False,
        "full_metadata_not_reconstructable_from_artifact": True,
        "metadata_format_version": value["version"],
        "workspace_members": value["workspace_members"],
        "workspace_default_members": value["workspace_default_members"],
        "packages": [
            {
                key: package[key]
                for key in ("id", "name", "version", "source", "dependencies")
            }
            for package in value["packages"]
        ],
        "resolve": value["resolve"],
    }
