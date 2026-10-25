"""Bounded NEW JSON observations. No arbitrary diagnostic strings are exported."""
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tomllib

REGISTRY = 'registry+https://github.com/rust-lang/crates.io-index'
DB_PARTS = ('advisory-dbs', 'advisory-db-3157b0e258782691', '.git')
SHA = re.compile(rb'[0-9a-f]{40}')
LIMIT = 2**32 - 1


def lock_allowlist(data):
    """Bounded immutable lock input, refusing cross-source identity ambiguity."""
    if len(data) > 4 * 1024**2:
        raise ValueError('lock_bound')
    packages = tomllib.loads(data.decode('utf-8')).get('package')
    if not isinstance(packages, list) or len(packages) > 32768:
        raise ValueError('lock_shape')
    identities = {}
    for package in packages:
        name, version = package.get('name'), package.get('version')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', name):
            raise ValueError('lock_name')
        if not isinstance(version, str) or not re.fullmatch(r'[0-9A-Za-z.+-]{1,128}', version):
            raise ValueError('lock_version')
        identities.setdefault((name, version), set()).add(package.get('source'))
    return {key: key for key, sources in identities.items() if sources == {REGISTRY}}


def default_db_config(data):
    if len(data) > 4 * 1024**2:
        return False
    try:
        config = tomllib.loads(data.decode('utf-8'))
        advisory = config.get('advisories', {})
        return (isinstance(advisory, dict) and 'db-path' not in advisory
                and 'db-urls' not in advisory and not advisory.get('git-fetch-with-cli', False))
    except (ValueError, UnicodeError):
        return False


class JSONObservations:
    LINE_LIMIT = 1024 * 1024
    ROW_LIMIT = 256
    COUNT_LIMIT = LIMIT
    REASONS = ('non_json', 'overlong', 'invalid_json', 'depth', 'shape', 'class',
               'advisory', 'root', 'lock', 'rows_full')

    def __init__(self, allowed):
        self.allowed = allowed
        self.pending = b''
        self.dropping = False
        self.rows = {}
        self.rejected = dict.fromkeys(self.REASONS, 0)
        self.saturated = False

    def increment(self, mapping, key):
        if mapping[key] < self.COUNT_LIMIT:
            mapping[key] += 1
        else:
            self.saturated = True

    @staticmethod
    def pairs(pairs):
        result = {}
        if len(pairs) > 256:
            raise ValueError('shape')
        for key, value in pairs:
            if key in result:
                raise ValueError('shape')
            result[key] = value
        return result

    @staticmethod
    def nonfinite(_):
        raise ValueError('invalid_json')

    @staticmethod
    def finite_float(value):
        # parse_constant does not catch overflow from valid JSON exponents.
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError('invalid_json')
        return parsed

    @staticmethod
    def depth_ok(data):
        quoted = escaped = False
        depth = 0
        for byte in data:
            if quoted:
                if escaped:
                    escaped = False
                elif byte == 92:
                    escaped = True
                elif byte == 34:
                    quoted = False
            elif byte == 34:
                quoted = True
            elif byte in (91, 123):
                depth += 1
                if depth > 32:
                    return False
            elif byte in (93, 125):
                depth -= 1
        return True

    def project(self, obj):
        if not isinstance(obj, dict) or obj.get('type') != 'diagnostic':
            return 'shape'
        fields = obj.get('fields')
        if not isinstance(fields, dict):
            return 'shape'
        severity, code = fields.get('severity'), fields.get('code')
        if severity not in ('error', 'warning') or code not in ('vulnerability', 'unmaintained'):
            return 'class'
        advisory = fields.get('advisory')
        if not isinstance(advisory, dict) or not {'id', 'package', 'source', 'collection', 'withdrawn', 'informational'} <= advisory.keys():
            return 'advisory'
        identifier, name = advisory.get('id'), advisory.get('package')
        if (not isinstance(identifier, str) or not re.fullmatch(r'RUSTSEC-[0-9]{4}-[0-9]{4}', identifier)
                or not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', name)
                or advisory.get('collection') not in (None, 'crates')
                or advisory.get('source') is not None or advisory.get('withdrawn') is not None
                or advisory.get('informational') != (None if code == 'vulnerability' else 'unmaintained')):
            return 'advisory'
        graphs = fields.get('graphs')
        if not isinstance(graphs, list) or len(graphs) != 1 or not isinstance(graphs[0], dict):
            return 'root'
        krate = graphs[0].get('Krate')
        if not isinstance(krate, dict) or 'Feature' in graphs[0]:
            return 'root'
        root_name, version = krate.get('name'), krate.get('version')
        if not isinstance(root_name, str) or not isinstance(version, str):
            return 'lock'
        pair = (root_name, version)
        if root_name != name or pair not in self.allowed:
            return 'lock'
        # Only copy name/version from hash-bound lock inputs.
        package, version = self.allowed[pair]
        key = (severity, code, identifier, package, version)
        if key not in self.rows:
            if len(self.rows) >= self.ROW_LIMIT:
                return 'rows_full'
            self.rows[key] = 0
        self.increment(self.rows, key)
        return None

    def line(self):
        data = self.pending
        reason = None
        if self.dropping:
            reason = 'overlong'
        elif not data.lstrip().startswith(b'{'):
            reason = 'non_json'
        elif not self.depth_ok(data):
            reason = 'depth'
        else:
            try:
                obj = json.loads(data.decode('utf-8'), object_pairs_hook=self.pairs,
                                 parse_constant=self.nonfinite, parse_float=self.finite_float)
                reason = self.project(obj)
            except (ValueError, UnicodeError, RecursionError, TypeError):
                reason = 'invalid_json'
        if reason:
            self.increment(self.rejected, reason)
        self.pending = b''
        self.dropping = False

    def feed(self, data):
        pieces = data.split(b'\n')
        for index, piece in enumerate(pieces):
            if not self.dropping:
                if len(self.pending) + len(piece) > self.LINE_LIMIT:
                    self.pending = b''
                    self.dropping = True
                else:
                    self.pending += piece
            if index < len(pieces) - 1:
                self.line()

    def finish(self):
        if self.pending or self.dropping:
            self.line()

    def receipt(self, permitted, complete):
        return {'schema': 'new_json_lock_validated_observations_v1',
                'declared_version': '0.19.0', 'actual_binary_verified': False,
                'historical_match_proven': False, 'advisory_content_verified': False,
                'status': 'revision_bound_observations' if permitted else 'provenance_or_execution_gate',
                'complete': complete, 'count_saturated': self.saturated,
                'rejected': self.rejected,
                'tuples': [dict(zip(('severity', 'code', 'advisory_id', 'package', 'version'), key), count=count)
                           for key, count in sorted(self.rows.items())] if permitted else []}


