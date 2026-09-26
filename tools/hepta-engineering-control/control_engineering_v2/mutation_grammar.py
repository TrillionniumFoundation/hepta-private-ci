"""Canonical control.engineering-owned MutationGrammarManifestV1 production.

The manifest is a bounded, authority-denying description of candidate mutation
classes. It is not a capability and cannot grant merge, activation, promotion,
release, runtime, provider, tool, network, filesystem or external-effect authority.
`learning.plasticity` consumes only the resulting non-zero semantic digest through
its typed parameter projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .control_plane import (
    EngineeringError,
    bounded_tuple,
    checked_id,
    semantic_digest as canonical_semantic_digest,
)

MAX_PROTECTED_PATH_GLOBS = 256
MAX_MANDATORY_CHECKS = 128
MAX_GLOB_BYTES = 1024
MAX_CHECK_BYTES = 256
MAX_FILES = 100
MAX_TEXT_BYTES = 1024 * 1024
MAX_CANDIDATES = 32

PROTOCOL_ALLOWED_OPERATIONS = frozenset(
    {
        "bounded_delta",
        "replace_with_predecessor_compatible_artifact",
        "add_factor",
        "revise_realization",
        "retire_factor",
        "add_step",
        "revise_bounded_step",
        "retire_step",
        "add",
        "revise_precondition",
        "revise_effect_model",
        "retire",
        "add_file",
        "edit_ast_node",
        "delete_owned_file",
        "dependency_update",
        "split",
        "merge",
        "rewire",
    }
)

PROTOCOL_AUTHORITY_DENY_LIST = (
    "runtimeAuthority",
    "productionCaller",
    "productionWriter",
    "modelInvocation",
    "providerDispatch",
    "toolExecution",
    "networkConnect",
    "externalFilesystemMutation",
    "secretOperation",
    "matrixSend",
    "externalEffect",
    "fleetMutation",
    "canonicalSelection",
    "merge",
    "operatorAcceptance",
    "promotion",
    "release",
)


def _fail(code: str) -> None:
    raise EngineeringError(code)


def _bounded_unique_strings(
    values: Iterable[str],
    *,
    limit: int,
    maximum_bytes: int,
    code: str,
) -> tuple[str, ...]:
    materialized = bounded_tuple(values, limit, code)
    normalized: list[str] = []
    for value in materialized:
        if (
            not isinstance(value, str)
            or not value
            or "\x00" in value
            or len(value.encode("utf-8")) > maximum_bytes
        ):
            _fail(code)
        normalized.append(value)
    result = tuple(sorted(normalized))
    if len(result) != len(set(result)):
        _fail(code)
    return result


@dataclass(frozen=True)
class MutationGrammarManifestV1:
    grammar_id: str
    version: int
    allowed_operations: tuple[str, ...]
    protected_path_globs: tuple[str, ...]
    maximum_files: int
    maximum_text_bytes: int
    maximum_candidates: int
    authority_deny_list: tuple[str, ...]
    mandatory_checks: tuple[str, ...]
    semantic_digest: str

    def semantic_payload(self) -> dict[str, Any]:
        """Return the exact canonical payload covered by `semanticDigest`."""
        return {
            "allowedOperations": list(self.allowed_operations),
            "authorityDenyList": list(self.authority_deny_list),
            "grammarId": self.grammar_id,
            "mandatoryChecks": list(self.mandatory_checks),
            "maximumCandidates": self.maximum_candidates,
            "maximumFiles": self.maximum_files,
            "maximumTextBytes": self.maximum_text_bytes,
            "protectedPathGlobs": list(self.protected_path_globs),
            "version": self.version,
        }

    def protocol_payload(self) -> dict[str, Any]:
        payload = self.semantic_payload()
        payload["semanticDigest"] = self.semantic_digest
        return payload

    def verify(self) -> None:
        rebuilt = build_mutation_grammar_manifest_v1(
            grammar_id=self.grammar_id,
            version=self.version,
            allowed_operations=self.allowed_operations,
            protected_path_globs=self.protected_path_globs,
            maximum_files=self.maximum_files,
            maximum_text_bytes=self.maximum_text_bytes,
            maximum_candidates=self.maximum_candidates,
            mandatory_checks=self.mandatory_checks,
        )
        if rebuilt != self:
            _fail("mutation_grammar_digest_mismatch")


def build_mutation_grammar_manifest_v1(
    *,
    grammar_id: str,
    version: int,
    allowed_operations: Iterable[str],
    protected_path_globs: Iterable[str],
    maximum_files: int,
    maximum_text_bytes: int,
    maximum_candidates: int,
    mandatory_checks: Iterable[str],
) -> MutationGrammarManifestV1:
    grammar_id = checked_id(grammar_id, "mutation_grammar_id")
    if type(version) is not int or version <= 0 or version > 0xFFFF_FFFF:
        _fail("invalid_mutation_grammar_version")
    operations = _bounded_unique_strings(
        allowed_operations,
        limit=len(PROTOCOL_ALLOWED_OPERATIONS),
        maximum_bytes=64,
        code="invalid_mutation_operations",
    )
    if not operations or not set(operations).issubset(PROTOCOL_ALLOWED_OPERATIONS):
        _fail("invalid_mutation_operations")
    protected = _bounded_unique_strings(
        protected_path_globs,
        limit=MAX_PROTECTED_PATH_GLOBS,
        maximum_bytes=MAX_GLOB_BYTES,
        code="invalid_mutation_protected_paths",
    )
    if not protected:
        _fail("invalid_mutation_protected_paths")
    checks = _bounded_unique_strings(
        mandatory_checks,
        limit=MAX_MANDATORY_CHECKS,
        maximum_bytes=MAX_CHECK_BYTES,
        code="invalid_mutation_checks",
    )
    if not checks:
        _fail("invalid_mutation_checks")
    if type(maximum_files) is not int or not 1 <= maximum_files <= MAX_FILES:
        _fail("invalid_mutation_file_budget")
    if (
        type(maximum_text_bytes) is not int
        or not 1 <= maximum_text_bytes <= MAX_TEXT_BYTES
    ):
        _fail("invalid_mutation_text_budget")
    if (
        type(maximum_candidates) is not int
        or not 1 <= maximum_candidates <= MAX_CANDIDATES
    ):
        _fail("invalid_mutation_candidate_budget")

    payload: dict[str, Any] = {
        "allowedOperations": list(operations),
        "authorityDenyList": list(PROTOCOL_AUTHORITY_DENY_LIST),
        "grammarId": grammar_id,
        "mandatoryChecks": list(checks),
        "maximumCandidates": maximum_candidates,
        "maximumFiles": maximum_files,
        "maximumTextBytes": maximum_text_bytes,
        "protectedPathGlobs": list(protected),
        "version": version,
    }
    return MutationGrammarManifestV1(
        grammar_id=grammar_id,
        version=version,
        allowed_operations=operations,
        protected_path_globs=protected,
        maximum_files=maximum_files,
        maximum_text_bytes=maximum_text_bytes,
        maximum_candidates=maximum_candidates,
        authority_deny_list=PROTOCOL_AUTHORITY_DENY_LIST,
        mandatory_checks=checks,
        semantic_digest=canonical_semantic_digest(payload),
    )


def plasticity_projection_grammar_digest_v1(
    manifest: MutationGrammarManifestV1,
) -> str:
    """Return the sole grammar identity accepted by a plasticity projection."""
    manifest.verify()
    return manifest.semantic_digest
