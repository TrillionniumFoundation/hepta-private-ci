"""Observe whole-authority rollback on disposable, deterministically keyed fixtures.

Argument: source directory containing authority.py. Databases are created only in
a new TemporaryDirectory; no caller-selected database or production key is used.
Exit zero means observation completed, never that rollback protection passed.
"""
import hashlib
import json
import pathlib
import shutil
import sqlite3
import sys
import tempfile

source = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(source))
from authority import COMPONENTS, Rejected, bundle, canonical, public, sign
from authority_tests import authority, key


def call(service, actor, operation, args, request_id):
    return service.apply(sign(key(actor), service.identity, operation, args, request_id))['result']


def replay(service, request):
    try:
        receipt = service.apply(request)
        outcome = 'accepted'
    except Rejected as exc:
        receipt, outcome = exc.receipt, 'rejected'
    key(1).public_key().verify(bytes.fromhex(receipt['signature']),
        canonical({name: value for name, value in receipt.items() if name != 'signature'}))
    return dict(outcome=outcome, receipt=receipt, fixture_signature_verified=True)


def state(service):
    cell = service.db.execute('SELECT owner,epoch,state FROM cells').fetchone()
    dependency = service.db.execute('SELECT revision,active FROM sources').fetchone()
    return dict(owner=cell['owner'], epoch=cell['epoch'], phase=cell['state'],
                source_revision=dependency['revision'], source_active=bool(dependency['active']))


with tempfile.TemporaryDirectory(prefix='memory-authority-rollback-fixture-') as temporary:
    path, snapshot = pathlib.Path(temporary) / 'authority.db', pathlib.Path(temporary) / 'snapshot.db'
    service = authority(str(path))
    initial = call(service, 2, 'source', dict(scope='scope', id='source', expected_revision=0,
                                            active=True, body='fixture-only fact'), 'source-initial')
    item = bundle('scope', ['address'], [public(key(3)), public(key(4))],
        [dict(id='source', revision=initial['revision'], hash=initial['hash'])],
        {name: name.encode() for name in COMPONENTS})
    call(service, 2, 'create', dict(cell='cell', owner=public(key(3)), bundle=item), 'create')
    stale = dict(read=sign(key(3), service.identity, 'read', dict(scope='scope', address='address'), 'old-read'),
        prepare=sign(key(3), service.identity, 'prepare', dict(cell='cell', epoch=1,
            expected=item['id'], transfer='old-owner-transfer', target=public(key(5))), 'old-prepare'))
    with sqlite3.connect(snapshot) as backup:
        service.db.backup(backup)
    snapshot_digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    call(service, 3, 'prepare', dict(cell='cell', epoch=1, expected=item['id'],
                                    transfer='legitimate-handoff', target=public(key(4))), 'prepare')
    current = dict(cell='cell', epoch=2, expected=item['id'], transfer='legitimate-handoff')
    call(service, 4, 'ready', dict(current, bundle=item), 'ready')
    call(service, 4, 'commit', current, 'commit')
    call(service, 2, 'source', dict(scope='scope', id='source', expected_revision=1,
                                   active=False, body='fixture-only fact revoked'), 'revoke')
    current_state = state(service)
    current_results = {name: replay(service, request) for name, request in stale.items()}
    service.close()
    # Restore the complete state, including receipts/bindings and revocations.
    # Sidecars, if any, are confined to this freshly allocated temporary directory.
    for suffix in ('-wal', '-shm'):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
    shutil.copyfile(snapshot, path)
    restored_bytes_match_snapshot = hashlib.sha256(path.read_bytes()).hexdigest() == snapshot_digest
    service = authority(str(path))  # Same fixture authority/admin keys and identity.
    restored_state = state(service)
    restored_results = {name: replay(service, request) for name, request in stale.items()}
    service.close()

report = dict(schema='hepta.memory.authority-rollback-observation.v1',
    probe_completed=True, guard_qualified=False, production_activation_allowed=False,
    vulnerability_reproduced=all(row['outcome'] == 'rejected' for row in current_results.values())
        and all(row['outcome'] == 'accepted' for row in restored_results.values()),
    authority_sha256=hashlib.sha256((source / 'authority.py').read_bytes()).hexdigest(),
    fixture_source_sha256=hashlib.sha256((source / 'authority_tests.py').read_bytes()).hexdigest(),
    probe_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
    snapshot_sha256=snapshot_digest, restored_bytes_match_snapshot=restored_bytes_match_snapshot,
    current_state=current_state, restored_state_before_replay=restored_state,
    identical_signed_requests=stale, current=current_results, restored=restored_results,
    scope='Known test keys and disposable SQLite only; observation is an unmet rollback-security gate.',
    missing_boundary='No independently retained nonrollbackable frontier or canonical replicated authority.',
    claim_limit='Demonstrates whole-store history loss, not unauthorized control of a live filesystem or production compromise.')
print(json.dumps(report, indent=2))
