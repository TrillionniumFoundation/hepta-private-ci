"""Exact project import closure and actually loaded executable dependency pins."""

import ast
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from .common import REPO, sha, write


def project_closure(entries):
    pending = [Path(p).resolve() for p in entries]
    found = {}

    def add_module(name):
        base = REPO.joinpath(*name.split('.'))
        candidates = (base.with_suffix('.py'), base / '__init__.py')
        for candidate in candidates:
            if candidate.is_file() and str(candidate.resolve()) not in found:
                pending.append(candidate.resolve())

    while pending:
        path = pending.pop()
        if str(path) in found: continue
        relative = path.relative_to(REPO)
        module = '.'.join(relative.with_suffix('').parts)
        package = module.rsplit('.', 1)[0]
        if path.name == '__init__.py': package = package
        found[str(path)] = sha(path)
        for parent in path.parents:
            if parent == REPO: break
            init = parent / '__init__.py'
            if init.is_file() and str(init) not in found: pending.append(init)
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                for alias in node.names: add_module(alias.name)
            elif isinstance(node, ast.ImportFrom):
                name = node.module or ''
                if node.level:
                    name = importlib.util.resolve_name('.' * node.level + name, package)
                add_module(name)
                for alias in node.names:
                    if alias.name != '*': add_module(name + '.' + alias.name)
    return dict(sorted(found.items()))


def runtime_snapshot(path):
    """Call after an actual complete host execution, before independent freeze."""
    loaded = set()
    for module in tuple(sys.modules.values()):
        value = getattr(module, '__file__', None)
        if value and Path(value).is_file():
            loaded.add(Path(value).resolve())
            cached = getattr(module, '__cached__', None)
            if cached and Path(cached).is_file(): loaded.add(Path(cached).resolve())
    # Include actual mapped torch/BLAS/ONNX/glibc code, not just Python package
    # versions. Anonymous buffers and model data mappings are not executable.
    for line in Path('/proc/self/maps').read_text().splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) == 6 and 'x' in fields[1] and fields[5].startswith('/'):
            candidate = Path(fields[5])
            if candidate.is_file(): loaded.add(candidate.resolve())
    codec_receipts = {}
    for name in ('ffmpeg', 'ffprobe'):
        executable = Path(shutil.which(name)).resolve()
        loaded.add(executable)
        linkage = subprocess.run(['ldd', str(executable)], capture_output=True, text=True, check=True).stdout
        dependencies = re.findall(r'(?:=>\s+)?(/\S+)\s+\(', linkage)
        for dependency in dependencies:
            if Path(dependency).is_file(): loaded.add(Path(dependency).resolve())
        codec_receipts[name] = {'executable': str(executable), 'ldd': linkage}
    record = {'schema': 'hepta.advance.executed-runtime-dependency-pins.v1',
        'pins': {str(p): sha(p) for p in sorted(loaded)}, 'codecs': codec_receipts,
        'scope': 'Actual loaded Python source/bytecode, executable process mappings and codec ldd dependencies after old-source complete execution',
        'new_confirmation_sources_used': False}
    write(path, record)
    return record
