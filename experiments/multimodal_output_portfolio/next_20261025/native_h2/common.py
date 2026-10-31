"""Separate H2 identities; the previous H1 experiment remains immutable."""

import ast
import importlib.util
import json
from pathlib import Path

from ..native.common import ASSETS, MODEL, NATIVE, OBSERVER, SENSOR, SHARED, TEACHER, sha, write


AREA = Path(__file__).parent
REPO = AREA.parents[3]
RAW = Path('/tmp/hepta-ndu-next-native-h2')
ALLOCATION = AREA.parent / 'NATIVE_H2_ALLOCATION.json'


def pins(extra=()):
    files = [MODEL, OBSERVER, SENSOR, TEACHER]
    files += [p for p in AREA.iterdir() if p.suffix in {'.py', '.rs', '.toml'}]
    files += list(extra)
    pending = [p.resolve() for p in files if p.suffix == '.py']
    visited = set()
    while pending:
        path = pending.pop()
        if path in visited: continue
        visited.add(path)
        package = '.'.join(path.relative_to(REPO).with_suffix('').parts[:-1])
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.ImportFrom):
                name = importlib.util.resolve_name('.' * node.level + (node.module or ''), package) if node.level else node.module
                if name:
                    names.append(name)
                    names += [name + '.' + alias.name for alias in node.names if alias.name != '*']
            elif isinstance(node, ast.Import):
                names += [alias.name for alias in node.names]
            for name in names:
                module = REPO.joinpath(*name.split('.'))
                candidates = [module.with_suffix('.py'), module / '__init__.py']
                candidates += [parent / '__init__.py' for parent in module.parents if parent.is_relative_to(REPO)]
                pending += [p for p in candidates if p.is_file() and p not in visited]
    files += list(visited)
    return {str(p.resolve()): sha(p) for p in files}


def qualified_dependencies(*actual_paths):
    """Keep qualification's exact function identity continuous through packaging."""
    protocol_path = AREA / 'QUALIFICATION_PROTOCOL.json'
    protocol = json.loads(protocol_path.read_text())
    expected = protocol.get('frozen_candidate_sha256', {})
    if (protocol.get('study') != 'native_h2_qualification' or not expected
            or protocol.get('source_allocation_sha256') != sha(ALLOCATION)):
        raise ValueError('Exact independent H2 qualification protocol required')
    for path, digest in expected.items():
        if not Path(path).is_absolute() or sha(path) != digest:
            raise ValueError('Qualified dependency changed before actual model use: ' + path)
    for path in (MODEL, SENSOR, TEACHER, OBSERVER, *actual_paths):
        path = Path(path).resolve()
        if expected.get(str(path)) != sha(path):
            raise ValueError('Actual model or encoder argument was not independently qualified: ' + str(path))
    return protocol
