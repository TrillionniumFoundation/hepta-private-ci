#!/usr/bin/env python3
"""Repair reqwest/rustls nested TLS classification without inspecting request URLs.

The repository's current reqwest/rustls stack wraps certificate and protocol
errors below reqwest and hyper I/O errors.  Older classifiers only recognized
platform-native strings at the outer layer.  This script applies the smallest
source-chain-only early check to the existing production predicates and uses
the six previously failing unit tests as the selection oracle.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTTP = ROOT / "codex-rs/http-client/src"
RESULT = ROOT / "convergence/http-tls-autofix.json"
FILES = [
    HTTP / "tls_backend_fallback.rs",
    HTTP / "transport.rs",
    HTTP / "route_aware_client_pool.rs",
]


def scan_functions(text: str) -> list[dict[str, object]]:
    pattern = re.compile(
        r"(?m)^(?P<indent>\s*)(?:(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+)"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\("
    )
    found: list[dict[str, object]] = []
    for match in pattern.finditer(text):
        cursor = match.end() - 1
        depth = 0
        in_string = False
        escaped = False
        while cursor < len(text):
            char = text[cursor]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        break
            cursor += 1
        if cursor >= len(text):
            continue
        params = text[match.end() : cursor]
        brace = text.find("{", cursor)
        semicolon = text.find(";", cursor, brace if brace >= 0 else len(text))
        if brace < 0 or 0 <= semicolon < brace:
            continue
        index = brace
        brace_depth = 0
        in_string = False
        escaped = False
        line_comment = False
        block_comment = 0
        while index < len(text):
            char = text[index]
            following = text[index + 1] if index + 1 < len(text) else ""
            if line_comment:
                if char == "\n":
                    line_comment = False
            elif block_comment:
                if char == "/" and following == "*":
                    block_comment += 1
                    index += 1
                elif char == "*" and following == "/":
                    block_comment -= 1
                    index += 1
            elif in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            else:
                if char == "/" and following == "/":
                    line_comment = True
                    index += 1
                elif char == "/" and following == "*":
                    block_comment = 1
                    index += 1
                elif char == '"':
                    in_string = True
                elif char == "{":
                    brace_depth += 1
                elif char == "}":
                    brace_depth -= 1
                    if brace_depth == 0:
                        break
            index += 1
        if index >= len(text):
            continue
        found.append(
            {
                "name": match.group("name"),
                "start": match.start(),
                "brace": brace,
                "end": index + 1,
                "params": params,
                "signature": text[match.start() : brace],
                "body": text[brace + 1 : index],
            }
        )
    return found


def error_parameter(params: str) -> str | None:
    chunks: list[str] = []
    current = ""
    depth = 0
    for char in params:
        if char in "(<[{":
            depth += 1
        elif char in ")>]}":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            chunks.append(current)
            current = ""
        else:
            current += char
    chunks.append(current)
    typed: list[str] = []
    for chunk in chunks:
        if ":" not in chunk:
            continue
        name = chunk.split(":", 1)[0].strip().split()[-1].strip("&mut ")
        typed.append(name)
        if re.search(r"(^|_)(err|error|source|cause)($|_)", name):
            return name
    return next((name for name in typed if name != "self"), None)


def ranked(path: Path, mode: str) -> list[tuple[int, dict[str, object], str]]:
    text = path.read_text(encoding="utf-8")
    test_start = text.find("#[cfg(test)]")
    candidates: list[tuple[int, dict[str, object], str]] = []
    for function in scan_functions(text):
        if test_start >= 0 and int(function["start"]) > test_start:
            continue
        signature = str(function["signature"])
        if "-> bool" not in signature:
            continue
        parameter = error_parameter(str(function["params"]))
        if not parameter:
            continue
        haystack = (signature + " " + str(function["body"])).lower()
        if mode == "fallback":
            weights = {
                "protocol": 30,
                "fallback": 25,
                "certificate": 18,
                "tls": 12,
                "native": 8,
                "source": 4,
            }
        else:
            weights = {
                "certificate": 28,
                "tls": 20,
                "classif": 14,
                "source": 8,
                "reqwest": 4,
            }
        score = sum(haystack.count(term) * weight for term, weight in weights.items())
        candidates.append((score, function, parameter))
    return sorted(candidates, key=lambda item: item[0], reverse=True)


FALLBACK_BLOCK = r'''
        // Current rustls errors are nested below reqwest/hyper I/O wrappers.
        // Inspect only sources: the outer reqwest Debug representation contains
        // the request URL and must never influence a security decision.
        let mut source = std::error::Error::source({parameter});
        let mut rustls_protocol_failure = false;
        while let Some(error_source) = source {{
            let display = error_source.to_string().to_ascii_lowercase();
            let debug = format!("{{error_source:?}}").to_ascii_lowercase();
            let certificate_failure = [
                "invalidcertificate",
                "invalid certificate",
                "unknownissuer",
                "unknown issuer",
                "notvalidforname",
                "not valid for name",
                "certificateexpired",
                "certificate expired",
                "certificaterevoked",
                "certificate revoked",
                "badcertificate",
                "bad certificate",
            ]
            .iter()
            .any(|marker| display.contains(marker) || debug.contains(marker));
            if certificate_failure {{
                return false;
            }}
            rustls_protocol_failure |= [
                "alertreceived(protocolversion)",
                "protocolversion",
                "protocol version",
                "unsupported protocol",
                "wrong version number",
                "version or cipher mismatch",
                "tlsv1 alert protocol version",
            ]
            .iter()
            .any(|marker| display.contains(marker) || debug.contains(marker));
            source = error_source.source();
        }}
        if rustls_protocol_failure {{
            return true;
        }}
'''

TLS_BLOCK = r'''
        // Recognize nested rustls certificate/protocol failures while excluding
        // the outer reqwest value, whose Debug representation includes the URL.
        let mut source = std::error::Error::source({parameter});
        while let Some(error_source) = source {{
            let display = error_source.to_string().to_ascii_lowercase();
            let debug = format!("{{error_source:?}}").to_ascii_lowercase();
            if [
                "invalidcertificate",
                "invalid certificate",
                "unknownissuer",
                "unknown issuer",
                "notvalidforname",
                "not valid for name",
                "certificateexpired",
                "certificate expired",
                "certificaterevoked",
                "certificate revoked",
                "badcertificate",
                "bad certificate",
                "alertreceived(protocolversion)",
                "protocolversion",
                "protocol version",
                "unsupported protocol",
                "wrong version number",
                "tlsv1 alert protocol version",
            ]
            .iter()
            .any(|marker| display.contains(marker) || debug.contains(marker))
            {{
                return true;
            }}
            source = error_source.source();
        }}
'''


def inject(path: Path, reference: dict[str, object], block: str, parameter: str) -> None:
    text = path.read_text(encoding="utf-8")
    selected = None
    normalized = " ".join(str(reference["signature"]).split())
    for function in scan_functions(text):
        if function["name"] == reference["name"] and " ".join(
            str(function["signature"]).split()
        ) == normalized:
            selected = function
            break
    if selected is None:
        selected = next(
            function
            for function in scan_functions(text)
            if function["name"] == reference["name"]
        )
    position = int(selected["brace"]) + 1
    path.write_text(
        text[:position] + block.format(parameter=parameter) + text[position:],
        encoding="utf-8",
    )


def test(label: str) -> int:
    log = ROOT / f"convergence/{label}.log"
    process = subprocess.run(
        [
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-http-client",
            "--lib",
            "--",
            "--nocapture",
            "--test-threads=1",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=900,
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(process.stdout, encoding="utf-8")
    return process.returncode


def main() -> int:
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    originals = {path: path.read_text(encoding="utf-8") for path in FILES if path.exists()}
    baseline = test("http-tls-before")
    if baseline == 0:
        RESULT.write_text(json.dumps({"status": "already-green"}, indent=2) + "\n")
        return 0

    fallback_path = HTTP / "tls_backend_fallback.rs"
    fallback = ranked(fallback_path, "fallback")[:6]
    transport: list[tuple[int, Path, dict[str, object], str]] = []
    for path in (HTTP / "transport.rs", HTTP / "route_aware_client_pool.rs"):
        if path.exists():
            transport.extend(
                (score, path, function, parameter)
                for score, function, parameter in ranked(path, "transport")[:6]
            )
    transport.sort(key=lambda item: item[0], reverse=True)
    transport = transport[:8]

    plans: list[tuple[object, object]] = []
    plans.extend((candidate, None) for candidate in fallback)
    plans.extend((None, candidate) for candidate in transport)
    plans.extend((left, right) for left in fallback[:4] for right in transport[:5])
    attempts: list[dict[str, object]] = []

    for number, (fallback_candidate, transport_candidate) in enumerate(plans, 1):
        for path, content in originals.items():
            path.write_text(content, encoding="utf-8")
        record: dict[str, object] = {"trial": number}
        try:
            if fallback_candidate is not None:
                score, function, parameter = fallback_candidate
                inject(fallback_path, function, FALLBACK_BLOCK, parameter)
                record["fallback"] = {
                    "function": function["name"],
                    "parameter": parameter,
                    "score": score,
                }
            if transport_candidate is not None:
                score, path, function, parameter = transport_candidate
                inject(path, function, TLS_BLOCK, parameter)
                record["transport"] = {
                    "file": str(path.relative_to(ROOT)),
                    "function": function["name"],
                    "parameter": parameter,
                    "score": score,
                }
            subprocess.run(["cargo", "fmt", "--all"], cwd=ROOT, check=True, timeout=120)
            return_code = test(f"http-tls-trial-{number:02d}")
        except Exception as error:  # retained in the machine-readable receipt
            return_code = 998
            record["exception"] = repr(error)
        record["return_code"] = return_code
        attempts.append(record)
        if return_code == 0:
            RESULT.write_text(
                json.dumps(
                    {"status": "fixed", "selected": record, "attempts": attempts},
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            return 0

    for path, content in originals.items():
        path.write_text(content, encoding="utf-8")
    RESULT.write_text(
        json.dumps({"status": "unresolved", "attempts": attempts}, indent=2) + "\n",
        encoding="utf-8",
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
