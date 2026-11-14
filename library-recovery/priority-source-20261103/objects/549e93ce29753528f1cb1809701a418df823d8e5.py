"""Contract-level state model only; the product owner API is not implemented."""
import asyncio
import weakref
import unittest

class Denied(Exception):pass
class Busy(Exception):pass
class Owner:
    def __init__(self, mode='exclusive'):
        self.mode=mode;self.phase='open';self.pending=set();self.active=set()
        self.mutating={};self.terminal=set();self.durable_unknown=set();self.close_db_started=False
    def reserve(self, operation):
        if self.mode!='exclusive' or self.phase!='open' or operation in self.mutating:
            raise Denied()
        if operation in self.pending or operation in self.active:raise Busy()
        self.pending.add(operation)
        return Guard(self,operation,'pending')
    def close_begin(self):
        if self.pending or self.active or self.mutating:raise Busy()
        if self.phase!='open':raise Denied()
        self.phase='closing'
    def terminal_begin(self, operation):
        if self.phase!='open':raise Denied()
        if operation in self.pending or operation in self.active or operation in self.mutating:raise Busy()
        self.mutating[operation]='reserved'
    def terminal_finish(self,operation):
        self.mutating.pop(operation);self.terminal.add(operation)
    def terminal_db_start(self,operation):self.mutating[operation]='db_attempted'
    def terminal_cancel_before_db(self,operation):
        if self.mutating[operation]!='reserved':raise Denied()
        self.mutating.pop(operation)
    def close_db_start(self):
        assert self.phase=='closing';self.close_db_started=True
    def close_cancel_before_db(self):
        if self.phase!='closing' or self.close_db_started:raise Denied()
        self.phase='open'

class Guard:
    def __init__(self,owner,operation,phase):self.owner=owner;self.operation=operation;self.phase=phase
    def activate(self):
        assert self.phase=='pending' and self.owner.phase=='open'
        # terminal models fresh durable state, not an in-memory gate tombstone.
        if self.operation in self.owner.terminal:raise Denied()
        self.owner.pending.remove(self.operation);self.owner.active.add(self.operation);self.phase='active'
    def drop(self):
        if self.phase=='pending':self.owner.pending.remove(self.operation)
        elif self.phase=='active':self.owner.active.remove(self.operation)
        self.phase='dropped';self.owner=None

class Capability:
    def __init__(self,owner,operation):self.owner=weakref.ref(owner);self.operation=operation;self.consumed=False
    def enter(self):
        if self.consumed:raise Denied()
        self.consumed=True;owner=self.owner()
        if owner is None:raise Denied()
        return owner.reserve(self.operation)

class EntryDesignTests(unittest.TestCase):
    def test_close_wins_before_entry_zero_provider_calls(self):
        owner=Owner();cap=Capability(owner,'op');owner.close_begin()
        with self.assertRaises(Denied):cap.enter()
        self.assertFalse(owner.pending or owner.active)
    def test_pending_validation_excludes_close_and_matching_terminal(self):
        owner=Owner();guard=Capability(owner,'op').enter()
        with self.assertRaises(Busy):owner.close_begin()
        with self.assertRaises(Busy):owner.terminal_begin('op')
        guard.activate()
        with self.assertRaises(Busy):owner.close_begin()
        guard.drop();owner.close_begin()
    def test_unrelated_terminal_progresses_during_active_entry(self):
        owner=Owner();guard=Capability(owner,'a').enter();guard.activate()
        owner.terminal_begin('b');owner.terminal_finish('b')
        self.assertEqual(owner.terminal,{'b'});self.assertEqual(owner.active,{'a'})
        guard.drop()
    def test_issued_unused_capability_does_not_pin_closed_owner(self):
        owner=Owner();cap=Capability(owner,'op');reference=weakref.ref(owner)
        owner.close_begin();owner.phase='closed';del owner
        self.assertIsNone(reference())
        with self.assertRaises(Denied):cap.enter()
    def test_pending_guard_keeps_owner_alive_for_validation(self):
        owner=Owner();reference=weakref.ref(owner);guard=Capability(owner,'op').enter()
        del owner;self.assertIsNotNone(reference());guard.drop();self.assertIsNone(reference())
    def test_shared_qualification_or_readonly_owner_cannot_enter(self):
        for mode in ['shared-qualification','readonly']:
            owner=Owner(mode);cap=Capability(owner,'op')
            with self.assertRaises(Denied):cap.enter()
            self.assertFalse(owner.pending or owner.active)
    def test_matching_terminal_wins_before_entry(self):
        owner=Owner();cap=Capability(owner,'op');owner.terminal_begin('op')
        with self.assertRaises(Denied):cap.enter()
        owner.terminal_finish('op');self.assertEqual(owner.terminal,{'op'})

    def test_completed_terminal_slot_reuse_still_rejects_stale_entry(self):
        owner=Owner();cap=Capability(owner,'op')
        owner.terminal_begin('op');owner.terminal_finish('op')
        self.assertFalse(owner.mutating)
        guard=cap.enter()
        self.assertEqual(owner.pending,{'op'})
        with self.assertRaises(Denied):guard.activate()
        guard.drop()
        self.assertFalse(owner.pending or owner.active)

    def test_duplicate_terminal_reservation_cannot_remove_another_inflight_marker(self):
        owner=Owner();owner.terminal_begin('op')
        with self.assertRaises(Busy):owner.terminal_begin('op')
        with self.assertRaises(Busy):owner.close_begin()
        owner.terminal_finish('op');owner.close_begin()
    def test_known_pre_database_cancellation_releases_terminal_and_close_reservations(self):
        owner=Owner();owner.terminal_begin('op');owner.terminal_cancel_before_db('op')
        owner.close_begin();owner.close_cancel_before_db()
        guard=Capability(owner,'op').enter();guard.drop()
    def test_unknown_database_outcome_never_automatically_reopens_entry(self):
        owner=Owner();owner.terminal_begin('op');owner.terminal_db_start('op')
        with self.assertRaises(Denied):owner.terminal_cancel_before_db('op')
        with self.assertRaises(Denied):Capability(owner,'op').enter()
        with self.assertRaises(Busy):owner.close_begin()
        other=Owner();other.close_begin();other.close_db_start()
        with self.assertRaises(Denied):other.close_cancel_before_db()
        with self.assertRaises(Denied):Capability(other,'op').enter()

class EntryCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_pending_releases_slot_but_never_requeues_unknown_effect(self):
        owner=Owner();owner.durable_unknown.add('op');cap=Capability(owner,'op');entered=asyncio.Event()
        async def validation():
            guard=cap.enter()
            try:entered.set();await asyncio.Future()
            finally:guard.drop()
        task=asyncio.create_task(validation());await entered.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        owner.close_begin();self.assertEqual(owner.durable_unknown,{'op'})
        with self.assertRaises(Denied):cap.enter()

if __name__=='__main__':unittest.main(verbosity=2)
