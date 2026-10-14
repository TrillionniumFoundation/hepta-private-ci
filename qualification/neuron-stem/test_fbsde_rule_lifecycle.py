"""Behavioral final-use, stale evidence, drift and paid recovery contracts."""
import unittest
from four_gate_common import digest
from fbsde_transfer import TransferProblem, TransferTable, OPS
from fbsde_rule_lifecycle import RuleSlot, UseTicket
from fbsde_transfer_reference import source_effect

PUBLIC = dict(source_id='unit', names=['Mira','Nolan','Orla'],
              event='Mira, Nolan and Orla execute the registered operation.')
CONTEXT = dict(scope='research', generation=1, environment='unit')


def source(rule, calls=None):
    def reveal(request):
        if calls is not None: calls.append(request.copy())
        return dict(request_sha256=digest(request), effect=source_effect(rule, tuple(request['state'])))
    return reveal


def slot(rule=1, limit=5):
    p = TransferProblem.build(PUBLIC, CONTEXT)
    history = tuple((s, p.table[rule][s]) for s in range(6))
    table = TransferTable.from_support(p, history, dict(binding=p.binding, **CONTEXT))
    return RuleSlot(PUBLIC, CONTEXT, history, table.snapshot(), recovery_limit=limit)


def begin(s, state=OPS[0]): return s.begin(PUBLIC['event'], PUBLIC['names'], state)