class MetadataInvalid(Exception):
    pass


def revision_receipt(cargo):
    """Future owned cache only. Fixed paths; no discovery and no denied-read fallback."""
    result = {'status': 'unavailable', 'commit': None, 'head_form': None,
              'metadata_sha256': {}, 'bytes': {}}
    descriptors = []
    seen = {}
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC

    def directory(parent, name):
        fd = os.open(name, flags | os.O_DIRECTORY, dir_fd=parent)
        descriptors.append(fd)
        return fd

    def read(parent, name, limit, key):
        fd = os.open(name, flags | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise MetadataInvalid()
            data = b''
            while len(data) <= limit:
                chunk = os.read(fd, limit + 1 - len(data))
                if not chunk:
                    break
                data += chunk
            after = os.fstat(fd)
            identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
            if len(data) > limit or identity(before) != identity(after):
                raise MetadataInvalid()
            value = (data, identity(after))
            if key in seen and seen[key] != value:
                raise MetadataInvalid()
            seen[key] = value
            return data
        finally:
            os.close(fd)

    try:
        # Anchor at filesystem root, checking EVERY ancestor rather than resolving symlinks.
        absolute = Path(os.path.abspath(cargo))
        parent = directory(None, '/')
        for part in absolute.parts[1:] + DB_PARTS:
            parent = directory(parent, part)
        gitdir = parent
        head = read(gitdir, 'HEAD', 256, 'head')
        target = None
        packed = False
        if re.fullmatch(rb'[0-9a-f]{40}\n?', head):
            commit = head.rstrip(b'\n')
            form = 'direct'
        elif head in (b'ref: refs/heads/main\n', b'ref: refs/heads/master\n'):
            ref = head[5:-1]
            form = 'main' if ref.endswith(b'/main') else 'master'
            try:
                refs = directory(gitdir, 'refs')
                heads = directory(refs, 'heads')
                target = (heads, form)
                raw_ref = read(heads, form, 64, 'ref')
                if not re.fullmatch(rb'[0-9a-f]{40}\n?', raw_ref):
                    raise MetadataInvalid()
                commit = raw_ref.rstrip(b'\n')
            except FileNotFoundError:
                # Only genuine absence permits the documented packed-ref layout.
                target = None
                packed = True
                data = read(gitdir, 'packed-refs', 65536, 'packed_refs')
                lines = data.splitlines()
                if len(lines) > 1024:
                    raise MetadataInvalid()
                found = []
                for line in lines:
                    if line.startswith(b'#'):
                        continue
                    match = re.fullmatch(rb'([0-9a-f]{40}) ([A-Za-z0-9_./-]+)', line)
                    if not match:
                        raise MetadataInvalid()
                    if match[2] == ref:
                        found.append(match[1])
                if len(found) != 1:
                    raise MetadataInvalid()
                commit = found[0]
        else:
            result['status'] = 'unsupported_head'
            return result
        if not SHA.fullmatch(commit):
            raise MetadataInvalid()
        fetched = read(gitdir, 'FETCH_HEAD', 4096, 'fetch_head')
        first = fetched.split(b'\n', 1)[0]
        # Only owner spelling is case-insensitive; no arbitrary URLs or query components.
        match = re.fullmatch(rb'([0-9a-f]{40})\t\thttps://github\.com/(?i:rustsec)/advisory-db', first)
        if not match or match[1] != commit:
            raise MetadataInvalid()
        # Stability reads happen only after ALL initial reads succeeded.
        read(gitdir, 'HEAD', 256, 'head')
        if packed:
            read(gitdir, 'packed-refs', 65536, 'packed_refs')
        elif target:
            read(target[0], target[1], 64, 'ref')
        read(gitdir, 'FETCH_HEAD', 4096, 'fetch_head')
        result.update(status='verified', commit=commit.decode('ascii'), head_form=form)
        result['metadata_sha256'] = {key: hashlib.sha256(value[0]).hexdigest() for key, value in seen.items()}
        result['bytes'] = {key: len(value[0]) for key, value in seen.items()}
    except OSError as error:
        result['status'] = 'denied' if error.errno in (errno.EACCES, errno.EPERM) else 'unavailable_or_unsafe'
    except MetadataInvalid:
        result['status'] = 'invalid_or_changed'
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
    return result
