import copy
import unittest
from scale import generate, trace_report

DIGEST = 'a' * 64

class TraceV2Tests(unittest.TestCase):
    def setUp(self):
        self.jobs = generate(64, 0.1, 0.5, 'mixed_family', DIGEST)
        self.events = []
        for i, row in enumerate(self.jobs):
            cold = i < 3
            event = {
                'kind':'request', 'request_id':row['request_id'],
                'model_digest':DIGEST, 'scope':row['scope'],
                'generation':row['generation'],
                'enqueued_us':9000+row['submitted_at_us'],
                'start_us':9100+row['submitted_at_us'],
                'end_us':9250+row['submitted_at_us']+i,
                'path':'cold_encoder' if cold else 'cache_hit_head',
                'status':'ok', 'cpu_us':50, 'rss_bytes':1_000_000
            }
            if cold: event['batch_id']='batch1'
            self.events.append(event)
        cold = self.events[:3]
        self.events.append({
            'kind':'backend_batch', 'batch_id':'batch1','backend':'native_hepta',
            'batch_size':3, 'model_digest':DIGEST, 'scope':self.jobs[0]['scope'],
            'generation':self.jobs[0]['generation'],
            'member_request_ids':[x['request_id'] for x in cold],
            'backend_started_us':max(x['start_us'] for x in cold),
            'backend_ended_us':min(x['end_us'] for x in cold),
        })
        self.events += [{'kind':'wal_fsync','latency_us':800},
                        {'kind':'restart','recovery_ms':12,'checksum_verified':True}]

    def invalid(self, match):
        with self.assertRaisesRegex(ValueError,match):
            trace_report(self.jobs,self.events)

    def test_valid_unattested(self):
        r=trace_report(self.jobs,self.events)
        self.assertEqual(r['schema'],'hepta.stem-cell-scale-observation.v2')
        self.assertEqual(r['trace_claimed_multi_request_batches'],1)
        self.assertIsNone(r['independently_verified_backend_multi_request_batches'])
        self.assertFalse(r['native_worker_attested'])
        self.assertFalse(r['production_authorized'])
        self.assertEqual(r['completed'],7)
        self.assertEqual(r['wal_fsync_p99_ms'],0.8)

    def test_cross_scope(self):
        self.jobs[1]['scope']=self.events[1]['scope']='another'
        self.invalid('mixed-scope/generation')

    def test_cross_generation(self):
        self.jobs[1]['generation']=self.events[1]['generation']=2
        self.invalid('mixed-scope/generation')

    def test_forged_batch_scope(self):
        self.events[-3]['scope']='another'
        self.invalid('mixed-scope/generation')

    def test_forged_batch_generation(self):
        self.events[-3]['generation']=2
        self.invalid('mixed-scope/generation')

    def test_missing_member_id(self):
        self.events[-3]['member_request_ids'][1]=self.jobs[3]['request_id']
        self.invalid('member identity')

    def test_duplicate_member(self):
        self.events[-3]['member_request_ids'][1]=self.jobs[0]['request_id']
        self.invalid('membership')

    def test_oversize_batch(self):
        self.events[-3]['batch_size']=33
        self.invalid('invalid or duplicate backend batch')

    def test_noninteger_batch_size(self):
        self.events[-3]['batch_size']=True
        self.invalid('invalid or duplicate backend batch')

    def test_clock_interval_drift(self):
        self.events[-3]['backend_started_us']=self.events[0]['start_us']-1
        self.invalid('interval not covered')

    def test_wrong_clock_type(self):
        self.events[0]['start_us']=1.23
        self.invalid('clock')

    def test_wrong_memory_type(self):
        self.events[0]['rss_bytes']=True
        self.invalid('resource counters')

    def test_missing_batch_identity(self):
        del self.events[-3]['member_request_ids']
        self.invalid('membership')

    def test_4096_intents_not_native_execution(self):
        intents=generate(4096,1.0,0.9,'same_family',DIGEST)
        self.assertEqual(len(intents),4096)
        self.assertEqual(len({x['request_id'] for x in intents}),4096)
        self.assertNotIn('runtime_receipt',intents[0])

if __name__=='__main__':
    unittest.main()
