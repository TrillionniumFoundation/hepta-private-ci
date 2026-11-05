"""Behavior tests; fixture admission is NOT evidence of language-model benefit.

All worker processes run on one physical machine. Crash tests use actual OS kill.
Receiver stages are real fsynced files, but no physical remote disk is involved.
Both fixture gates explicitly approve protocol fixtures, not measured net benefit.
"""

import copy
import json
import multiprocessing as mp
import os
import pathlib
import tempfile
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from authority import Authority, COMPONENTS, GateDecision, StructureDecision, Rejected, bundle, canonical, digest, public, sign


def key(number):
    return Ed25519PrivateKey.from_private_bytes(bytes([number]) * 32)


def fixture_gate(candidate, parents, manifest, verified):
    return GateDecision(candidate, parents, manifest['components']['model'] != digest(b'negative'),
                        digest(b'protocol-test-fixture-no-language-evidence'))


def fixture_structure_gate(plan_id, plan, verified):
    return StructureDecision(plan_id, True, digest(b'whole-plan-protocol-fixture-not-economic-evidence'))


def authority(path, evaluator=fixture_gate, structure_evaluator=fixture_structure_gate):
    return Authority(path, key(1), public(key(2)), evaluator, structure_evaluator)


def mutate_worker(path, number, operation, args, barrier, queue, request_id=None):
    a = authority(path)
    barrier.wait(timeout=15)
    try:
        result = a.apply(sign(key(number), a.identity, operation, args, request_id))
        queue.put(('ok', result['result']))
    except Rejected as exc:
        queue.put(('rejected', str(exc)))
    finally:
        a.close()


