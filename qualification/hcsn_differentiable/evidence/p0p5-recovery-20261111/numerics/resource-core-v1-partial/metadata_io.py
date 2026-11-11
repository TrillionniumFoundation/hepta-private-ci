"""Bounded, immutable metadata I/O. No model or producer imports."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
from zipfile import ZipFile

from resource_arithmetic import require

PROGRAM = Path(__file__).resolve().parent
PLAN_SHA = '4ccfa7cc21ec37312e48d095e8f4b7373c765dd6d33fa9314ce724d161e8b06b'
AUDITOR_SHA = '4cc126ad4cf11e12c80408a868f8c673be70bccdce95a02228fda9d1543ef8d2'
WHOLE, RSS = 120, 512 * 1024**2
AUDIT_WHOLE, AUDIT_RSS = 1800, 2 * 1024**3
JSON_LIMIT = 32 * 1024**2


def digest_bytes(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def identity(path, budget=lambda: None):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), 'nonregular input: '+str(path))
    digest, count = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            budget()
            digest.update(chunk)
            count += len(chunk)
    return {'bytes': count, 'sha256': digest.hexdigest()}


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'duplicate JSON key: '+key)
            value[key] = item
        return value
    def constant(value):
        raise ValueError('nonfinite JSON constant: '+value)
    require(len(raw) <= JSON_LIMIT, 'metadata exceeds fixed JSON byte limit')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


class Inputs:
    def __init__(self, budget=lambda: None):
        self.files, self.budget = {}, budget

    def bind(self, path, expected):
        self.budget()
        path = str(Path(path).resolve())
        item = identity(path, self.budget)
        require(item == expected or item['sha256'] == expected, 'input identity differs: '+path)
        require(path not in self.files or self.files[path] == item, 'input changed: '+path)
        self.files[path] = item
        return Path(path)

    def raw(self, spec, limit=JSON_LIMIT):
        path = self.bind(spec['path'], spec['identity'])
        require(path.stat().st_size <= limit, 'metadata byte limit exceeded: '+str(path))
        raw = path.read_bytes()
        require(digest_bytes(raw) == self.files[str(path)], 'input changed during read')
        return raw

    def json(self, spec):
        return strict_json(self.raw(spec))

    def lines(self, spec):
        return [strict_json(row) for row in self.raw(spec).splitlines() if row]

    def verify(self):
        for path, item in self.files.items():
            require(identity(path, self.budget) == item, 'input changed after analysis: '+path)


def program_manifest(program=PROGRAM):
    path = program/'MANIFEST.json'
    raw = path.read_bytes()
    manifest = strict_json(raw)
    files = manifest['files']
    require(set(files) == {str(p.relative_to(program)) for p in program.rglob('*')
                          if p.is_file() and p.name not in ('MANIFEST.json', 'FREEZE.json')
                          and '__pycache__' not in p.parts}, 'program member roster differs')
    for relative, expected in files.items():
        require(not PurePosixPath(relative).is_absolute() and '..' not in PurePosixPath(relative).parts,
                'unsafe program member')
        require(identity(program/relative) == expected, 'program bytes differ: '+relative)
    return digest_bytes(raw)['sha256']


def authorize(args, inputs):
    auth = inputs.json({'path': args.authorization, 'identity': args.authorization_sha})
    require(auth.get('execution_authorized') is True
            and auth.get('scope') == 'c2-terminal-resource-metadata-only'
            and auth.get('confirmation_E_access') is False, 'separate execution authorization required')
    require(auth['program_manifest_sha256'] == program_manifest()
            and auth['plan_sha256'] == PLAN_SHA and auth['binding_sha256'] == args.binding_sha,
            'authorization is not bound to exact program/plan/inputs')
    require(auth['resources'] == {'whole_hard_wall_seconds': WHOLE, 'peak_RSS_bytes': RSS,
                                 'workers': 1, 'threads': 1, 'automatic_retry': False}, 'resource limits differ')
    plan = inputs.json({'path': str(PROGRAM/'PLAN.json'), 'identity': PLAN_SHA})
    binding = inputs.json({'path': args.binding, 'identity': args.binding_sha})
    require(binding['schema'] == 'c2-resource-input-binding-v1'
            and binding.get('all_six_terminal') is True
            and binding.get('confirmation_E_access') is False, 'post-terminal metadata binding required')
    require(set(binding['fixed_inputs']) == set(plan['fixed_inputs']), 'fixed-input roster differs')
    for original, expected in plan['fixed_inputs'].items():
        inputs.bind(binding['fixed_inputs'][original], expected)
    return auth, plan, binding


class VerifiedArchive:
    """Streams all members for SHA/CRC, but parses only requested JSON metadata."""
    def __init__(self, path, inputs, expected):
        self.path = inputs.bind(path, expected)
        self.budget = inputs.budget
        self.members = {}
        with ZipFile(self.path) as archive:
            names = archive.namelist()
            require(len(names) == len(set(names)), 'duplicate archive members')
            require(all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts
                        and '\\' not in n and not n.endswith('/') for n in names), 'unsafe archive member')
            require(all(((i.external_attr >> 16) & 0o170000) != 0o120000 for i in archive.infolist()), 'symlink member')
            require(archive.getinfo('MANIFEST.json').file_size <= JSON_LIMIT, 'manifest too large')
            self.manifest = strict_json(archive.read('MANIFEST.json'))['files']
            require(set(names) == set(self.manifest) | {'MANIFEST.json'}, 'archive manifest coverage differs')
            for name in names:
                self.budget()
                digest, count = hashlib.sha256(), 0
                with archive.open(name) as stream:
                    for chunk in iter(lambda: stream.read(1024**2), b''):
                        self.budget()
                        digest.update(chunk)
                        count += len(chunk)
                item = {'bytes': count, 'sha256': digest.hexdigest()}
                require(name == 'MANIFEST.json' or item == self.manifest[name], 'archive member changed: '+name)
                self.members[name] = item
        require(identity(self.path, self.budget) == expected, 'archive changed during verification')

    def json(self, name):
        self.budget()
        require(name in self.members and self.members[name]['bytes'] <= JSON_LIMIT, 'missing/oversize metadata member: '+name)
        with ZipFile(self.path) as archive:
            raw = archive.read(name)
        require(digest_bytes(raw) == self.members[name], 'archive metadata changed')
        return strict_json(raw)
