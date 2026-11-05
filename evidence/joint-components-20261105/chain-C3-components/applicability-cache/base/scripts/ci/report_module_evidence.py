#!/usr/bin/env python3
"""Read-only procedure/evidence navigation; never runs a campaign or grants acceptance.

Subject identity, the complete recorded runtime, and an observed exact test selector
are separate facts. Missing coverage is reported, not converted to a passing result.
The existing package validators remain responsible for campaign-specific semantics.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from check_invariant_evidence import load, require, safe, source_bytes

ROOT = Path(__file__).resolve().parents[2]
MATURITY = 'config/pon/module-maturity-v1.json'
PARAMETERS = {
    'config/pon/devnet-v1.json', 'config/pon/ledger-v1.json',
    'config/pon/model-family-v1.json', 'config/pon/work-profile-v1.json',
    'config/pon/evaluation-round-v1.json',
}
KINDS = {
    'pure-component', 'reference-owner', 'native-component-with-reference-caller',
    'controlled-experiment', 'specified-not-integrated', 'native-development-owner',
}
FIELDS = {
    'operation', 'implementation_kind', 'runtime_symbols', 'controlled_entrypoint',
    'ordinary_product_entrypoint', 'backend', 'persistence_owner',
    'evidence_selectors', 'remaining',
}


def python_symbols(text: str) -> set[str]:
    found: set[str] = set()

    def visit(nodes: list[ast.stmt], prefix: str = '') -> None:
        for node in nodes:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + node.name
                found.add(name)
                visit(node.body, name + '.')
    visit(ast.parse(text).body)
    return found


def check_symbol(root: Path, ref: dict[str, str]) -> None:
    require(isinstance(ref, dict) and set(ref) == {'path', 'symbol'}, 'callable binding fields')
    path = safe(root, ref['path'])
    symbol = ref['symbol']
    require(isinstance(symbol, str) and symbol, 'missing callable symbol')
    text = path.read_text()
    if path.suffix == '.py':
        require(symbol in python_symbols(text), 'missing Python owner ' + str(ref))
    elif path.suffix == '.rs':
        # This is a source binding check, not a Rust semantic analyzer or a test pass.
        text = rust_code(text)
        parts = symbol.split('::')
        if len(parts) == 2:
            bodies = list(rust_impl_bodies(text, parts[0]))
            require(bodies, 'missing Rust implementation owner ' + symbol)
            require(any(rust_direct_method(body, parts[1]) for body in bodies),
                    'missing Rust callable ' + symbol)
        else:
            require(re.search(r'\bfn\s+' + re.escape(parts[-1]) + r'\s*[(<]', text),
                    'missing Rust callable ' + symbol)
    else:
        raise ValueError('unsupported callable source ' + ref['path'])


def rust_group_end(code: str, start: int) -> int | None:
    """End of a balanced generic/header group; ignore arrows and const-block operators."""
    pairs = {'<': '>', '(': ')', '[': ']', '{': '}'}
    stack = [pairs[code[start]]]
    for index in range(start + 1, len(code)):
        char = code[index]
        if char in '<>' and ('}' in stack or code[index - 1] == '-'):
            continue
        if char in pairs:
            stack.append(pairs[char])
        elif char in '>)]}':
            if char != stack[-1]:
                return None
            stack.pop()
            if not stack:
                return index + 1
    return None


def rust_impl_bodies(code: str, owner: str):
    """Find this exact inherent owner, including generic declarations and arguments."""
    for match in re.finditer(r'\bimpl\b\s*', code):
        index = match.end()
        if index < len(code) and code[index] == '<':
            index = rust_group_end(code, index)
            if index is None:
                continue
        index += len(code[index:]) - len(code[index:].lstrip())
        named = re.match(re.escape(owner) + r'(?!\w)', code[index:])
        if named is None:
            continue
        index += named.end()
        index += len(code[index:]) - len(code[index:].lstrip())
        if index < len(code) and code[index] == '<':
            index = rust_group_end(code, index)
            if index is None:
                continue
            index += len(code[index:]) - len(code[index:].lstrip())
        where = re.match(r'where\b', code[index:])
        if where:
            index += where.end()
            while index < len(code) and code[index] not in '{;}':
                if code[index] in '<([':
                    end = rust_group_end(code, index)
                    if end is None:
                        break
                    index = end
                else:
                    index += 1
        # In particular, `impl Trait for Owner` cannot become an inherent owner.
        if index >= len(code) or code[index] != '{':
            continue
        depth = 1
        for end in range(index + 1, len(code)):
            depth += (code[end] == '{') - (code[end] == '}')
            if depth == 0:
                yield code[index + 1:end]
                break


def rust_direct_method(body: str, method: str) -> bool:
    """A nested local function or another nested impl is not this owner's method."""
    depth = 0
    pattern = r'[{}()\[\]]|\bfn\s+' + re.escape(method) + r'\s*(?=[(<])'
    for match in re.finditer(pattern, body):
        token = match[0]
        if token in '{([':
            depth += 1
        elif token in '})]':
            depth -= 1
        elif depth == 0:
            return True
    return False