def killed_worker(path, request, target_boundary, pipe):
    a = authority(path)
    def hook(boundary):
        if boundary == target_boundary:
            pipe.send(boundary)
            pipe.recv()
    a.apply(request, hook)


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(pathlib.Path(self.temp.name) / 'authority.db')
        self.a = authority(self.path)
        self.source = self.call('source', dict(scope='scope', id='s', expected_revision=0,
                                              active=True, body='authoritative source'), 2)
        self.item = self.item_for()
        self.call('create', dict(cell='cell', owner=public(key(3)), bundle=self.item), 2)

    def tearDown(self):
        self.a.close()
        self.temp.cleanup()

    def call(self, op, args, signer=3):
        return self.a.apply(sign(key(signer), self.a.identity, op, args))['result']

    def item_for(self, model=b'model-v1', addresses=('one', 'two'), acl=None, sources=None):
        dependency = dict(id='s', revision=self.source['revision'], hash=self.source['hash'])
        return bundle('scope', addresses, acl if acl is not None else [public(key(3)), public(key(4)), public(key(5))],
                      sources if sources is not None else [dependency],
                      {name: model if name == 'model' else name.encode() for name in COMPONENTS})

    def update(self, item, epoch=1, expected=None):
        return dict(cell='cell', epoch=epoch, expected=expected or self.item['id'], bundle=item)

    def prepare(self):
        return self.call('prepare', dict(cell='cell', epoch=1, expected=self.item['id'],
                                         transfer='transfer', target=public(key(4))))

    def transfer_args(self):
        return dict(transfer='transfer', cell='cell', epoch=2, expected=self.item['id'])

    def ready(self):
        # An actual local receiver stage, read back only after fsync and rename.
        target = pathlib.Path(self.temp.name) / 'receiver.bundle.json'
        temporary = target.with_suffix('.tmp')
        with temporary.open('wb') as stream:
            stream.write(canonical(self.item))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        if os.name == 'posix':
            descriptor = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        item = json.loads(target.read_bytes())
        return self.call('ready', dict(self.transfer_args(), bundle=item), 4)

    def test_signed_receipt_and_tampered_command(self):
        request = sign(key(3), self.a.identity, 'read', dict(scope='scope', address='one'))
        receipt = self.a.apply(request)
        payload = {k: v for k, v in receipt.items() if k != 'signature'}
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.a.identity)).verify(
            bytes.fromhex(receipt['signature']), canonical(payload))
        request['args']['address'] = 'two'
        with self.assertRaisesRegex(Rejected, 'signed'):
            self.a.apply(request)
        with self.assertRaisesRegex(Rejected, 'owner'):
            self.call('publish', self.update(self.item_for(b'v2')), 4)

    def test_bundle_bytes_and_lineage_verified(self):
        broken = copy.deepcopy(self.item)
        broken['objects']['model'] = b'corrupted'.hex()
        with self.assertRaises(Rejected):
            self.call('publish', self.update(broken))
        with self.assertRaisesRegex(Rejected, 'lineage'):
            self.call('publish', self.update(self.item_for(b'v2', sources=[])))
        self.assertEqual(self.call('read', dict(scope='scope', address='one'))['epoch'], 1)

    def test_quality_cannot_be_client_approval(self):
        with self.assertRaisesRegex(Rejected, 'quality'):
            self.call('publish', dict(self.update(self.item_for(b'negative')), approved=True))
        self.a.evaluator = lambda c, p, m, v: {'approved': True, 'candidate_id': c, 'parent_ids': p}
        with self.assertRaisesRegex(Rejected, 'quality'):
            self.call('publish', self.update(self.item_for(b'v2')))

    def test_two_actual_processes_compete_for_same_epoch(self):
        ctx = mp.get_context('spawn')
        barrier, queue = ctx.Barrier(3), ctx.Queue()
        workers = [ctx.Process(target=mutate_worker, args=(self.path, 3, 'publish',
                   self.update(self.item_for(f'candidate-{i}'.encode())), barrier, queue)) for i in range(2)]
        for worker in workers:
            worker.start()
        barrier.wait(timeout=15)
        results = [queue.get(timeout=20) for _ in workers]
        for worker in workers:
            worker.join(timeout=10)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(sorted(r[0] for r in results), ['ok', 'rejected'])
        self.assertEqual(self.call('read', dict(scope='scope', address='one'))['epoch'], 2)

    def test_migration_cold_restart_and_old_owner_fenced(self):
        self.prepare()
        self.a.close()
        self.a = authority(self.path)
        self.assertEqual(self.call('status', {'cell': 'cell'}, 4)['transfers'][0]['state'], 'prepared')
        with self.assertRaisesRegex(Rejected, 'frozen'):
            self.call('publish', self.update(self.item_for(b'v2'), 2))
        self.ready()
        self.a.close()
        self.a = authority(self.path)
        result = self.call('commit', self.transfer_args(), 4)
        self.assertEqual((result['owner'], result['epoch']), (public(key(4)), 3))
        with self.assertRaisesRegex(Rejected, 'owner'):
            self.call('publish', self.update(self.item_for(b'v2'), 3))
        self.call('publish', self.update(self.item_for(b'v2'), 3), 4)
        self.a.close()
        self.a = authority(self.path)
        self.assertEqual(self.call('status', {'cell': 'cell'}, 4)['transfers'][0]['state'], 'committed')

    def test_ready_requires_exact_bytes_and_receiver_identity(self):
        self.prepare()
        with self.assertRaises(Rejected):
            self.call('ready', dict(self.transfer_args(), bundle=self.item), 3)
        broken = copy.deepcopy(self.item)
        broken['objects']['memory'] = '00'
        with self.assertRaises(Rejected):
            self.call('ready', dict(self.transfer_args(), bundle=broken), 4)
        self.assertEqual(self.call('status', {'cell': 'cell'})['transfers'][0]['state'], 'prepared')

    def test_source_update_after_ready_blocks_commit(self):
        self.prepare()
        self.ready()
        self.call('source', dict(scope='scope', id='s', expected_revision=1, active=False, body='revoked'), 2)
        with self.assertRaisesRegex(Rejected, 'source'):
            self.call('commit', self.transfer_args(), 4)
        self.call('abort', self.transfer_args())
        with self.assertRaisesRegex(Rejected, 'source'):
            self.call('read', dict(scope='scope', address='one'))

    def test_rollback_new_epoch_and_no_permission_or_source_rollback(self):
        newer = self.item_for(b'v2')
        self.call('publish', self.update(newer))
        result = self.call('publish', self.update(self.item, 2, newer['id']))
        self.assertEqual(result['epoch'], 3)
        self.call('restrict', dict(cell='cell', epoch=3, expected=self.item['id'], acl=[public(key(3))]))
        with self.assertRaisesRegex(Rejected, 'permission'):
            self.call('publish', self.update(self.item, 4))
        with self.assertRaises(Rejected):
            self.call('read', dict(scope='scope', address='one'), 5)
        self.call('source', dict(scope='scope', id='s', expected_revision=1, active=False, body='revoked'), 2)
        narrowed = self.item_for(acl=[public(key(3))])
        with self.assertRaisesRegex(Rejected, 'source'):
            self.call('publish', self.update(narrowed, 4))

    def test_unrelated_source_update_does_not_stale_cell(self):
        self.call('source', dict(scope='scope', id='other', expected_revision=0, active=True, body='unrelated'), 2)
        self.assertEqual(self.call('read', dict(scope='scope', address='one'))['epoch'], 1)

    def test_atomic_split_merge_and_owner_exclusion(self):
        left, right = self.item_for(addresses=('one',)), self.item_for(addresses=('two',))
        parents = [dict(cell='cell', epoch=1, expected=self.item['id'])]
        children = [dict(cell='left', bundle=left), dict(cell='right', bundle=right)]
        self.call('reshape', dict(parents=parents, children=children))
        with self.assertRaisesRegex(Rejected, 'retired'):
            self.call('publish', self.update(self.item, 2))
        self.assertEqual(self.call('read', dict(scope='scope', address='one'))['cell'], 'left')
        self.call('reshape', dict(parents=[dict(cell='left', epoch=1, expected=left['id']),
                                          dict(cell='right', epoch=1, expected=right['id'])],
                                 children=[dict(cell='merged', bundle=self.item)]))
        self.assertEqual(self.call('read', dict(scope='scope', address='two'))['cell'], 'merged')

    def test_failed_reshape_restores_all_addresses(self):
        duplicate = self.item_for(addresses=('one',))
        with self.assertRaises(Rejected):
            self.call('reshape', dict(parents=[dict(cell='cell', epoch=1, expected=self.item['id'])],
                                     children=[dict(cell='left', bundle=duplicate), dict(cell='right', bundle=duplicate)]))
        self.assertEqual(self.call('read', dict(scope='scope', address='two'))['cell'], 'cell')

    def test_receipt_replay_never_reapplies_mutation(self):
        request = sign(key(3), self.a.identity, 'publish', self.update(self.item_for(b'v2')), 'retry')
        first = self.a.apply(request)
        self.assertEqual(first, self.a.apply(request))
        changed = sign(key(3), self.a.identity, 'publish', self.update(self.item_for(b'other')), 'retry')
        with self.assertRaisesRegex(Rejected, 'idempotency'):
            self.a.apply(changed)
        self.assertEqual(self.call('read', dict(scope='scope', address='one'))['epoch'], 2)

    @unittest.skipUnless(os.name == 'posix', 'actual POSIX process-kill boundary test')
    def test_kill_before_and_after_commit_then_reconcile_same_request(self):
        ctx = mp.get_context('spawn')
        for boundary, expected_epoch in [('before_commit', 1), ('after_commit', 2)]:
            with self.subTest(boundary=boundary):
                item = self.item_for(b'crash-candidate')
                request = sign(key(3), self.a.identity, 'publish', self.update(item), 'crash-' + boundary)
                receiver, sender = ctx.Pipe()
                worker = ctx.Process(target=killed_worker, args=(self.path, request, boundary, sender))
                worker.start()
                self.assertTrue(receiver.poll(20), 'worker did not reach transaction boundary')
                self.assertEqual(receiver.recv(), boundary)
                worker.kill()
                worker.join(timeout=10)
                self.assertLess(worker.exitcode, 0)
                self.a.close()
                self.a = authority(self.path)
                self.assertEqual(self.call('status', {'cell': 'cell'})['cell']['epoch'], expected_epoch)
                if boundary == 'after_commit':
                    self.assertEqual(self.a.apply(request)['result']['epoch'], 2)
                receiver.close()
                sender.close()

    def test_corrupted_persisted_object_is_rejected(self):
        self.a.db.execute('UPDATE objects SET data=? WHERE hash=?', (b'broken', self.item['manifest']['components']['model']))
        with self.assertRaisesRegex(Rejected, 'corrupted'):
            self.call('read', dict(scope='scope', address='one'))

    def test_wrong_service_identity_cannot_reopen_authority(self):
        with self.assertRaisesRegex(Rejected, 'identity'):
            Authority(self.path, key(8), public(key(2)), fixture_gate)

    def test_verified_bytes_are_immutable_and_manifest_isolated(self):
        candidate = self.item_for(b'v2')
        def gate(identifier, parents, manifest, verified):
            self.assertEqual(verified['model'], b'v2')
            with self.assertRaises(TypeError):
                verified['model'] = b'changed'
            manifest['sources'][0]['revision'] = 999
            return GateDecision(identifier, parents, True, digest(b'fixture'))
        self.a.evaluator = gate
        with self.assertRaisesRegex(Rejected, 'manifest changed'):
            self.call('publish', self.update(candidate))
        self.assertEqual(candidate['manifest']['sources'][0]['revision'], 1)
        self.assertEqual(self.call('status', {'cell': 'cell'})['cell']['epoch'], 1)

    def test_last_reader_revoke_keeps_owner_repair_path(self):
        self.call('restrict', dict(cell='cell', epoch=1, expected=self.item['id'], acl=[]))
        for actor in (3, 4, 5):
            with self.assertRaises(Rejected):
                self.call('read', dict(scope='scope', address='one'), actor)
        self.assertEqual(json.loads(self.call('status', {'cell': 'cell'})['cell']['acl']), [])
        narrowed = self.item_for(acl=[])
        self.call('publish', self.update(narrowed, 2))
        with self.assertRaisesRegex(Rejected, 'permission'):
            self.call('publish', self.update(self.item, 3, narrowed['id']))

    def test_complete_plan_gate_missing_or_misbound_refuses_reshape(self):
        args = dict(parents=[dict(cell='cell', epoch=1, expected=self.item['id'])],
                    children=[dict(cell='left', bundle=self.item_for(addresses=('one',))),
                              dict(cell='right', bundle=self.item_for(addresses=('two',)))], approved=True)
        self.a.structure_evaluator = None
        with self.assertRaisesRegex(Rejected, 'structure'):
            self.call('reshape', args)
        self.a.structure_evaluator = lambda p, plan, data: StructureDecision('0' * 64, True, digest(b'fixture'))
        with self.assertRaisesRegex(Rejected, 'structure'):
            self.call('reshape', args)
        self.assertEqual(self.call('read', dict(scope='scope', address='two'))['cell'], 'cell')

    def test_admin_recovers_absent_owner_without_old_owner_abort(self):
        args = dict(cell='cell', epoch=1, expected=self.item['id'], transfer='transfer', target=public(key(4)))
        with self.assertRaisesRegex(Rejected, 'admin'):
            self.call('recover_prepare', args)
        self.call('recover_prepare', args, 2)
        with self.assertRaisesRegex(Rejected, 'frozen'):
            self.call('publish', self.update(self.item_for(b'v2'), 2))
        with self.assertRaisesRegex(Rejected, 'abort'):
            self.call('abort', self.transfer_args())
        self.a.close()
        self.a = authority(self.path)
        self.ready()
        self.assertEqual(self.call('commit', self.transfer_args(), 4)['owner'], public(key(4)))
        with self.assertRaisesRegex(Rejected, 'owner'):
            self.call('publish', self.update(self.item_for(b'v2'), 3))

    def test_bad_source_types_rejected_without_mutation(self):
        args = dict(scope='scope', id='s', expected_revision=1, body='next', active=True)
        for field in ('scope', 'id', 'body'):
            for value in (None, ''):
                with self.subTest(field=field, value=value), self.assertRaises(Rejected) as failure:
                    self.call('source', dict(args, **{field: value}), 2)
                self.assertEqual(failure.exception.receipt['outcome'], 'rejected')
        self.assertEqual(self.a.db.execute('SELECT revision FROM sources WHERE id=?', ('s',)).fetchone()[0], 1)
        self.assertEqual(self.a.db.execute('SELECT count(*) FROM rejections').fetchone()[0], 6)

    def test_signed_rejections_durable_and_cannot_replace_success(self):
        accepted = sign(key(3), self.a.identity, 'publish', self.update(self.item_for(b'v2')), 'same-id')
        success = self.a.apply(accepted)
        refused = sign(key(3), self.a.identity, 'publish', self.update(self.item_for(b'other')), 'same-id')
        with self.assertRaises(Rejected) as first:
            self.a.apply(refused)
        receipt = first.exception.receipt
        unsigned = {k: v for k, v in receipt.items() if k != 'signature'}
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.a.identity)).verify(
            bytes.fromhex(receipt['signature']), canonical(unsigned))
        self.assertEqual(receipt['command_hash'], digest(canonical(refused)))
        self.a.close()
        self.a = authority(self.path)
        with self.assertRaises(Rejected) as retried:
            self.a.apply(refused)
        self.assertEqual(receipt, retried.exception.receipt)
        self.assertEqual(self.a.apply(accepted), success)
        stored = self.a.db.execute('SELECT signed_request FROM rejections').fetchall()
        self.assertEqual([json.loads(r[0]) for r in stored], [refused])

    def test_two_processes_cannot_rebind_rejected_request_id(self):
        ctx = mp.get_context('spawn')
        barrier, queue = ctx.Barrier(3), ctx.Queue()
        workers = [ctx.Process(target=mutate_worker, args=(self.path, 3, 'publish',
                   self.update(self.item_for(model)), barrier, queue, 'contested-id'))
                   for model in (b'negative', b'positive')]
        for worker in workers:
            worker.start()
        barrier.wait(timeout=15)
        results = [queue.get(timeout=20) for _ in workers]
        for worker in workers:
            worker.join(timeout=10)
            self.assertEqual(worker.exitcode, 0)
        accepted = sum(result[0] == 'ok' for result in results)
        self.assertLessEqual(accepted, 1)
        self.assertEqual(self.call('status', {'cell': 'cell'})['cell']['epoch'], 1 + accepted)
        success = self.a.db.execute('SELECT command_hash FROM receipts WHERE id=?', ('contested-id',)).fetchone()
        refused = {r[0] for r in self.a.db.execute('SELECT command_hash FROM rejections WHERE id=?', ('contested-id',))}
        self.assertEqual(len(refused), 2 - accepted)
        if success:
            self.assertNotIn(success[0], refused)


if __name__ == '__main__':
    unittest.main(verbosity=2)