class LifecycleTests(unittest.TestCase):
    def test_current_use_and_replay(self):
        s = slot(); t = begin(s)
        self.assertTrue(s.verify(t, source(1)))
        self.assertEqual(s.finish(t), source_effect(1, OPS[0]))
        with self.assertRaisesRegex(ValueError,'consumed'): s.finish(t)

    def test_generation_change_fences_already_proposed_result(self):
        s = slot(); t = begin(s); s.advance_generation(2)
        with self.assertRaisesRegex(ValueError,'stale'): s.finish(t)
        self.assertEqual(s.status()['state'],'quarantined')
        with self.assertRaisesRegex(ValueError,'monotone'): s.advance_generation(1)

    def test_current_context_is_not_supplied_by_old_handle(self):
        s = slot(); t = begin(s); s.advance_generation(2)
        with self.assertRaises(ValueError): s.finish(UseTicket(t.slot,1,t.sequence,t.identity))

    def test_inflight_verification_cannot_revive_after_generation_change(self):
        s = slot(); t = begin(s)
        def delayed(r): s.advance_generation(2); return source(1)(r)
        self.assertFalse(s.verify(t,delayed))
        with self.assertRaises(ValueError): s.finish(t)
        self.assertIn('late_receipt',[r['event'] for r in s.records()])

    def test_contradiction_cancels_all_pending_uses(self):
        s = slot(); a = begin(s); b = begin(s,OPS[1])
        self.assertFalse(s.verify(a,source(2)))
        with self.assertRaises(ValueError): s.finish(b)
        self.assertEqual(s.status()['pending'],0)

    def test_new_evidence_required_to_reactivate(self):
        s = slot(); old = begin(s); self.assertFalse(s.verify(old,source(7)))
        calls=[]; self.assertTrue(s.relearn(source(7,calls)))
        self.assertLessEqual(len(calls),5); self.assertGreater(len(calls),0)
        with self.assertRaises(ValueError): s.finish(old)
        for state in OPS:
            t=begin(s,state); self.assertEqual(s.finish(t),tuple(state[j] for j in source_effect(7,state)))
        self.assertEqual(sum(r['event']=='initial' for r in s.records()),1)
        self.assertEqual(sum(r['event']=='reactivate' for r in s.records()),1)

    def test_failed_recovery_costs_do_not_reset(self):
        s = slot(limit=2); s.advance_generation(2)
        def fail(_): raise RuntimeError('unavailable')
        self.assertFalse(s.relearn(fail)); self.assertFalse(s.relearn(fail))
        self.assertFalse(s.relearn(lambda _:self.fail('spent budget used')))
        s.advance_generation(3)
        self.assertFalse(s.relearn(lambda _:self.fail('generation reset budget')))
        self.assertEqual(s.status()['recovery_attempts'],2)

    def test_bad_receipt_is_retained_and_cannot_publish(self):
        s = slot(); t=begin(s)
        self.assertFalse(s.verify(t,lambda _:dict(request_sha256='bad',effect=(0,1,2))))
        self.assertEqual(s.status()['state'],'quarantined')
        self.assertEqual(next(r for r in s.records() if r['event']=='verification')['receipt']['request_sha256'],'bad')

    def test_source_exception_quarantines(self):
        s=slot(); t=begin(s)
        def bad(_): raise RuntimeError('source offline')
        self.assertFalse(s.verify(t,bad)); self.assertEqual(s.status()['state'],'quarantined')

    def test_nonbijective_refuses_reacquisition(self):
        s=slot();s.advance_generation(2)
        self.assertFalse(s.relearn(lambda r:dict(request_sha256=digest(r),effect=(0,0,1))))
        self.assertEqual(s.status()['state'],'refused')
        self.assertFalse(s.relearn(lambda _:self.fail('refused family retried')))

    def test_partial_recovery_observations_survive_resume(self):
        s=slot();s.advance_generation(2); calls=[]
        def interrupted(r):
            calls.append(r)
            if len(calls)==2: raise RuntimeError('temporary')
            return source(7)(r)
        self.assertFalse(s.relearn(interrupted))
        self.assertTrue(s.relearn(source(7,calls)))
        self.assertEqual([r['sequence'] for r in calls],list(range(len(calls))))
        self.assertEqual(calls[2]['history_sha256'],calls[1]['history_sha256'])

    def test_recovery_inflight_generation_change_discards_late_effect(self):
        s=slot();s.advance_generation(2)
        def delayed(r): s.advance_generation(3); return source(7)(r)
        self.assertFalse(s.relearn(delayed))
        self.assertEqual(s.status()['recovery_attempts'],1)
        self.assertEqual(s.status()['state'],'quarantined')

    def test_reentrant_recovery_does_not_create_parallel_source_calls(self):
        s=slot();s.advance_generation(2)
        def reentrant(r):
            with self.assertRaisesRegex(ValueError,'in flight'): s.relearn(lambda _:self.fail())
            return source(7)(r)
        self.assertTrue(s.relearn(reentrant))

    def test_snapshot_and_returned_logs_do_not_reactivate(self):
        s=slot(); logs=s.records(); logs[0]['snapshot']['effects'][0]=4
        self.assertNotEqual(s.records(),logs)
        s.advance_generation(2)
        with self.assertRaisesRegex(ValueError,'not currently active'): begin(s)

    def test_silent_drift_is_invisible_until_a_discriminating_observation(self):
        # Explicit limitation: one sentinel state cannot establish a whole domain.
        p=TransferProblem.build(PUBLIC,CONTEXT)
        a,b=next((i,j) for i in range(33) for j in range(33)
                 if p.table[i][0]==p.table[j][0] and p.table[i]!=p.table[j])
        s=slot(a);t=begin(s);self.assertTrue(s.verify(t,source(b)));s.finish(t)
        state=next(OPS[k] for k in range(6) if p.table[a][k]!=p.table[b][k])
        t=begin(s,state)
        self.assertNotEqual(s.finish(t),tuple(state[j] for j in source_effect(b,state)))

    def test_all_finite_in_family_recoveries_fit_same_five_call_limit(self):
        for rule in range(33):
            s=slot();s.advance_generation(2);calls=[]
            self.assertTrue(s.relearn(source(rule,calls)))
            self.assertLessEqual(len(calls),5)

    def test_foreign_slot_ticket_rejected(self):
        a,b=slot(1),slot(2);t=begin(a)
        with self.assertRaises(ValueError): b.finish(t)

    def test_identical_slot_clone_does_not_accept_another_live_handle(self):
        a,b=slot(),slot();ta=begin(a);begin(b)
        with self.assertRaisesRegex(ValueError,'foreign'):b.finish(ta)

    def test_serialized_ticket_fields_are_not_a_live_use_handle(self):
        s=slot();t=begin(s)
        with self.assertRaisesRegex(ValueError,'foreign'):s.finish(UseTicket(**t.__dict__))

    def test_pending_source_check_cannot_be_published_reentrantly(self):
        s=slot();t=begin(s)
        def during(r):
            with self.assertRaisesRegex(ValueError,'pending'):s.finish(t)
            return source(1)(r)
        self.assertTrue(s.verify(t,during));s.finish(t)

    def test_same_ticket_cannot_start_two_concurrent_verifications(self):
        s=slot();t=begin(s)
        def during(r):
            with self.assertRaisesRegex(ValueError,'in flight'):s.verify(t,lambda _:self.fail())
            return source(1)(r)
        self.assertTrue(s.verify(t,during))

    def test_source_cannot_rewrite_the_issued_request(self):
        s=slot();t=begin(s)
        def mutate(r):
            r['state']=OPS[1]
            return source(1)(r)
        self.assertFalse(s.verify(t,mutate))
        self.assertEqual(next(e for e in s.records() if e['event']=='verification')['request']['state'],list(OPS[0]))

    def test_real_thread_late_response_after_generation_fence(self):
        from threading import Event,Thread
        entered=Event();release=Event();result=[];s=slot();t=begin(s)
        def waiting(r):
            entered.set()
            if not release.wait(2):raise RuntimeError('test synchronization timeout')
            return source(1)(r)
        worker=Thread(target=lambda:result.append(s.verify(t,waiting)))
        worker.start()
        try:
            self.assertTrue(entered.wait(2));s.advance_generation(2)
        finally:
            release.set();worker.join(2)
        self.assertFalse(worker.is_alive());self.assertEqual(result,[False])
        with self.assertRaises(ValueError):s.finish(t)

    def test_malformed_receipt_cannot_escape_retirement_via_serialization(self):
        for value in (object(), {'request_sha256':'x'*10000,'effect':[0,1,2]},
                      {'request_sha256':'x','effect':[float('nan'),1,2]},
                      {'request_sha256':'x','effect':[0,1,{'nested':object()}]}):
            s=slot();t=begin(s)
            self.assertFalse(s.verify(t,lambda _:value))
            with self.assertRaises(ValueError):s.finish(t)
            row=next(r for r in s.records() if r['event']=='verification')
            self.assertIsNone(row['receipt']);self.assertIn('malformed',row['error'])

    def test_malformed_recovery_is_charged_and_large_error_is_bounded(self):
        s=slot(limit=2);s.advance_generation(2)
        self.assertFalse(s.relearn(lambda _:object()))
        def bad(_):raise RuntimeError('x'*10000)
        self.assertFalse(s.relearn(bad))
        self.assertEqual(s.status()['recovery_attempts'],2)
        self.assertEqual(len(s.records()[-1]['error']),512)
        self.assertFalse(s.relearn(lambda _:self.fail('spent budget')))

    def test_pending_capacity(self):
        s=slot()
        for _ in range(16):begin(s)
        with self.assertRaisesRegex(ValueError,'pending'):begin(s)

if __name__=='__main__':unittest.main()
