"""Read-only installed-runtime integrity snapshot; no third-party imports."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
from common import sha256


def snapshot():
    distributions = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata['Name']
        assert name and name not in distributions, 'Duplicate/unnamed installed distribution'
        files = {}
        declared = distribution.files
        assert declared is not None, f'No installed file manifest for {name}'
        for relative in sorted(declared, key=str):
            path = Path(distribution.locate_file(relative))
            if path.is_file():
                files[str(relative)] = {'sha256': sha256(path), 'bytes': path.stat().st_size}
            else:
                files[str(relative)] = {'missing_declared_file': True}
        distributions[name] = {'version': distribution.version, 'files': files}
    return {'schema': 1, 'python_executable_sha256': sha256(Path(sys.executable).resolve()),
            'python_version': sys.version, 'python_build': platform.python_build(),
            'python_compiler': platform.python_compiler(), 'distributions': distributions}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def verify(expected):
    actual = snapshot()
    assert digest(actual) == digest(expected), 'Installed runtime files or Python identity changed after admission'
    return digest(actual)


if __name__ == '__main__':
    # Only after authorized runtime acquisition; redirects are chosen by the parent.
    print(json.dumps(snapshot(), indent=2))
