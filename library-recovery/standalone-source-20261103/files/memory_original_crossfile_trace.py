#!/usr/bin/env python3
"""Source-byte-bound, model-free cross-file dependency trace on original Git files.

Static AST (Python) and conservative literal-import (Rust) proofs only: no
execution of downloaded project code, no pretrained Reader calls, no semantic
sufficiency or production admission. An original test-to-implementation link is
not an independently human reviewed real task or verified executable repair.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from real_source_reader_probe import (
    SOURCE_CUT,
    SOURCE_SHA,
    REOPEN_SHA,
    digest,
    real_source,
    require,
    write_once,
)

PROFILE = "hepta.memory.original-crossfile-dependency.v1"
# These declared source links were selected before scoring. All source bytes
# are from the immutable 2026-10-12 six-repository public source archive.
# Study labels are static *mechanical* facts, never generated-model results.
# id, repository, caller path, caller scope, referenced symbol, definition path,
# language and qualified class (for Python constructor-alias links).
CASES = (
    (
        'py-http-01',
        'python/cpython',
        'Lib/test/test_httplib.py',
        'HeaderTests.test_auto_headers',
        'request',
        'Lib/http/client.py',
        'py-method',
        'HTTPConnection',
    ),
    (
        'py-http-02',
        'python/cpython',
        'Lib/test/test_httplib.py',
        'HeaderTests.test_putheader',
        'putheader',
        'Lib/http/client.py',
        'py-method',
        'HTTPConnection',
    ),
    (
        'py-http-03',
        'python/cpython',
        'Lib/test/test_httplib.py',
        'BasicTest.test_send',
        'send',
        'Lib/http/client.py',
        'py-method',
        'HTTPConnection',
    ),
    (
        'sk-base-01',
        'scikit-learn/scikit-learn',
        'sklearn/linear_model/tests/test_base.py',
        'test_preprocess_data',
        '_preprocess_data',
        'sklearn/linear_model/_base.py',
        'py-import',
        '',
    ),
    (
        'sk-base-02',
        'scikit-learn/scikit-learn',
        'sklearn/linear_model/tests/test_base.py',
        'test_rescale_data',
        '_rescale_data',
        'sklearn/linear_model/_base.py',
        'py-import',
        '',
    ),
    (
        'sk-log-01',
        'scikit-learn/scikit-learn',
        'sklearn/linear_model/tests/test_logistic.py',
        'test_logistic_regression_path_convergence_fail',
        '_logistic_regression_path',
        'sklearn/linear_model/_logistic.py',
        'py-import',
        '',
    ),
    (
        'sk-log-02',
        'scikit-learn/scikit-learn',
        'sklearn/linear_model/tests/test_logistic.py',
        'test_logistic_cv_multinomial_score',
        '_log_reg_scoring_path',
        'sklearn/linear_model/_logistic.py',
        'py-import',
        '',
    ),
    (
        'sk-api-01',
        'scikit-learn/scikit-learn',
        'sklearn/utils/tests/test_array_api.py',
        'test_asarray_with_order',
        '_asarray_with_order',
        'sklearn/utils/_array_api.py',
        'py-import',
        '',
    ),
    (
        'sk-api-02',
        'scikit-learn/scikit-learn',
        'sklearn/utils/tests/test_array_api.py',
        'test_convert_to_numpy_cpu',
        '_convert_to_numpy',
        'sklearn/utils/_array_api.py',
        'py-import',
        '',
    ),
    (
        'deno-01',
        'denoland/deno',
        'libs/cache_dir/global/mod.rs',
        'local_path_for_url',
        'url_to_filename',
        'libs/cache_dir/cache.rs',
        'rs-fn',
        '',
    ),
    (
        'deno-02',
        'denoland/deno',
        'libs/cache_dir/file_fetcher/mod.rs',
        'literal-line-730',
        'NOT_FOUND_CACHE_HEADER',
        'libs/cache_dir/cache.rs',
        'rs-const',
        '',
    ),
    (
        'deno-03',
        'denoland/deno',
        'libs/cache_dir/global/mod.rs',
        'literal-line-171',
        'CacheReadFileError',
        'libs/cache_dir/cache.rs',
        'rs-enum',
        '',
    ),
)

EXPECTED_ROOTS = {"python/cpython": 3, "scikit-learn/scikit-learn": 6, "denoland/deno": 3}


def _hash_line(value: str) -> str:
    return digest(value.encode("utf-8"))


def _scope(tree: ast.Module, qualified: str):
    chunks = qualified.split(".")
    body = tree.body
    node = None
    for chunk in chunks:
        node = next((v for v in body if isinstance(v, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and v.name == chunk), None)
        require(node is not None, "original caller scope absent")
        body = node.body
    require(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)), "original caller is not executable function")
    return node


def _python_trace(spec, caller: str, definition: str):
    _, repo, cp, scope, symbol, dp, kind, owner = spec
    try:
        a = ast.parse(caller)
        b = ast.parse(definition)
    except (SyntaxError, ValueError) as exc:
        raise ValueError("original Python AST failed to parse") from exc
    target = _scope(a, scope)
    if kind == "py-import":
        module = dp.removesuffix(".py").replace("/", ".")
        # An explicit *module-level* import, not an ambiguous same-name
        # substring anywhere in the test corpus, establishes the reference.
        matches = [n for n in a.body if isinstance(n, ast.ImportFrom) and n.module == module
                   for alias in n.names if (alias.asname or alias.name) == symbol and alias.name == symbol]
        imported = [n for n in b.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == symbol]
        calls = [n for n in ast.walk(target) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == symbol]
        # Assignment to the imported function inside the selected caller would
        # break the nominal from-import call edge, even if its name still fits.
        rebound = any(isinstance(n, ast.Name) and n.id == symbol
                      and isinstance(n.ctx, ast.Store) for n in ast.walk(target))
        require(len(matches) == 1 and len(imported) == 1 and calls and not rebound,
                "original import/call/implementation chain missing or locally shadowed")
        imp_line, def_line = matches[0].lineno, imported[0].lineno
    else:
        require(repo == "python/cpython" and owner == "HTTPConnection" and dp == "Lib/http/client.py",
                "unknown Python module alias contract")
        matches = [n for n in a.body if isinstance(n, ast.ImportFrom) and n.module == "http"
                   for alias in n.names if alias.name == "client" and alias.asname is None]
        clazz = [n for n in b.body if isinstance(n, ast.ClassDef) and n.name == owner]
        require(len(matches) == len(clazz) == 1, "original class import/definition missing")
        method = [n for n in clazz[0].body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == symbol]
        require(len(method) == 1, "original owner method missing")
        # Proof only for an original alias declared by the constructor in the
        # same test scope. This is NOT general Python data-flow analysis.
        aliases = {n.targets[0].id for n in ast.walk(target) if isinstance(n, ast.Assign)
                   and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                   and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                   and isinstance(n.value.func.value, ast.Name)
                   and n.value.func.value.id == "client" and n.value.func.attr == owner}
        calls = [n for n in ast.walk(target) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                 and n.func.value.id in aliases and n.func.attr == symbol]
        constructor_stores = sum(1 for n in ast.walk(target) if isinstance(n, ast.Assign)
                                 and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                                 and n.targets[0].id in aliases and isinstance(n.value, ast.Call)
                                 and isinstance(n.value.func, ast.Attribute)
                                 and isinstance(n.value.func.value, ast.Name)
                                 and n.value.func.value.id == "client"
                                 and n.value.func.attr == owner)
        all_alias_stores = sum(1 for n in ast.walk(target) if isinstance(n, ast.Name)
                               and n.id in aliases and isinstance(n.ctx, ast.Store))
        require(aliases and calls and constructor_stores == all_alias_stores,
                "original constructor-alias/method-call chain missing or rebound")
        imp_line, def_line = matches[0].lineno, method[0].lineno
    call_line = min(n.lineno for n in calls)
    lines_a, lines_b = caller.splitlines(), definition.splitlines()
    require(1 <= imp_line <= len(lines_a) and 1 <= call_line <= len(lines_a)
            and 1 <= def_line <= len(lines_b), "original Python source span out of range")
    return dict(import_line=imp_line, call_line=call_line, definition_line=def_line,
                call_site_sha256=_hash_line(lines_a[call_line - 1]),
                import_site_sha256=_hash_line(lines_a[imp_line - 1]),
                definition_site_sha256=_hash_line(lines_b[def_line - 1]),
                syntax_profile=kind, executable_project_test_ran=False)


def _rust_trace(spec, caller: str, definition: str):
    _, _, cp, scope, symbol, dp, kind, _ = spec
    require(dp == "libs/cache_dir/cache.rs" and cp.startswith("libs/cache_dir/"),
            "unregistered Rust cross-module mapping")
    a, b = caller.splitlines(), definition.splitlines()
    import_pattern = re.compile(r"^\s*use\s+crate::cache::" + re.escape(symbol) + r"\s*;\s*$")
    imports = [i for i, row in enumerate(a, 1) if import_pattern.fullmatch(row)]
    if kind == "rs-fn":
        declaration = re.compile(r"^\s*pub\s+fn\s+" + re.escape(symbol) + r"\s*\(")
    elif kind == "rs-const":
        declaration = re.compile(r"^\s*pub\s+const\s+" + re.escape(symbol) + r"\s*:")
    elif kind == "rs-enum":
        declaration = re.compile(r"^\s*pub\s+enum\s+" + re.escape(symbol) + r"\b")
    else:
        raise ValueError("unregistered Rust syntax edge")
    declarations = [i for i, row in enumerate(b, 1) if declaration.search(row)]
    if scope.startswith("literal-line-"):
        call_line = int(scope.removeprefix("literal-line-"))
        require(call_line > 0 and call_line <= len(a), "original literal call line not present")
        uses = [call_line] if re.search(r"\b" + re.escape(symbol) + r"\b", a[call_line - 1]) else []
    else:
        method = re.compile(r"^\s*(?:pub\s+)?fn\s+" + re.escape(scope) + r"\s*\(")
        start = next((i for i, row in enumerate(a, 1) if method.search(row)), None)
        require(start is not None, "original Rust caller function missing")
        # Restrict this conservative Rust audit to the first method body up to
        # the next same-indentation definition; no claim of a full Rust parser.
        boundary = next((i for i in range(start + 1, len(a) + 1) if re.match(r"^\s{2}(?:pub\s+)?fn\s+", a[i - 1])), len(a) + 1)
        uses = [i for i in range(start, boundary)
                if re.search(r"\b" + re.escape(symbol) + r"\b", a[i - 1])]
        require(uses, "original Rust caller lost imported reference")
        call_line = uses[0]
    require(len(imports) == 1 and len(declarations) == 1 and uses,
            "original Rust import/definition/reference incomplete")
    return dict(import_line=imports[0], call_line=call_line, definition_line=declarations[0],
                call_site_sha256=_hash_line(a[call_line - 1]),
                import_site_sha256=_hash_line(a[imports[0] - 1]),
                definition_site_sha256=_hash_line(b[declarations[0] - 1]),
                syntax_profile=kind, executable_project_test_ran=False)


def audit(sources: tuple) -> dict:
    files, blobs = sources
    require(len(files) == 32 and len(blobs) == 32 and len(set(blobs)) == 32,
            "exact original Git source census required")
    by_key = {}
    for row in files:
        key = (row["repo"], row["path"])
        require(key not in by_key and key in blobs and row["partition"] in
                ("train", "selection", "evaluation"), "original Git identity mismatch")
        raw = blobs[key]
        require(digest(raw) == row["sha256"] and len(raw) == row["bytes"] and
                hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == row["blob_sha"],
                "original Git file differs from inventory")
        by_key[key] = row
    rows = []
    roots = Counter()
    for spec in CASES:
        case_id, repo, cp, scope, symbol, dp, syntax, owner = spec
        require((repo, cp) in by_key and (repo, dp) in by_key and cp != dp and
                by_key[repo, cp]["partition"] == by_key[repo, dp]["partition"] == "evaluation",
                "cross-partition or missing original source")
        require(syntax in ("py-import", "py-method", "rs-fn", "rs-const", "rs-enum"),
                "unsupported static linkage type")
        try:
            caller, definition = [blobs[repo, p].decode("utf-8", "strict") for p in (cp, dp)]
        except UnicodeDecodeError as exc:
            raise ValueError("unrecognized non-UTF8 static source") from exc
        proof = (_python_trace(spec, caller, definition) if syntax.startswith("py-")
                 else _rust_trace(spec, caller, definition))
        roots[repo] += 1
        rows.append(dict(id=case_id, repository_proxy=repo, caller_file=cp,
                         caller_scope=scope, referenced_symbol=owner + "." + symbol if owner else symbol,
                         implementation_file=dp, caller_git_blob=by_key[repo, cp]["blob_sha"],
                         implementation_git_blob=by_key[repo, dp]["blob_sha"],
                         syntax_link_proved=True, **proof))
    require(len(rows) == 12 and len({x["id"] for x in rows}) == len(rows) and
            dict(roots) == EXPECTED_ROOTS, "registered cross-file task census drift")
    return dict(schema=PROFILE, source_original_zip_sha256=SOURCE_SHA,
                independent_reopen_zip_sha256=REOPEN_SHA, source_cut_utc=SOURCE_CUT,
                original_git_blob_count=32, original_repository_name_proxies=6,
                original_evaluation_repository_proxies=3, original_source_derived_edges=12,
                verified_cross_file_static_links=12, root_counts=dict(sorted(roots.items())),
                python_links=9, rust_literal_import_links=3,
                independent_human_semantic_judgement=False,
                real_project_tests_executed=False, new_model_calls=0,
                new_prospective_task_family=False, task_success_rate=None,
                parameter_learning_advantage=False, complete_lifecycle_tco=None,
                production_qualified=False, cases=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", required=True, type=Path)
    parser.add_argument("--reopen-zip", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit(real_source(args.source_zip, args.reopen_zip))
    write_once(args.output, json.dumps(report, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":")).encode() + b"\n")
    print(json.dumps(dict(static_links=12, original_files=32,
                          new_model_calls=0, production_qualified=False), sort_keys=True))


if __name__ == "__main__":
    main()
