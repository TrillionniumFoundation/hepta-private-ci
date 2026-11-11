"""Generate the finite process-observation overlay without changing stable SDK types."""

import ast
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from scripts._process_observation.source import load_evidence, require_hex, sha256

METHODS = {
    "process/exited": "ProcessExitedNotification",
    "process/indeterminate": "ProcessIndeterminateNotification",
    "process/outputDelta": "ProcessOutputDeltaNotification",
}


def _definition_name(reference: object) -> str:
    if not isinstance(reference, str) or not reference.startswith("#/definitions/"):
        raise ValueError("process overlay contains a non-local or unresolved reference")
    name = reference.removeprefix("#/definitions/")
    if re.fullmatch("[A-Za-z_][A-Za-z0-9_]*", name) is None:
        raise ValueError("unsupported process overlay definition reference")
    return name


def _references(value: Any) -> set[str]:
    if isinstance(value, dict):
        names = {_definition_name(value["$ref"])} if "$ref" in value else set()
        for key, child in value.items():
            if key != "$ref":
                names.update(_references(child))
        return names
    if isinstance(value, list):
        return set().union(*(_references(child) for child in value))
    return set()


def _closed_definitions(definitions: object, roots: set[str]) -> dict[str, Any]:
    if not isinstance(definitions, dict):
        raise ValueError("missing schema definitions")
    selected: dict[str, Any] = {}
    pending = sorted(roots)
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        definition = definitions.get(name)
        if not isinstance(definition, dict) or not definition:
            raise ValueError(f"unresolved or untyped definition: {name}")
        selected[name] = definition
        pending.extend(sorted(_references(definition) - selected.keys()))
    return dict(sorted(selected.items()))


def select_process_schema(server: dict[str, Any]) -> dict[str, Any]:
    """Select exactly the three methods and their complete local reference closure."""
    found: dict[str, str] = {}
    variants = server.get("oneOf")
    if not isinstance(variants, list):
        raise ValueError("missing server notification variants")
    for variant in variants:
        properties = variant.get("properties", {})
        method = properties.get("method", {}).get("enum")
        if not isinstance(method, list) or len(method) != 1 or method[0] not in METHODS:
            continue
        method_name = method[0]
        if method_name in found:
            raise ValueError(f"duplicate process notification: {method_name}")
        payload_name = _definition_name(properties.get("params", {}).get("$ref"))
        if payload_name != METHODS[method_name]:
            raise ValueError(f"process notification changed its payload: {method_name}")
        found[method_name] = payload_name
    if found != METHODS:
        raise ValueError("experimental schema does not contain all process notifications")
    definitions = _closed_definitions(server.get("definitions"), set(METHODS.values()))
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "ProcessObservation",
        "anyOf": [{"$ref": f"#/definitions/{name}"} for name in METHODS.values()],
        "definitions": definitions,
    }


def validate_generated_module(text: str) -> None:
    """Refuse incomplete generated classes or an untyped fallback."""
    tree = ast.parse(text)
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    if not set(METHODS.values()).issubset(classes):
        raise ValueError("generator did not emit all process payload classes")
    if any(isinstance(node, ast.Name) and node.id == "Any" for node in ast.walk(tree)):
        raise ValueError("process overlay generation produced an Any fallback")


def _validate_fixture(schema: dict[str, Any], provenance: dict[str, Any]) -> None:
    require_hex(provenance.get("source_commit"), 40, "source commit")
    require_hex(provenance.get("source_tree"), 40, "source tree")
    for key in (
        "experimental_archive_sha256",
        "server_notification_sha256",
        "source_receipt_sha256",
        "generated_manifest_sha256",
        "commands_receipt_sha256",
        "tool_versions_sha256",
        "schema_sha256",
    ):
        require_hex(provenance.get(key), 64, key)
    if provenance.get("format") != 1 or provenance.get("methods") != METHODS:
        raise ValueError("unsupported process-observation provenance")
    if schema.get("anyOf") != [{"$ref": f"#/definitions/{name}"} for name in METHODS.values()]:
        raise ValueError("process overlay roots changed")
    closed = _closed_definitions(schema.get("definitions"), set(METHODS.values()))
    if closed != schema["definitions"]:
        raise ValueError("process overlay contains definitions outside the method closure")


def normalize_process_schema(schema_dir: Path) -> str:
    """Select common normalization explicitly; stable Account compatibility is unrelated."""
    from scripts.update_sdk_artifacts import (
        _normalize_schema_titles_and_enums,
        schema_bundle_path,
    )

    schema = json.loads(schema_bundle_path(schema_dir).read_text())
    return _normalize_schema_titles_and_enums(schema)


def render_overlay(schema_bytes: bytes, provenance: dict[str, Any]) -> str:
    """Use the existing SDK generator's normalization and exact model-codegen flags."""
    from scripts.update_sdk_artifacts import (
        _normalize_generated_timestamps,
        generate_pydantic_module,
        run_python_module,
        schema_bundle_path,
        sdk_pyproject_path,
        sdk_root,
    )

    if provenance.get("schema_sha256") != sha256(schema_bytes):
        raise ValueError("process-observation schema changed since extraction")
    schema = json.loads(schema_bytes)
    _validate_fixture(schema, provenance)
    with tempfile.TemporaryDirectory(prefix="codex-process-observation-") as td:
        root = Path(td)
        schema_bundle_path(root).write_bytes(schema_bytes)
        output = root / "process_observation.py"
        generate_pydantic_module(root, output, normalize=normalize_process_schema)
        _normalize_generated_timestamps(output)
        # Temporary output lives outside the SDK tree, so explicitly retain its
        # owning Ruff configuration for the same two passes used by just fmt.
        for arguments in (
            ["check", "--fix", "--fix-only"],
            ["format"],
        ):
            run_python_module(
                "ruff",
                [*arguments, "--config", str(sdk_pyproject_path()), str(output)],
                cwd=sdk_root(),
            )
        generated = output.read_text()
    validate_generated_module(generated)
    header = (
        "# Process-observation overlay; generated from the reviewed experimental schema.\n"
        f"# Source commit: {provenance['source_commit']}\n"
        f"# Source tree: {provenance['source_tree']}\n"
        f"# Experimental archive SHA256: {provenance['experimental_archive_sha256']}\n"
        f"# Selected schema SHA256: {provenance['schema_sha256']}\n"
    )
    return header + generated


def generate_from_evidence(
    evidence: Path, source_commit: str, source_tree: str, archive_sha256: str
) -> None:
    """Produce the fixture and overlay only from a complete original CI artifact."""
    from scripts.update_sdk_artifacts import sdk_root

    server, provenance = load_evidence(evidence, source_commit, source_tree, archive_sha256)
    schema_bytes = (
        json.dumps(select_process_schema(server), indent=2, sort_keys=True) + "\n"
    ).encode()
    provenance.update(format=1, methods=METHODS, schema_sha256=sha256(schema_bytes))
    generated = render_overlay(schema_bytes, provenance)
    # Validation/code generation must finish before any maintained artifact is written.
    fixtures = sdk_root() / "tests" / "fixtures" / "process_observation"
    fixtures.mkdir(parents=True, exist_ok=True)
    (fixtures / "schema.json").write_bytes(schema_bytes)
    (fixtures / "source.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    (sdk_root() / "src" / "openai_codex" / "generated" / "process_observation.py").write_text(
        generated
    )
