"""Research reference: one SQLite authority, Ed25519 identities, no remote consensus.

Authority(path, authority_key, admin_public, evaluator=None,
          structure_evaluator=None).apply(signed_request)
Trusted evaluator(candidate_id, tuple(parent_ids), manifest_copy, verified_bytes)
returns GateDecision. structure_evaluator(plan_digest, plan_copy, verified_children)
returns StructureDecision; absent gates fail closed. Both receive immutable bytes.
Client approval fields are never consumed. The evaluator must run a real experiment;
unit-test fixture gates establish protocol behavior only. All addresses are exact.

SQLite WAL/FULL fences concurrent cooperating processes on ONE authority filesystem.
It does not withstand rollback of that whole filesystem, malicious authority admins,
or compromise of service signing keys. Ready verifies bytes supplied by a receiver;
it is not proof of physical remote persistence. Reads linearize at this authority;
remote final-use fencing, cryptographic erasure and production consensus are absent.
Ed25519 is not post-quantum. Cross-owner split/merge is deliberately unsupported.
"""

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from types import MappingProxyType
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

COMPONENTS = frozenset(('model', 'memory', 'encoder', 'tokenizer', 'schema', 'routing',
                        'calibration', 'optimizer', 'rng', 'sampler', 'runtime'))
DOMAIN = 'hepta.memory-cell.v15'


class Rejected(Exception):
    def __init__(self, reason, receipt=None):
        super().__init__(reason)
        self.receipt = receipt


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def public(key):
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def _identity(value):
    try:
        raw = bytes.fromhex(value)
        if len(raw) != 32 or raw.hex() != value:
            raise ValueError()
        Ed25519PublicKey.from_public_bytes(raw)
    except (TypeError, ValueError):
        raise Rejected('invalid identity')
    return value


def sign(key, authority, operation, args, request_id=None):
    value = dict(domain=DOMAIN, authority=authority, actor=public(key),
                 operation=operation, args=args, request_id=request_id or uuid.uuid4().hex)
    value['signature'] = key.sign(canonical(value)).hex()
    return value


def verify(value, authority):
    try:
        if set(value) != {'domain', 'authority', 'actor', 'operation', 'args', 'request_id', 'signature'}:
            raise ValueError()
        if value['domain'] != DOMAIN or value['authority'] != authority:
            raise ValueError()
        if not isinstance(value['request_id'], str) or not 1 <= len(value['request_id']) <= 128:
            raise ValueError()
        payload = {k: v for k, v in value.items() if k != 'signature'}
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(_identity(value['actor']))).verify(
            bytes.fromhex(value['signature']), canonical(payload))
    except Exception as exc:
        raise Rejected('invalid signed request') from exc


def bundle(scope, addresses, acl, sources, components):
    """Build transport object. sources are exact id/revision/hash dependency records."""
    manifest = dict(format=DOMAIN, scope=scope, addresses=sorted(addresses), acl=sorted(acl),
                    sources=sorted(sources, key=lambda x: x['id']),
                    components={k: digest(v) for k, v in sorted(components.items())})
    return dict(id=digest(canonical(manifest)), manifest=manifest,
                objects={k: v.hex() for k, v in components.items()})


@dataclass(frozen=True)
class GateDecision:
    candidate_id: str
    parent_ids: tuple
    approved: bool
    evidence_digest: str


@dataclass(frozen=True)
class StructureDecision:
    plan_digest: str
    approved: bool
    evidence_digest: str


