"""Identifier admission must preserve handoff liveness, including legacy DB opens."""
import copy
import sqlite3
import unittest

from authority import Rejected, public
from authority_tests import AuthorityTests, authority, key


class IdentifierTests(AuthorityTests):
    def state(self):
        return {table: [tuple(row) for row in self.a.db.execute('SELECT * FROM ' + table)]
                for table in ('sources', 'source_history', 'objects', 'bundles', 'cells',
                              'addresses', 'transfers', 'recovery_transfers')}

    def invalid(self, kind):
        limit = 256 if kind == 'cell' else 128
        return [None, False, True, 0, 1, [], {}, '', '\ud800', 'x' * (limit + 1),
                'é' * (limit // 2 + 1), '🙂' * (limit // 4 + 1)]

    def refuse(self, operation, args, actor, kind):
        before = self.state()
        with self.assertRaisesRegex(Rejected, 'invalid ' + kind + ' identifier'):
            self.call(operation, args, actor)
        self.assertEqual(self.state(), before)

    def test_all_cell_entrypoints_reject_missing_and_invalid_ids(self):
        for operation in ('create', 'publish', 'prepare', 'recover_prepare', 'restrict',
                          'ready', 'commit', 'abort', 'status'):
            actor = 2 if operation in ('create', 'recover_prepare') else 3
            args = dict(cell='cell', epoch=1, expected=self.item['id'], bundle=self.item,
                        owner=public(key(3)), target=public(key(4)), transfer='valid', acl=[])
            for value in self.invalid('cell'):
                with self.subTest(operation=operation, value=value):
                    self.refuse(operation, dict(args, cell=value), actor, 'cell')
            del args['cell']
            self.refuse(operation, args, actor, 'cell')

    def test_bad_prepare_preserves_normal_abort_and_commit_paths(self):
        args = dict(cell='cell', epoch=1, expected=self.item['id'], target=public(key(4)))
        for operation, actor in (('prepare', 3), ('recover_prepare', 2)):
            for value in self.invalid('transfer'):
                with self.subTest(operation=operation, value=value):
                    self.refuse(operation, dict(args, transfer=value), actor, 'transfer')
            self.refuse(operation, args, actor, 'transfer')
        self.call('prepare', dict(args, transfer='abortable'))
        self.call('abort', dict(cell='cell', epoch=2, expected=self.item['id'], transfer='abortable'))
        self.call('prepare', dict(args, epoch=3, transfer='committable'))
        current = dict(cell='cell', epoch=4, expected=self.item['id'], transfer='committable')
        self.call('ready', dict(current, bundle=self.item), 4)
        self.call('commit', current, 4)
        self.assertEqual(tuple(self.a.db.execute('SELECT owner,epoch,state FROM cells').fetchone()),
                         (public(key(4)), 5, 'active'))

    def test_bad_terminal_identifiers_preserve_pending_transfer(self):
        self.prepare()
        args = self.transfer_args()
        for operation, actor in (('ready', 4), ('commit', 4), ('abort', 3)):
            for value in self.invalid('transfer'):
                with self.subTest(operation=operation, value=value):
                    self.refuse(operation, dict(args, transfer=value, bundle=self.item), actor, 'transfer')
            missing = dict(args, bundle=self.item)
            del missing['transfer']
            self.refuse(operation, missing, actor, 'transfer')
        self.call('ready', dict(args, bundle=self.item), 4)
        self.call('commit', args, 4)
        self.assertEqual(self.call('status', {'cell': 'cell'}, 4)['cell']['state'], 'active')

    def test_reshape_validates_all_child_and_parent_identifiers_before_retirement(self):
        args = dict(parents=[dict(cell='cell', epoch=1, expected=self.item['id'])],
                    children=[dict(cell='child', bundle=self.item)])
        for side in ('parents', 'children'):
            for value in self.invalid('cell'):
                with self.subTest(side=side, value=value):
                    invalid = copy.deepcopy(args)
                    invalid[side][0]['cell'] = value
                    self.refuse('reshape', invalid, 3, 'cell')
            missing = copy.deepcopy(args)
            del missing[side][0]['cell']
            self.refuse('reshape', missing, 3, 'cell')
        self.call('reshape', args)
        self.assertEqual(self.call('status', {'cell': 'cell'})['cell']['state'], 'retired')
        self.assertEqual(self.call('status', {'cell': 'child'})['cell']['state'], 'active')

    def test_valid_utf8_byte_boundaries_survive_cold_reopen_and_handoff(self):
        for index, (cell, transfer) in enumerate((('a' * 256, 't' * 128),
                                                 ('界' * 85 + 'a', '🙂' * 32),
                                                 ('é' * 128, '界' * 42 + 'ab'))):
            item = self.item_for(addresses=('unicode-' + str(index),))
            self.call('create', dict(cell=cell, owner=public(key(3)), bundle=item), 2)
            self.call('prepare', dict(cell=cell, epoch=1, expected=item['id'],
                                      target=public(key(4)), transfer=transfer))
            self.a.close()
            self.a = authority(self.path)
            current = dict(cell=cell, epoch=2, expected=item['id'], transfer=transfer)
            self.call('ready', dict(current, bundle=item), 4)
            self.call('commit', current, 4)
            read = self.call('read', dict(scope='scope', address='unicode-' + str(index)))
            self.assertEqual((read['cell'], read['owner'], read['epoch']), (cell, public(key(4)), 3))

    def test_identifiers_are_exact_not_unicode_normalized(self):
        for cell, address in (('é', 'composed'), ('e\u0301', 'decomposed')):
            item = self.item_for(addresses=(address,))
            self.call('create', dict(cell=cell, owner=public(key(3)), bundle=item), 2)
            self.assertEqual(self.call('read', dict(scope='scope', address=address))['cell'], cell)
        self.a.close()
        self.a = authority(self.path)
        self.assertNotEqual(self.call('status', {'cell': 'é'}), self.call('status', {'cell': 'e\u0301'}))

    def test_corrupt_legacy_identifiers_require_recovery_without_state_repair(self):
        self.call('recover_prepare', dict(cell='cell', epoch=1, expected=self.item['id'],
                                          transfer='recovery', target=public(key(4))), 2)
        for table, column, kind in (('cells', 'id', 'cell'), ('addresses', 'cell', 'cell'),
                                    ('transfers', 'id', 'transfer'), ('transfers', 'cell', 'cell'),
                                    ('recovery_transfers', 'id', 'transfer')):
            for index, value in enumerate((None, '', 'x' * (257 if kind == 'cell' else 129))):
                with self.subTest(table=table, column=column, value=value):
                    path = self.path + '.' + table + '.' + column + str(index)
                    with sqlite3.connect(path) as poisoned:
                        self.a.db.backup(poisoned)
                        poisoned.execute('UPDATE ' + table + ' SET ' + column + '=?', (value,))
                        poisoned.commit()
                        before = list(poisoned.iterdump())
                        with self.assertRaisesRegex(Rejected, 'recovery required: invalid persisted'):
                            authority(path)
                        self.assertEqual(list(poisoned.iterdump()), before)
        args = dict(cell='cell', epoch=2, expected=self.item['id'], transfer='recovery')
        self.call('abort', args, 2)
        self.assertEqual(self.call('status', {'cell': 'cell'})['cell']['state'], 'active')


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(IdentifierTests(name) for name in IdentifierTests.__dict__
                              if name.startswith('test_'))
