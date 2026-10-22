"""Conservative source classification for the Lane E writer inventory.

This is a bounded lexical check, not Rust compilation or general data flow.
Only standalone, disabled qualification function items and simple read arms
are exempt. Unknown conditions, imports and write-shaped uses remain visible.
"""

from pathlib import Path
import re
import tomllib


QUALIFICATION_FEATURE = "qualification-legacy-learning-write"
LEGACY_VARIANTS = "Decision|Outcome|Credit|Revocation"


def rust_code(text: str) -> str:
    """Mask comments and literals, retaining offsets and structural tokens."""
    output = list(text)
    index = 0
    while index < len(text):
        end = None
        if text.startswith("//", index):
            end = text.find("\n", index)
            if end < 0:
                end = len(text)
        elif text.startswith("/*", index):
            end, depth = index + 2, 1
            while end < len(text) and depth:
                if text.startswith("/*", end):
                    depth += 1
                    end += 2
                elif text.startswith("*/", end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
            if depth:
                raise ValueError("unterminated Rust comment")
        else:
            raw = re.match(r'(?:br|cr|r)(#{0,255})"', text[index:])
            if raw:
                close = text.find('"' + raw.group(1), index + raw.end())
                if close < 0:
                    raise ValueError("unterminated Rust raw literal")
                end = close + 1 + len(raw.group(1))
            elif text[index] == '"':
                end = index + 1
                while end < len(text):
                    if text[end] == "\\":
                        end += 2
                    elif text[end] == '"':
                        end += 1
                        break
                    else:
                        end += 1
                else:
                    raise ValueError("unterminated Rust string")
            elif text[index] == "'":
                char = re.match(
                    r"'(?:\\(?:u\{[0-9A-Fa-f_]+\}|x[0-9A-Fa-f]{2}|.)|[^'\\\n])'",
                    text[index:],
                )
                if char:
                    end = index + char.end()
        if end is None:
            index += 1
        else:
            output[index:end] = [
                "\n" if value == "\n" else " " for value in text[index:end]
            ]
            index = end
    return "".join(output)


def _dependencies(table):
    for name, value in table.items():
        if name == "dev-dependencies":
            continue
        if name in {"dependencies", "build-dependencies"}:
            yield from value.items()
        elif isinstance(value, dict):
            yield from _dependencies(value)


def _expanded_features(manifest, requested):
    features = manifest.get("features", {})
    pending = list(requested)
    enabled = set()
    while pending:
        name = pending.pop()
        if name not in enabled:
            enabled.add(name)
            pending.extend(features.get(name, []))
    return enabled


def qualification_is_disabled(root: Path, manifest_path: Path) -> bool:
    """Prove the exact qualification switch is absent from normal Cargo use.

    A new explicit Bazel enablement requires review rather than an automatic
    exemption. Dev-dependency fixtures do not enable a normal product build.
    """
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    if QUALIFICATION_FEATURE not in manifest.get("features", {}):
        return False
    if QUALIFICATION_FEATURE in _expanded_features(manifest, ["default"]):
        return False
    package = manifest["package"]["name"]
    consumers = [
        tomllib.loads(path.read_text(encoding="utf-8"))
        for path in (root / "codex-rs").rglob("Cargo.toml")
    ]
    workspace_dependencies = {
        alias: spec
        for consumer in consumers
        for alias, spec in consumer.get("workspace", {}).get("dependencies", {}).items()
    }
    for consumer in consumers:
        defaults = _expanded_features(consumer, ["default"])
        for alias, spec in _dependencies(consumer):
            if not isinstance(spec, dict):
                continue
            inherited = (
                workspace_dependencies.get(alias, {}) if spec.get("workspace") else {}
            )
            if not isinstance(inherited, dict):
                inherited = {}
            if spec.get("package", inherited.get("package", alias)) != package:
                continue
            requested = set(spec.get("features", [])) | set(
                inherited.get("features", [])
            )
            requested.update(
                value.split("/", 1)[1]
                for value in defaults
                if value.startswith((f"{alias}/", f"{alias}?/"))
            )
            if QUALIFICATION_FEATURE in _expanded_features(manifest, requested):
                return False
    for pattern in ("BUILD.bazel", "*.bzl"):
        for path in root.rglob(pattern):
            if QUALIFICATION_FEATURE in path.read_text(encoding="utf-8"):
                return False
    return True


def _closing(code: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    for index in range(start, len(code)):
        if code[index] == opening:
            depth += 1
        elif code[index] == closing:
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError("unbalanced qualification item")


def _outside_macros(code: str, positions: set[int]) -> set[int]:
    # Macro input need not retain the syntax or meaning of its input tokens.
    stack = []
    outside = set()
    for index, value in enumerate(code):
        if index in positions and not any(stack):
            outside.add(index)
        if value in "({[":
            stack.append(
                bool(re.search(r"(?:\w+\s*!|macro_rules!\s+\w+)\s*$", code[:index]))
            )
        elif value in ")}]" and stack:
            stack.pop()
    return outside


def product_source(text: str, qualification_disabled: bool) -> str:
    code = rust_code(text)
    if not qualification_disabled:
        return code
    output = list(code)
    attribute = re.compile(
        r'#\s*\[\s*cfg\s*\(\s*feature\s*=\s*"' + QUALIFICATION_FEATURE + r'"\s*\)\s*\]'
    )
    matches = list(attribute.finditer(text))
    outside = _outside_macros(code, {match.start() for match in matches})
    for match in matches:
        if code[match.start()] != "#" or match.start() not in outside:
            continue
        cursor = match.end()
        while True:
            cursor += len(code[cursor:]) - len(code[cursor:].lstrip())
            if not code.startswith("#[", cursor):
                break
            cursor = _closing(code, cursor + 1, "[", "]")
        declaration = re.match(
            r"(?:pub(?:\([^)]*\))?\s+)?(?:async\s+|unsafe\s+|const\s+)*fn\s+\w+\s*\(",
            code[cursor:],
        )
        if declaration is None:
            continue
        body = code.find("{", cursor + declaration.end())
        if body < 0 or ";" in code[cursor:body]:
            continue
        end = _closing(code, body, "{", "}")
        output[match.start() : end] = [
            "\n" if value == "\n" else " " for value in code[match.start() : end]
        ]
    return "".join(output)


def writer_uses(code: str) -> set[str]:
    """Return suspicious write uses; simple field-reading match arms are reads."""
    aliases = {"LedgerEvent"}
    aliases.update(re.findall(r"\bLedgerEvent\s+as\s+(\w+)", code))
    aliases.update(
        re.findall(r"\btype\s+(\w+)\s*=\s*(?:\w+\s*::\s*)*LedgerEvent\s*;", code)
    )
    event = "(?:" + "|".join(map(re.escape, sorted(aliases))) + ")"
    findings = set()
    if re.search(rf"\b{event}\s*::\s*[{{*]", code):
        findings.add("raw event grouped/wildcard import")
    if re.search(r"(?:\.|::)\s*append_qualification\b", code):
        findings.add("legacy qualification append outside disabled qualification item")
    if "DurableLearningJournal" in code:
        journals = {"DurableLearningJournal"}
        journals.update(re.findall(r"\bDurableLearningJournal\s+as\s+(\w+)", code))
        journal = "(?:" + "|".join(map(re.escape, sorted(journals))) + ")"
        if re.search(r"\.\s*append_decision\b", code) or re.search(
            rf"\b{journal}\s*>?\s*::\s*append_decision\b", code
        ):
            findings.add("legacy journal decision write")
    read_arm = re.compile(
        rf"\b{event}\s*::\s*({LEGACY_VARIANTS})\s*\(\s*(\w+)\s*\)"
        r"\s*=>\s*&\s*\2\s*\.\s*record_id\s*,"
    )
    reads = {match.start(): match for match in read_arm.finditer(code)}
    masked = list(code)
    for start in _outside_macros(code, set(reads)):
        match = reads[start]
        masked[start : match.end()] = " " * (match.end() - start)
    code = "".join(masked)
    for variant in re.findall(rf"\b{event}\s*::\s*({LEGACY_VARIANTS})\b", code):
        findings.add(f"raw V1 {variant} append")
    return findings