def _evidence(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


class Authority:
    def __init__(self, path, authority_key, admin_public, evaluator=None, structure_evaluator=None):
        self.key, self.identity, self.admin = authority_key, public(authority_key), _identity(admin_public)
        self.evaluator = evaluator
        self.structure_evaluator = structure_evaluator
        self.db = sqlite3.connect(path, timeout=20, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sources(scope TEXT, id TEXT, revision INTEGER, hash TEXT,
          body TEXT, active INTEGER, PRIMARY KEY(scope,id));
        CREATE TABLE IF NOT EXISTS source_history(scope TEXT,id TEXT,revision INTEGER,hash TEXT,
          body TEXT,active INTEGER,PRIMARY KEY(scope,id,revision));
        CREATE TABLE IF NOT EXISTS objects(hash TEXT PRIMARY KEY,data BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS bundles(id TEXT PRIMARY KEY,manifest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cells(id TEXT PRIMARY KEY,scope TEXT,owner TEXT,epoch INTEGER,
          bundle TEXT,state TEXT,acl TEXT);
        CREATE TABLE IF NOT EXISTS addresses(scope TEXT,address TEXT,cell TEXT,
          PRIMARY KEY(scope,address));
        CREATE TABLE IF NOT EXISTS transfers(id TEXT PRIMARY KEY,cell TEXT,epoch INTEGER,
          source TEXT,target TEXT,bundle TEXT,state TEXT,ready_request TEXT);
        CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,command_hash TEXT,response TEXT,
          signed_request TEXT);
        CREATE TABLE IF NOT EXISTS rejections(command_hash TEXT PRIMARY KEY,id TEXT,response TEXT,
          signed_request TEXT);
        CREATE TABLE IF NOT EXISTS request_bindings(id TEXT PRIMARY KEY,command_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS recovery_transfers(id TEXT PRIMARY KEY,controller TEXT);
        ''')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            for name, expected in [('authority', self.identity), ('admin', self.admin)]:
                self.db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)', (name, expected))
                if self.db.execute('SELECT v FROM meta WHERE k=?', (name,)).fetchone()[0] != expected:
                    raise Rejected('authority or admin identity changed')
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def close(self):
        self.db.close()

    def _manifest(self, identifier):
        row = self.db.execute('SELECT manifest FROM bundles WHERE id=?', (identifier,)).fetchone()
        if row is None or digest(row[0].encode()) != identifier:
            raise Rejected('missing or corrupted bundle')
        return json.loads(row[0])

    def _fresh(self, manifest):
        for dependency in manifest['sources']:
            row = self.db.execute('SELECT * FROM sources WHERE scope=? AND id=?',
                                  (manifest['scope'], dependency['id'])).fetchone()
            if not row or not row['active'] or (row['revision'], row['hash']) != (
                    dependency['revision'], dependency['hash']):
                raise Rejected('source revoked or stale')

    def _validate(self, item, parents=(), acl=None, addresses=None):
        try:
            m = item['manifest']
            if set(item) != {'id', 'manifest', 'objects'} or set(m) != {
                    'format', 'scope', 'addresses', 'acl', 'sources', 'components'}:
                raise ValueError()
            if m['format'] != DOMAIN or not isinstance(m['scope'], str) or not m['scope']:
                raise ValueError()
            for field in ('addresses', 'acl'):
                if not isinstance(m[field], list) or m[field] != sorted(set(m[field])) or (field == 'addresses' and not m[field]):
                    raise ValueError()
            if any(not isinstance(a, str) or not a for a in m['addresses']):
                raise ValueError()
            for actor in m['acl']:
                _identity(actor)
            if set(m['components']) != COMPONENTS or set(item['objects']) != COMPONENTS:
                raise ValueError()
            blobs = {name: bytes.fromhex(value) for name, value in item['objects'].items()}
            if sum(map(len, blobs.values())) > 64 * 1024 * 1024:
                raise ValueError()
            if any(digest(data) != m['components'][name] for name, data in blobs.items()):
                raise ValueError()
            if digest(canonical(m)) != item['id']:
                raise ValueError()
            ids = [s['id'] for s in m['sources']]
            if ids != sorted(set(ids)):
                raise ValueError()
            for source in m['sources']:
                if set(source) != {'id', 'revision', 'hash'} or not isinstance(source['id'], str):
                    raise ValueError()
                if type(source['revision']) is not int or source['revision'] <= 0:
                    raise ValueError()
            if acl is not None and set(m['acl']) != set(acl):
                raise Rejected('permission change requires current authority policy')
            if addresses is not None and set(m['addresses']) != set(addresses):
                raise Rejected('address set changed outside reshape')
            required = {s['id'] for parent in parents for s in self._manifest(parent)['sources']}
            if not required <= set(ids):
                raise Rejected('source lineage dropped')
            if any(self._manifest(p)['scope'] != m['scope'] for p in parents):
                raise Rejected('scope mismatch')
            self._fresh(m)
            return m, blobs
        except (KeyError, TypeError, ValueError) as exc:
            raise Rejected('invalid bundle or object digest') from exc

    def _store(self, item, parents=(), acl=None, addresses=None):
        m, blobs = self._validate(item, parents, acl, addresses)
        isolated = json.loads(canonical(m))
        decision = self.evaluator(item['id'], tuple(parents), isolated, MappingProxyType(dict(blobs))) if self.evaluator else None
        if type(decision) is not GateDecision or decision.approved is not True or (
                decision.candidate_id, decision.parent_ids) != (item['id'], tuple(parents)):
            raise Rejected('trusted quality admission refused')
        if (not _evidence(decision.evidence_digest) or digest(canonical(isolated)) != item['id']
                or digest(canonical(m)) != item['id']):
            raise Rejected('missing bound evaluation evidence or manifest changed')
        for name, data in blobs.items():
            self.db.execute('INSERT OR IGNORE INTO objects VALUES (?,?)', (m['components'][name], data))
            if self.db.execute('SELECT data FROM objects WHERE hash=?', (m['components'][name],)).fetchone()[0] != data:
                raise Rejected('immutable object conflict')
        self.db.execute('INSERT OR IGNORE INTO bundles VALUES (?,?)', (item['id'], canonical(m).decode()))
        return decision.evidence_digest

    def _cell(self, args, actor, allow_prepared=False):
        row = self.db.execute('SELECT * FROM cells WHERE id=?', (args['cell'],)).fetchone()
        if not row or row['owner'] != actor:
            raise Rejected('not current owner')
        if type(args['epoch']) is not int or (row['epoch'], row['bundle']) != (args['epoch'], args['expected']):
            raise Rejected('epoch or bundle CAS failed')
        if row['state'] != 'active' and not (allow_prepared and row['state'] == 'prepared'):
            raise Rejected('cell frozen or retired')
        return row

    def _admin(self, actor):
        if actor != self.admin:
            raise Rejected('admin signature required')

    def _addresses(self, row):
        return [x[0] for x in self.db.execute('SELECT address FROM addresses WHERE cell=? ORDER BY address', (row['id'],))]

    def _load_bundle(self, identifier):
        m, objects = self._manifest(identifier), {}
        for name, identifier_hash in m['components'].items():
            row = self.db.execute('SELECT data FROM objects WHERE hash=?', (identifier_hash,)).fetchone()
            if not row or digest(row[0]) != identifier_hash:
                raise Rejected('missing or corrupted object')
            objects[name] = row[0].hex()
        return dict(id=identifier, manifest=m, objects=objects)

    def _structure(self, args, actor, parents, prior_ids, acl):
        verified = [self._validate(c['bundle'], prior_ids, acl) for c in args['children']]
        plan = dict(domain=DOMAIN, authority=self.identity, operation='reshape', actor=actor,
                    parents=[dict(state=dict(p, acl=json.loads(p['acl'])), addresses=self._addresses(p),
                                  bundle=self._load_bundle(p['bundle'])) for p in parents],
                    children=[dict(cell=c['cell'], owner=actor, bundle=dict(id=c['bundle']['id'], manifest=m))
                              for c, (m, _) in zip(args['children'], verified)])
        identifier = digest(canonical(plan))
        isolated = json.loads(canonical(plan))
        immutable = tuple(MappingProxyType(dict(objects)) for _, objects in verified)
        decision = self.structure_evaluator(identifier, isolated, immutable) if self.structure_evaluator else None
        if type(decision) is not StructureDecision or decision.approved is not True or decision.plan_digest != identifier:
            raise Rejected('trusted structure admission refused')
        if not _evidence(decision.evidence_digest) or digest(canonical(isolated)) != identifier:
            raise Rejected('missing bound structure evidence or plan changed')
        return identifier, decision.evidence_digest

    def _new_cell(self, name, owner, item, epoch=1):
        m = item['manifest']
        self.db.execute('INSERT INTO cells VALUES (?,?,?,?,?,?,?)',
                        (name, m['scope'], _identity(owner), epoch, item['id'], 'active', canonical(m['acl']).decode()))
        self.db.executemany('INSERT INTO addresses VALUES (?,?,?)', [(m['scope'], a, name) for a in m['addresses']])
        return dict(cell=name, owner=owner, epoch=epoch, bundle=item['id'])

    def _dispatch(self, op, a, actor):
        if op == 'source':
            self._admin(actor)
            if any(not isinstance(a.get(field), str) or not a[field] for field in ('scope', 'id', 'body')):
                raise Rejected('source scope, id and body must be nonempty strings')
            row = self.db.execute('SELECT revision FROM sources WHERE scope=? AND id=?', (a['scope'], a['id'])).fetchone()
            prior = row[0] if row else 0
            if type(a['expected_revision']) is not int or a['expected_revision'] != prior or type(a['active']) is not bool:
                raise Rejected('source CAS failed')
            record = (a['scope'], a['id'], prior + 1, digest(a['body'].encode()), a['body'], int(a['active']))
            self.db.execute('INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?)', record)
            self.db.execute('INSERT INTO source_history VALUES (?,?,?,?,?,?)', record)
            return dict(id=a['id'], revision=record[2], hash=record[3], active=a['active'])
        if op == 'create':
            self._admin(actor)
            evidence = self._store(a['bundle'])
            result = self._new_cell(a['cell'], a['owner'], a['bundle'])
            return dict(result, evidence=evidence)
        if op in ('publish', 'prepare', 'recover_prepare', 'restrict'):
            owner = actor
            if op == 'recover_prepare':
                self._admin(actor)
                incumbent = self.db.execute('SELECT owner FROM cells WHERE id=?', (a['cell'],)).fetchone()
                if not incumbent:
                    raise Rejected('unknown recovery cell')
                owner = incumbent[0]
            row = self._cell(a, owner)
            if op == 'publish':
                evidence = self._store(a['bundle'], (row['bundle'],), json.loads(row['acl']), self._addresses(row))
                self.db.execute('UPDATE cells SET bundle=?,epoch=epoch+1 WHERE id=?', (a['bundle']['id'], row['id']))
                return dict(cell=row['id'], epoch=row['epoch']+1, bundle=a['bundle']['id'], evidence=evidence)
            if op == 'restrict':
                if not isinstance(a['acl'], list):
                    raise Rejected('ACL must be a list')
                acl = sorted(set(a['acl']))
                if not set(acl) <= set(json.loads(row['acl'])):
                    raise Rejected('permission expansion refused')
                self.db.execute('UPDATE cells SET acl=?,epoch=epoch+1 WHERE id=?', (canonical(acl).decode(), row['id']))
                return dict(cell=row['id'], epoch=row['epoch']+1, acl=acl)
            self._fresh(self._manifest(row['bundle']))
            target = _identity(a['target'])
            if target == row['owner']:
                raise Rejected('same-owner transfer')
            self.db.execute('INSERT INTO transfers VALUES (?,?,?,?,?,?,?,?)',
                            (a['transfer'], row['id'], row['epoch']+1, row['owner'], target, row['bundle'], 'prepared', None,))
            if op == 'recover_prepare':
                self.db.execute('INSERT INTO recovery_transfers VALUES (?,?)', (a['transfer'], actor))
            self.db.execute("UPDATE cells SET state='prepared',epoch=epoch+1 WHERE id=?", (row['id'],))
            return dict(transfer=a['transfer'], epoch=row['epoch']+1, bundle=row['bundle'], state='prepared')
        if op in ('ready', 'commit', 'abort'):
            t = self.db.execute('SELECT * FROM transfers WHERE id=?', (a['transfer'],)).fetchone()
            if not t:
                raise Rejected('unknown transfer')
            row = self.db.execute('SELECT * FROM cells WHERE id=?', (t['cell'],)).fetchone()
            if a['cell'] != t['cell'] or type(a['epoch']) is not int or (a['epoch'], a['expected']) != (t['epoch'], t['bundle']):
                raise Rejected('transfer CAS failed')
            if (row['epoch'], row['bundle'], row['state'], row['owner']) != (t['epoch'], t['bundle'], 'prepared', t['source']):
                raise Rejected('transfer no longer current')
            if op == 'abort':
                recovery = self.db.execute('SELECT controller FROM recovery_transfers WHERE id=?', (t['id'],)).fetchone()
                allowed = (recovery[0],) if recovery else (t['source'], self.admin)
                if actor not in allowed or t['state'] not in ('prepared', 'ready'):
                    raise Rejected('abort refused')
                new_owner, state = t['source'], 'aborted'
            else:
                if actor != t['target'] or t['state'] != ('prepared' if op == 'ready' else 'ready'):
                    raise Rejected('receiver signature or state mismatch')
                self._fresh(self._manifest(t['bundle']))
                if op == 'ready':
                    if a['bundle']['id'] != t['bundle']:
                        raise Rejected('receiver bundle mismatch')
                    self._validate(a['bundle'], addresses=self._addresses(row))
                    self.db.execute("UPDATE transfers SET state='ready',ready_request=? WHERE id=?", (digest(canonical(a)), t['id']))
                    return dict(transfer=t['id'], state='ready', epoch=t['epoch'], bundle=t['bundle'])
                new_owner, state = t['target'], 'committed'
            self.db.execute("UPDATE cells SET state='active',owner=?,epoch=epoch+1 WHERE id=?", (new_owner, row['id']))
            self.db.execute('UPDATE transfers SET state=? WHERE id=?', (state, t['id']))
            return dict(transfer=t['id'], cell=row['id'], state=state, owner=new_owner, epoch=row['epoch']+1, bundle=row['bundle'])
        if op == 'reshape':
            parents = [self._cell(p, actor) for p in a['parents']]
            if not parents or len({p['id'] for p in parents}) != len(parents):
                raise Rejected('duplicate or empty parents')
            if len({p['scope'] for p in parents}) != 1:
                raise Rejected('cross-scope reshape')
            prior_ids = tuple(p['bundle'] for p in parents)
            acl = set.intersection(*(set(json.loads(p['acl'])) for p in parents))
            all_addresses = [x for p in parents for x in self._addresses(p)]
            children_addresses = [x for child in a['children'] for x in child['bundle']['manifest']['addresses']]
            if not a['children'] or len(set(children_addresses)) != len(children_addresses) or set(all_addresses) != set(children_addresses):
                raise Rejected('reshape must partition all addresses exactly')
            plan, structure_evidence = self._structure(a, actor, parents, prior_ids, acl)
            evidence = [self._store(c['bundle'], prior_ids, acl) for c in a['children']]
            for p in parents:
                self.db.execute("UPDATE cells SET state='retired',epoch=epoch+1 WHERE id=?", (p['id'],))
                self.db.execute('DELETE FROM addresses WHERE cell=?', (p['id'],))
            children = [self._new_cell(c['cell'], actor, c['bundle']) for c in a['children']]
            return dict(parents=[p['id'] for p in parents], children=children, evidence=evidence,
                        plan=plan, structure_evidence=structure_evidence)
        if op == 'status':
            row = self.db.execute('SELECT * FROM cells WHERE id=?', (a['cell'],)).fetchone()
            transfers = self.db.execute('SELECT * FROM transfers WHERE cell=? ORDER BY id', (a['cell'],)).fetchall()
            if not row or actor not in {self.admin, row['owner']} | {t['target'] for t in transfers if t['state'] in ('prepared', 'ready')}:
                raise Rejected('status denied')
            return dict(cell=dict(row), transfers=[dict(t) for t in transfers])
        if op == 'read':
            row = self.db.execute('SELECT c.* FROM cells c JOIN addresses a ON a.cell=c.id WHERE a.scope=? AND a.address=?', (a['scope'], a['address'])).fetchone()
            if not row or row['state'] != 'active' or actor not in json.loads(row['acl']):
                raise Rejected('read unavailable or denied')
            item = self._load_bundle(row['bundle'])
            self._fresh(item['manifest'])
            return dict(cell=row['id'], owner=row['owner'], epoch=row['epoch'], acl=json.loads(row['acl']),
                        bundle=item)
        raise Rejected('unknown operation')

    def _record_rejection(self, request, fingerprint, reason):
        self.db.execute('INSERT OR IGNORE INTO request_bindings VALUES (?,?)', (request['request_id'], fingerprint))
        prior = self.db.execute('SELECT response FROM rejections WHERE command_hash=?', (fingerprint,)).fetchone()
        if prior:
            return json.loads(prior[0])
        payload = dict(domain=DOMAIN, authority=self.identity, request_id=request['request_id'],
                       command_hash=fingerprint, outcome='rejected', reason=reason[:256])
        receipt = dict(payload, signature=self.key.sign(canonical(payload)).hex())
        self.db.execute('INSERT INTO rejections VALUES (?,?,?,?)', (fingerprint, request['request_id'],
                        canonical(receipt).decode(), canonical(request).decode()))
        return receipt

    def apply(self, request, boundary_hook=None):
        """boundary_hook(before_commit|after_commit) is trusted fault-test instrumentation."""
        request = json.loads(canonical(request))
        verify(request, self.identity)
        fingerprint = digest(canonical(request))
        read = request['operation'] in ('read', 'status')
        committed = False
        self.db.execute('BEGIN IMMEDIATE')
        self.db.execute('SAVEPOINT mutation')
        try:
            self.db.execute('INSERT OR IGNORE INTO request_bindings VALUES (?,?)', (request['request_id'], fingerprint))
            bound = self.db.execute('SELECT command_hash FROM request_bindings WHERE id=?', (request['request_id'],)).fetchone()[0]
            if bound != fingerprint:
                raise Rejected('idempotency key reused for another request')
            prior = self.db.execute('SELECT * FROM receipts WHERE id=?', (request['request_id'],)).fetchone()
            if prior:
                if prior['command_hash'] != fingerprint:
                    raise Rejected('idempotency key reused for another request')
                receipt = json.loads(prior['response'])
                self.db.rollback()
                return receipt
            refusal = self.db.execute('SELECT response FROM rejections WHERE command_hash=?', (fingerprint,)).fetchone()
            if refusal:
                receipt = json.loads(refusal[0])
                raise Rejected(receipt['reason'], receipt)
            result = self._dispatch(request['operation'], request['args'], request['actor'])
            payload = dict(domain=DOMAIN, authority=self.identity, request_id=request['request_id'], command_hash=fingerprint, result=result)
            receipt = dict(payload, signature=self.key.sign(canonical(payload)).hex())
            if not read:
                self.db.execute('INSERT INTO receipts VALUES (?,?,?,?)', (request['request_id'], fingerprint, canonical(receipt).decode(), canonical(request).decode()))
            if boundary_hook:
                boundary_hook('before_commit')
            self.db.commit()
            committed = True
            if boundary_hook:
                boundary_hook('after_commit')
            return receipt
        except BaseException as exc:
            if not committed and isinstance(exc, (Rejected, KeyError, sqlite3.IntegrityError, TypeError, ValueError, AttributeError)):
                reason = str(exc) if isinstance(exc, Rejected) else 'invalid operation or uniqueness conflict'
                self.db.execute('ROLLBACK TO mutation')
                self.db.execute('RELEASE mutation')
                try:
                    receipt = self._record_rejection(request, fingerprint, reason)
                    self.db.commit()
                except BaseException:
                    self.db.rollback()
                    raise
                raise Rejected(reason, receipt) from exc
            self.db.rollback()
            raise