def rust_code(text: str) -> str:
    """Mask comments/string literals, preserving layout for source-only test binding."""
    out = list(text)
    raw_start = re.compile(r'(?:br|r)(#*)"')
    char_start = re.compile(r"'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|.)|[^'\\\n])'")
    i = 0
    while i < len(text):
        start = i
        if text.startswith('//', i):
            end = text.find('\n', i)
            i = len(text) if end < 0 else end
        elif text.startswith('/*', i):
            i += 2
            depth = 1
            while i < len(text) and depth:
                if text.startswith('/*', i):
                    depth += 1
                    i += 2
                elif text.startswith('*/', i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
        elif text[i] in 'br' and (raw := raw_start.match(text, i)):
            terminator = '"' + raw[1]
            end = text.find(terminator, raw.end())
            i = len(text) if end < 0 else end + len(terminator)
        elif text[i] == "'" and (character := char_start.match(text, i)):
            # Lifetimes ('a, '_) have no closing quote and are left as code.
            i = character.end()
        elif text[i] == '"':
            i += 1
            while i < len(text):
                if text[i] == '\\':
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
        else:
            i += 1
            continue
        for j in range(start, min(i, len(text))):
            if text[j] != '\n':
                out[j] = ' '
    return ''.join(out)


def check_test_selector(root: Path, selector: str) -> None:
    """Bind a real test, including Rust tests whose names do not start with test_."""
    path, symbol = selector.split('::', 1)
    check_symbol(root, {'path': path, 'symbol': symbol})
    if path.endswith('.rs'):
        text = rust_code(safe(root, path).read_text())
        require(re.search(r'#\[test\]\s*(?:#\[[^\n]*\]\s*)*fn\s+' +
                          re.escape(symbol) + r'\s*\(', text),
                'not an attributed Rust test selector')
    else:
        require(symbol.split('.')[-1].startswith('test_'), 'not an executable test selector')


def validate_contract(root: Path = ROOT) -> dict[str, Any]:
    """Validate relationships, not paragraph lengths, heading counts or pass quotas."""
    root = Path(root).resolve()
    registry = load(root / 'config/pon/module-contracts-v1.json')
    maturity = load(root / MATURITY)
    contracts = {row['id']: row for row in registry['modules']}
    rows = maturity['modules']
    require(len(rows) == len({row['id'] for row in rows}) and
            {row['id'] for row in rows} == set(contracts), 'responsibility owner coverage')
    for package in maturity['evidence_packages'].values():
        require(set(package) == {'manifest', 'qualification', 'log_prefix', 'scope', 'source_archive'},
                'evidence declaration fields')
        manifest_path = safe(root, package['manifest'])
        if package['qualification'] is not None:
            safe(manifest_path.parent, package['qualification'])
        require(package['log_prefix'] in {'', 'qualification/'}, 'unrecognized log base')
        require(isinstance(package['scope'], str) and package['scope'], 'missing evidence scope')
    operations = 0
    cache: set[tuple[str, str]] = set()
    for row in rows:
        expected = {op['id'] for op in contracts[row['id']]['operations']}
        owners = row['responsibilities']
        require(len(owners) == len({v['operation'] for v in owners}) and
                {v['operation'] for v in owners} == expected, 'procedure responsibility coverage')
        for owner in owners:
            require(set(owner) == FIELDS, 'responsibility fields')
            require(owner['implementation_kind'] in KINDS, 'unknown implementation kind')
            require(all(isinstance(owner[k], str) and owner[k].strip()
                        for k in ('backend', 'remaining')), 'missing scope/backend')
            require(isinstance(owner['runtime_symbols'], list), 'callable list')
            if owner['implementation_kind'] != 'specified-not-integrated':
                require(owner['runtime_symbols'] and owner['controlled_entrypoint'] is not None,
                        'implemented responsibility lacks callable entry')
            else:
                require(owner['controlled_entrypoint'] is None,
                        'specified-only responsibility masquerades as integrated entry')
            require(owner['ordinary_product_entrypoint'] is None or
                    row['native_product_integrated'] is True, 'unearned ordinary product entry')
            refs = owner['runtime_symbols'] + [owner[k] for k in (
                'controlled_entrypoint', 'ordinary_product_entrypoint', 'persistence_owner')
                if owner[k] is not None]
            for ref in refs:
                key = (ref['path'], ref['symbol'])
                if key not in cache:
                    check_symbol(root, ref)
                    cache.add(key)
            selectors = owner['evidence_selectors']
            require(isinstance(selectors, list) and len(selectors) == len(set(selectors)),
                    'duplicate evidence selector')
            for selector in selectors:
                check_test_selector(root, selector)
            operations += 1
    return {'responsibilities': operations, 'bindings_consistent': True,
            'tests_executed_by_this_checker': False, 'acceptance_granted': False}


def runtime_path(path: str) -> bool:
    return (path.startswith(('formal/pon-nakamoto-v1/', 'trillionnium/')) and
            not path.endswith('.md')) or path in PARAMETERS


def observed_selector(selector: str, records: list[dict[str, Any]]) -> bool:
    """A similarly named test in another invocation is not evidence for this one."""
    path, symbol = selector.split('::', 1)
    if path.endswith('.rs'):
        parts = Path(path).parts
        if len(parts) != 5 or parts[:2] != ('trillionnium', 'crates') or parts[3] != 'tests':
            return False
        package, target = parts[2], Path(parts[4]).stem
        expected = ['cargo', 'test', '--offline', '--locked', '--manifest-path',
                    'trillionnium/Cargo.toml', '-p', package, '--test', target, '--', '--nocapture']
        for row in records:
            if row['command'] != expected or type(row['returncode']) is not int or row['returncode'] != 0 or row.get('timed_out', False):
                continue
            text = row['_log_text']
            if (re.search(r'(?m)^\s*Running tests/' + re.escape(target) + r'\.rs ', text)
                and re.search(r'(?m)^test ' + re.escape(symbol) + r' \.\.\.(?:(?!^test ).)*?(?:^| )ok\s*$', text, re.S)
                and re.search(r'(?m)^test result: ok\. \d+ passed; 0 failed;', text)):
                return True
        return False
    if not path.endswith('.py'):
        return False
    method = symbol.rsplit('.', 1)[-1]
    for row in records:
        if (path not in row['command'] or type(row['returncode']) is not int or
                row['returncode'] != 0 or row.get('timed_out', False) is not False):
            continue
        text = row['_log_text']
        if not (re.search(r'(?m)^Ran \d+ tests?\b', text) and re.search(r'(?m)^OK\s*$', text)):
            continue
        # unittest may print (__main__.Class.method), (Class.method), or a module prefix.
        if re.search(r'(?m)^' + re.escape(method) + r' \((?:[\w.]+\.)?' +
                     re.escape(symbol) + r'\)(?:\s+\.\.\.)?\s+ok\s*$', text):
            return True
    return False


def match_sources(root: Path, inputs: dict[str, str], subjects: list[str],
                  current_runtime: set[str]) -> dict[str, Any]:
    """Never turn a partial subject match into a transitive runtime-match claim."""
    changed = []
    absent = []
    for path in subjects:
        if path not in inputs:
            absent.append(path)
        elif not (root / path).is_file() or hashlib.sha256((root / path).read_bytes()).hexdigest() != inputs[path]:
            changed.append(path)
    recorded = {path for path in inputs if runtime_path(path)}
    runtime_changed = [path for path in sorted(recorded & current_runtime)
                       if hashlib.sha256(safe(root, path).read_bytes()).hexdigest() != inputs[path]]
    return {
        'subject_bytes_match': bool(subjects) and not changed and not absent,
        'changed_subjects': changed, 'unrecorded_subjects': absent,
        'complete_recorded_runtime_matches': bool(recorded) and recorded == current_runtime and not runtime_changed,
        'runtime_inventory_added': sorted(current_runtime - recorded),
        'runtime_inventory_removed': sorted(recorded - current_runtime),
        'changed_runtime_inputs': runtime_changed,
    }


def package_snapshot(root: Path, declaration: dict[str, Any]) -> dict[str, Any]:
    manifest_path = safe(root, declaration['manifest'])
    folder = manifest_path.parent
    manifest = load(manifest_path)
    require(manifest['independent_accepted'] is False and manifest['production_activation'] is False,
            'navigation package must not grant acceptance')
    files = manifest['files']
    for relative, digest in files.items():
        require(re.fullmatch('[0-9a-f]{64}', digest) is not None, 'bad artifact digest')
        require(hashlib.sha256(safe(folder, relative).read_bytes()).hexdigest() == digest,
                'changed evidence artifact ' + relative)
    commit = manifest['implementation_commit']
    records: list[dict[str, Any]] = []
    if declaration['qualification'] is None:
        inputs = manifest['source_files_sha256']
        tree = None
    else:
        qualification = declaration['qualification']
        require(qualification in files, 'unmanifested qualification')
        q = load(safe(folder, qualification))
        require(q['source_commit'] == commit and q['source_tree'] == manifest['implementation_tree'],
                'qualification source differs from manifest')
        require(q['source_clean'] is True and q['all_commands_passed'] is True, 'incomplete qualification')
        inputs = dict(q['source_files_sha256'])
        tree = q['source_tree']
        records = [dict(v) for v in q['results']]
        supplement = 'qualification-supplement.json'
        if supplement in files:
            extra = load(safe(folder, supplement))
            require(extra['source_commit'] == commit and extra['source_tree'] == tree and
                    extra['source_clean'] is True, 'supplement source mismatch')
            for path, digest in extra['source_files_sha256'].items():
                require(path not in inputs or inputs[path] == digest, 'supplement fingerprint conflict')
                inputs[path] = digest
            records += [dict(v) for v in extra['results']]
        for row in records:
            relative = declaration['log_prefix'] + row['log']
            require(relative in files, 'unmanifested execution log ' + relative)
            row['_log_text'] = safe(folder, relative).read_text()
    archive = declaration['source_archive']
    binding_commit = commit if archive is None else archive['commit']
    if archive is not None:
        require(declaration['qualification'] is None and set(archive) == {'commit', 'tree'},
                'only the original archival package has a separate binding snapshot')
        require(re.fullmatch('[0-9a-f]{40}', binding_commit), 'bad archive identity')
        actual_archive = subprocess.check_output(['git', 'rev-parse', binding_commit + '^{tree}'],
                                                cwd=root, text=True).strip()
        require(actual_archive == archive['tree'], 'archive tree mismatch')
    originals = source_bytes(root, binding_commit, list(inputs))
    for path, raw in originals.items():
        require(hashlib.sha256(raw).hexdigest() == inputs[path], 'false original-source digest ' + path)
    if tree is not None:
        actual = subprocess.check_output(['git', 'rev-parse', commit + '^{tree}'], cwd=root, text=True).strip()
        require(actual == tree, 'wrong measured tree')
    return {'commit': commit, 'tree': tree, 'source_binding_commit': binding_commit, 'inputs': inputs, 'records': records,
            'scope': declaration['scope'], 'manifest': declaration['manifest'],
            'artifact_integrity_verified': True, 'campaign_semantics_reexecuted': False}


def report(root: Path = ROOT, module: str | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    validate_contract(root)
    data = load(root / MATURITY)
    require(module is None or module in {row['id'] for row in data['modules']}, 'unknown module')
    tracked = set(subprocess.check_output(['git', 'ls-files'], cwd=root, text=True).splitlines())
    # Include newly added candidate runtime files; a stale index must not hide new code.
    untracked = set(subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'],
                                           cwd=root, text=True).splitlines())
    current_runtime = {p for p in tracked | untracked if runtime_path(p) and (root / p).is_file()}
    snapshots = {name: package_snapshot(root, decl) for name, decl in data['evidence_packages'].items()}
    # Full-runtime comparison is shared across procedures, not repeated for every row.
    runtime_matches = {name: match_sources(root, snap['inputs'], [], current_runtime)
                       for name, snap in snapshots.items()}
    rows = []
    for owner in data['modules']:
        if module is not None and owner['id'] != module:
            continue
        for responsibility in owner['responsibilities']:
            refs = responsibility['runtime_symbols'] + [responsibility[k] for k in (
                'controlled_entrypoint', 'persistence_owner') if responsibility[k] is not None]
            subjects = sorted({ref['path'] for ref in refs} | set(PARAMETERS))
            # No implemented subject for a purely specified routine, even when prerequisites exist.
            has_entry = responsibility['controlled_entrypoint'] is not None
            packages = {}
            for name, snap in snapshots.items():
                match = match_sources(root, snap['inputs'], subjects, set())
                match.update({k: v for k, v in runtime_matches[name].items() if k.startswith(('complete_', 'runtime_', 'changed_runtime'))})
                observed = [s for s in responsibility['evidence_selectors']
                            if observed_selector(s, snap['records'])]
                packages[name] = {
                    'measured_commit': snap['commit'], 'measured_tree': snap['tree'],
                    'source_binding_commit': snap['source_binding_commit'],
                    'manifest': snap['manifest'], 'scope': snap['scope'],
                    'artifact_integrity_verified': True, **match,
                    'observed_selectors': observed,
                    'unobserved_selectors': [s for s in responsibility['evidence_selectors'] if s not in observed],
                    'reexecuted_now': False,
                    'current_regression_support': has_entry and bool(observed) and
                        len(observed) == len(responsibility['evidence_selectors']) and
                        match['subject_bytes_match'] and match['complete_recorded_runtime_matches'],
                }
            rows.append({'module': owner['id'], **responsibility, 'packages': packages})
    return {
        'schema': 'pon-responsibility-evidence-report-v1',
        'candidate_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
        'candidate_tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=root, text=True).strip(),
        'candidate_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip()),
        'responsibilities': rows, 'tests_run_by_reporter': False,
        'ordinary_product_integration_granted': False, 'independent_acceptance_granted': False,
        'production_activation': False,
    }


def markdown(value: dict[str, Any]) -> str:
    out = ['# Responsibility evidence at ' + value['candidate_head'], '',
           'Working tree dirty: ' + str(value['candidate_dirty']) + '. No tests are executed by this report.', '',
           '| Responsibility | Package / measured source | Subject bytes | Complete recorded runtime | Exact tests observed / declared |',
           '|---|---|---|---|---|']
    remaining = []
    for row in value['responsibilities']:
        for name, package in row['packages'].items():
            out.append('| ' + row['operation'] + ' | ' + name + ' / `' + package['measured_commit'] + '` | ' +
                       str(package['subject_bytes_match']) + ' | ' + str(package['complete_recorded_runtime_matches']) +
                       ' | ' + str(len(package['observed_selectors'])) + '/' + str(len(row['evidence_selectors'])) + ' |')
        remaining += ['', '**' + row['operation'] + ':** ' + row['remaining']]
    out += remaining + ['']
    out.append('Subject matches are not a new execution, a dependency-closure proof, integration, or independent acceptance.')
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module')
    parser.add_argument('--format', choices=['json', 'markdown'], default='json')
    parser.add_argument('--bindings-only', action='store_true')
    args = parser.parse_args()
    value = validate_contract() if args.bindings_only else report(module=args.module)
    print(markdown(value) if args.format == 'markdown' and not args.bindings_only
          else json.dumps(value, indent=2, sort_keys=True))
