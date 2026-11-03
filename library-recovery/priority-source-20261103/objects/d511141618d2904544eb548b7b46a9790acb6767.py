#!/usr/bin/env python3
"""Bao-facing barrier specifications over the co-owner's abstract gate model.

No Rust, CognitiveStore transaction, HTTP request, grant signature or real
provider executes here. These schedules constrain the proposed integration.
"""
import asyncio
import unittest
from owner_entry_design_model import Busy, Capability, Denied, Owner

class AuthorityDenied(Exception):
    pass

class AuthorityFixture:
    def __init__(self):
        self.live = True
        self.claims = 0
        self.deliveries = 0

    def claim(self):
        if not self.live:
            raise AuthorityDenied()
        self.claims += 1

    def deliver(self, consumer):
        if not self.live:
            raise AuthorityDenied()
        self.deliveries += 1
        consumer()

async def ready():
    return None

async def proposed_bao_order(capability, prepare, validate_owner, transport, authority, consumer, trace):
    await prepare()
    guard = capability.enter()
    trace.append('pending')
    try:
        await validate_owner()
        guard.activate()
        trace.append('active')
        authority.claim()
        trace.append('kernel_claim')
        await transport()
        trace.append('response')
        authority.deliver(consumer)
        trace.append('consumer')
    finally:
        guard.drop()
        trace.append('drop')

class BaoEntryOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_close_during_authbus_preparation_denies_before_provider(self):
        owner = Owner(); owner.durable_unknown.add('op')
        capability = Capability(owner, 'op'); authority = AuthorityFixture()
        preparing = asyncio.Event(); continue_prepare = asyncio.Event(); trace = []; calls = []
        async def prepare():
            preparing.set(); await continue_prepare.wait()
        async def transport():
            calls.append('provider')
        task = asyncio.create_task(proposed_bao_order(capability, prepare, ready, transport, authority, lambda: calls.append('consumer'), trace))
        await preparing.wait(); owner.close_begin(); continue_prepare.set()
        with self.assertRaises(Denied): await task
        self.assertEqual(calls, []); self.assertEqual(authority.claims, 0)
        self.assertEqual(owner.durable_unknown, {'op'})

    async def test_pending_validation_excludes_close_until_successful_entry(self):
        owner = Owner(); capability = Capability(owner, 'op'); authority = AuthorityFixture()
        validating = asyncio.Event(); finish_validation = asyncio.Event(); trace = []; calls = []
        async def validate():
            validating.set(); await finish_validation.wait()
        async def transport():
            calls.append('provider')
        task = asyncio.create_task(proposed_bao_order(capability, ready, validate, transport, authority, lambda: calls.append('consumer'), trace))
        await validating.wait()
        with self.assertRaises(Busy): owner.close_begin()
        with self.assertRaises(Busy): owner.terminal_begin('op')
        self.assertEqual(calls, []); self.assertEqual(authority.claims, 0)
        finish_validation.set(); await task
        self.assertEqual(trace, ['pending', 'active', 'kernel_claim', 'response', 'consumer', 'drop'])
        self.assertEqual(calls, ['provider', 'consumer'])

    async def test_cancel_during_validation_releases_pending_without_retry_authority(self):
        owner = Owner(); owner.durable_unknown.add('op')
        capability = Capability(owner, 'op'); authority = AuthorityFixture(); validating = asyncio.Event(); trace = []
        async def validate():
            validating.set(); await asyncio.Future()
        task = asyncio.create_task(proposed_bao_order(capability, ready, validate, ready, authority, lambda: None, trace))
        await validating.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        owner.close_begin()
        self.assertEqual(owner.durable_unknown, {'op'}); self.assertEqual(authority.claims, 0)
        with self.assertRaises(Denied): capability.enter()

    async def test_cancel_after_send_preserves_unknown_and_blocks_matching_terminal_until_drop(self):
        owner = Owner(); owner.durable_unknown.add('op')
        capability = Capability(owner, 'op'); authority = AuthorityFixture(); sent = asyncio.Event(); trace = []; calls = []
        async def transport():
            calls.append('provider'); sent.set(); await asyncio.Future()
        task = asyncio.create_task(proposed_bao_order(capability, ready, ready, transport, authority, lambda: calls.append('consumer'), trace))
        await sent.wait()
        with self.assertRaises(Busy): owner.close_begin()
        with self.assertRaises(Busy): owner.terminal_begin('op')
        owner.terminal_begin('unrelated'); owner.terminal_finish('unrelated')
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        owner.close_begin()
        self.assertEqual(calls, ['provider']); self.assertEqual(owner.durable_unknown, {'op'})
        with self.assertRaises(Denied): capability.enter()

    async def test_operation_entry_does_not_replace_kernel_authority(self):
        owner = Owner(); capability = Capability(owner, 'op'); authority = AuthorityFixture(); authority.live = False
        trace = []; calls = []
        async def transport():
            calls.append('provider')
        with self.assertRaises(AuthorityDenied):
            await proposed_bao_order(capability, ready, ready, transport, authority, lambda: calls.append('consumer'), trace)
        self.assertEqual(calls, []); self.assertEqual(trace, ['pending', 'active', 'drop'])
        owner.close_begin()

    async def test_post_send_revocation_still_denies_final_secret_delivery(self):
        owner = Owner(); capability = Capability(owner, 'op'); authority = AuthorityFixture()
        sent = asyncio.Event(); finish_transport = asyncio.Event(); trace = []; calls = []
        async def transport():
            calls.append('provider'); sent.set(); await finish_transport.wait()
        task = asyncio.create_task(proposed_bao_order(capability, ready, ready, transport, authority, lambda: calls.append('consumer'), trace))
        await sent.wait(); authority.live = False
        with self.assertRaises(Busy): owner.close_begin()
        finish_transport.set()
        with self.assertRaises(AuthorityDenied): await task
        self.assertEqual(calls, ['provider']); self.assertEqual(authority.deliveries, 0)
        owner.close_begin()

if __name__ == '__main__':
    unittest.main(verbosity=2)
