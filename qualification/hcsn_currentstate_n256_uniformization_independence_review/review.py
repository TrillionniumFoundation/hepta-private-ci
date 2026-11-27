"""Review implementation lineage by exact source and AST, without numerics."""

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path


CANDIDATE_SHA256 = "0f686be417338f7aa102a8386171798b06a63689acdd043a69e95212655bf3f9"
ORACLE_SHA256 = "4213f078e36cd3e296e9301df2d1788c3b9375cf7a911c73c0090fe500f5ab73"
PROVIDER_SHA256 = "602dcedd5827a35fbee81b51687a8e8bc3f4038f519a308eef3e884d088e2be2"
PROVIDER_ALLOWED_IMPORT_ROOTS = {"hashlib", "json", "math", "dataclasses", "pathlib"}


class IndependenceReviewError(ValueError):
    """Raised before accepting a changed or coupled provider implementation."""


@dataclass(frozen=True)
class ImplementationIndependenceReview:
    candidate_source_sha256: str
    oracle_source_sha256: str
    provider_source_sha256: str
    candidate_algorithm_family: str
    oracle_algorithm_family: str
    provider_algorithm_family: str
    provider_standard_library_only: bool
    provider_imports_candidate: bool
    provider_imports_oracle: bool
    provider_calls_expm_multiply: bool
    candidate_imports_provider: bool
    oracle_imports_provider: bool
    exact_sources_distinct: bool
    implementation_independence_passed: bool
    external_reviewer_independence_certified: bool = False
    provider_admitted: bool = False
    numerical_calls: int = 0
    n256_provider_calls: int = 0
    tail_certificates_admitted: int = 0
    largegrid_qualification: bool = False


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _tree(raw, label):
    try:
        return ast.parse(raw.decode())
    except (UnicodeDecodeError, SyntaxError) as error:
        raise IndependenceReviewError(f"invalid {label} source") from error


def _imports(tree):
    values = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    values.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return values


def _call_names(tree):
    values = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            values.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            values.add(node.func.attr)
    return values


def _function_names(tree):
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports_lineage(imports, lineage):
    return any(lineage in value for value in imports)


def review_sources(candidate_path, oracle_path, provider_path):
    """Bind exact sources and prove only implementation-level separation."""

    candidate_raw = Path(candidate_path).read_bytes()
    oracle_raw = Path(oracle_path).read_bytes()
    provider_raw = Path(provider_path).read_bytes()
    actual = (_digest(candidate_raw), _digest(oracle_raw), _digest(provider_raw))
    expected = (CANDIDATE_SHA256, ORACLE_SHA256, PROVIDER_SHA256)
    if actual != expected:
        raise IndependenceReviewError("exact source SHA-256 mismatch")

    candidate = _tree(candidate_raw, "candidate")
    oracle = _tree(oracle_raw, "oracle")
    provider = _tree(provider_raw, "provider")
    candidate_imports = _imports(candidate)
    oracle_imports = _imports(oracle)
    provider_imports = _imports(provider)
    provider_roots = {value.split(".", 1)[0] for value in provider_imports}
    provider_calls = _call_names(provider)
    candidate_calls = _call_names(candidate)
    oracle_calls = _call_names(oracle)
    provider_functions = _function_names(provider)

    if not provider_roots <= PROVIDER_ALLOWED_IMPORT_ROOTS:
        raise IndependenceReviewError("provider imports a non-standard dependency")
    if _imports_lineage(provider_imports, "sparse_dynamic_intent"):
        raise IndependenceReviewError("provider imports candidate lineage")
    if _imports_lineage(provider_imports, "independent_oracle_intent"):
        raise IndependenceReviewError("provider imports oracle lineage")
    if "expm_multiply" in provider_calls:
        raise IndependenceReviewError("provider reuses expm_multiply")
    if not {"stable_poisson_window", "synthetic_uniformization_action"} <= provider_functions:
        raise IndependenceReviewError("provider uniformization primitives are absent")
    if "expm_multiply" not in candidate_calls or "expm_multiply" not in oracle_calls:
        raise IndependenceReviewError("bound Krylov lineage signature changed")
    candidate_imports_provider = _imports_lineage(
        candidate_imports, "uniformization_provider_intent"
    )
    oracle_imports_provider = _imports_lineage(
        oracle_imports, "uniformization_provider_intent"
    )
    if candidate_imports_provider or oracle_imports_provider:
        raise IndependenceReviewError("older lineage imports provider")

    return ImplementationIndependenceReview(
        candidate_source_sha256=actual[0],
        oracle_source_sha256=actual[1],
        provider_source_sha256=actual[2],
        candidate_algorithm_family="scipy_sparse_expm_multiply",
        oracle_algorithm_family="scipy_sparse_expm_multiply",
        provider_algorithm_family="stdlib_modal_poisson_uniformization",
        provider_standard_library_only=True,
        provider_imports_candidate=False,
        provider_imports_oracle=False,
        provider_calls_expm_multiply=False,
        candidate_imports_provider=candidate_imports_provider,
        oracle_imports_provider=oracle_imports_provider,
        exact_sources_distinct=len(set(actual)) == 3,
        implementation_independence_passed=len(set(actual)) == 3,
    )
