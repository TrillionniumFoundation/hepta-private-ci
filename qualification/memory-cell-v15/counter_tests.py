"""SQLite integer exhaustion controls; direct DB setup models an imported snapshot."""
from authority_tests import AuthorityTests
from authority import MAX_COUNTER, Rejected, public, sign
from authority_tests import key


class CounterTests(AuthorityTests):
    # Inherit fixture setup only; discovery selects this subclass's cases below.
    def test_exhausted_epoch_rejects_without_real_promotion(self):
        self.a.db.execute("UPDATE cells SET epoch=? WHERE id='cell'", (MAX_COUNTER,))
        request = sign(key(3), self.a.identity, 'restrict',
                       dict(cell='cell', epoch=MAX_COUNTER, expected=self.item['id'], acl=[]), 'exhausted')
        for _ in range(2):
            with self.assertRaises(Rejected) as caught:
                self.a.apply(request)
            self.assertEqual(caught.exception.receipt['outcome'], 'rejected')
        self.assertEqual(tuple(self.a.db.execute('SELECT epoch,typeof(epoch) FROM cells').fetchone()),
                         (MAX_COUNTER, 'integer'))

    def test_prepare_reserves_commit_and_abort_epoch(self):
        self.a.db.execute("UPDATE cells SET epoch=? WHERE id='cell'", (MAX_COUNTER-1,))
        with self.assertRaisesRegex(Rejected, 'counter exhausted'):
            self.call('prepare', dict(cell='cell', epoch=MAX_COUNTER-1, expected=self.item['id'],
                                     transfer='too-late', target=public(key(4))))
        self.assertEqual(self.a.db.execute('SELECT COUNT(*) FROM transfers').fetchone()[0], 0)
        self.assertEqual(tuple(self.a.db.execute('SELECT epoch,state FROM cells').fetchone()),
                         (MAX_COUNTER-1, 'active'))

    def test_last_legal_transfer_can_commit(self):
        self.a.db.execute("UPDATE cells SET epoch=? WHERE id='cell'", (MAX_COUNTER-2,))
        self.call('prepare', dict(cell='cell', epoch=MAX_COUNTER-2, expected=self.item['id'],
                                 transfer='last', target=public(key(4))))
        args = dict(cell='cell', epoch=MAX_COUNTER-1, expected=self.item['id'], transfer='last')
        self.call('ready', dict(args, bundle=self.item), 4)
        self.call('commit', args, 4)
        self.assertEqual(tuple(self.a.db.execute('SELECT epoch,typeof(epoch),owner,state FROM cells').fetchone()),
                         (MAX_COUNTER, 'integer', public(key(4)), 'active'))

    def test_exhausted_source_revision_keeps_signed_rejection(self):
        self.a.db.execute("UPDATE sources SET revision=?", (MAX_COUNTER,))
        with self.assertRaises(Rejected) as caught:
            self.call('source', dict(scope='scope', id='s', expected_revision=MAX_COUNTER,
                                     active=False, body='revoked'), 2)
        self.assertEqual(caught.exception.receipt['outcome'], 'rejected')
        self.assertEqual(tuple(self.a.db.execute('SELECT revision,typeof(revision),active FROM sources').fetchone()),
                         (MAX_COUNTER, 'integer', 1))


# Do not duplicate the base class's original 22 cases in the reported count.
def load_tests(loader, tests, pattern):
    import unittest
    return unittest.TestSuite(CounterTests(name) for name in CounterTests.__dict__ if name.startswith('test_'))
