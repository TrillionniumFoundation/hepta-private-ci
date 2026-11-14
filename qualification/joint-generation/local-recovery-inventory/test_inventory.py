"""Handmade metadata only: fake process identities/costs are not real execution evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('receipt_inventory', HERE / 'inventory.py')
m = importlib.util.module_from_spec(spec)
exec(compile((HERE / 'inventory.py').read_bytes(), str(HERE / 'inventory.py'), 'exec'), m.__dict__)
s = m.support
SOURCE = 'a' * 64


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='synthetic-recovery-inventory-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'owned'; self.root.mkdir(); (self.root / 'claims').mkdir()
        self.owner = dict(pid=20, birth_ticks=100, boot_id='HANDMADE-boot', pid_namespace='HANDMADE-ns')
        self.scope = dict(schema='BOUNDED-LOCAL-SCOPE-v1', production=False, scope_id='HANDMADE-scope', descendants=m.NO_DESCENDANTS, run_root=str(self.root),
            segment_ids=['one', 'two', 'three'], source_manifest={'path':str(self.base/'DO_NOT_OPEN_SOURCE'), 'sha256':SOURCE})
        self.scope_ref = self.put(self.base/'SCOPE.json', self.scope)
        self.put(self.root/'OWNER.json', dict(schema='BOUNDED-LOCAL-OWNER-v1', owner=self.owner, scope_ref=self.scope_ref))

    def put(self, path, value):
        path.write_bytes(s.canonical(value))
        return {'path':str(path), 'sha256':s.sha(path.read_bytes())}

    def segment(self, sid='one', predecessor=None, exit_code=0, settled=True, pid=21):
        root=self.root/sid; root.mkdir(); (root/'output').mkdir(); claim_dir=self.root/'claims'/sid; claim_dir.mkdir()
        cfg={'path':str(self.base/(sid+'-DO_NOT_OPEN_CONFIG')), 'sha256':'b'*64}
        process=dict(self.owner, pid=pid, birth_ticks=101+pid)
        claim=dict(schema='BOUNDED-LOCAL-CLAIM-v1', segment_id=sid, owner=self.owner, scope_ref=self.scope_ref,
            source_sha256=SOURCE, config_ref=cfg, retry_allowed=False, predecessor_settlement=predecessor)
        cr=self.put(claim_dir/'CLAIM.json', claim)
        self.put(root/'BOUND_PROCESS.json', dict(owner=self.owner, process=process, claim_ref=cr))
        raw=dict(schema='BOUNDED-LOCAL-RAW-WAIT-v1', segment_id=sid, owner=self.owner, process=process,
            scope_ref=self.scope_ref, source_sha256=SOURCE, config_ref=cfg, claim_ref=cr, complete_wait=True,
            wait_scope='owned-direct-child', descendants=m.NO_DESCENDANTS, fork_pid=pid, waited_pid=pid, exit_code=exit_code, wait_status=exit_code<<8,
            user_cpu_seconds='1.25', system_cpu_seconds='0.25', work_release_sent=True, error=None, cleanup_errors=[])
        rr=self.put(root/'RAW_WAIT.json', raw)
        if settled:
            result={'path':str(root/'output'/'RESULT.json'), 'sha256':'c'*64}
            return self.put(root/'SETTLEMENT.json', dict(schema='BOUNDED-LOCAL-SETTLEMENT-v1', status='FULLY_WAITED_EXIT0',
                segment_id=sid, scope_ref=self.scope_ref, source_sha256=SOURCE, owner=self.owner, process=process,
                scope_id='HANDMADE-scope', wait_scope='owned-direct-child', descendants=m.NO_DESCENDANTS,
                config_ref=cfg, raw_wait=rr, child_cpu_seconds='1.50', result=result))

    def inspect(self):
        return m.inspect_scope(self.scope_ref, SOURCE)

    def mutate(self, relative, key, value):
        p=self.root/relative; obj=s.decode(p.read_bytes()); obj[key]=value; self.put(p,obj)

    def test_settled_does_not_imply_parent_liveness_or_replay(self):
        self.segment(); r=self.inspect()
        self.assertEqual(r['records'][0]['status'], 'SETTLED_METADATA_ONLY')
        self.assertEqual(r['reported_child_cpu_sum'], '1.50')
        self.assertEqual((r['parent_inclusive_cpu_seconds'],r['whole_scope_complete'],r['current_liveness'],r['automatic_resume_or_replay_allowed']),
                         (None,False,'UNKNOWN',False))

    def test_no_payload_config_or_source_reads(self):
        self.segment(); calls=[]; read=s.read
        def allowed(path, limit):
            calls.append(str(path)); self.assertNotIn('DO_NOT_OPEN', str(path)); self.assertNotIn('/output/', str(path))
            return read(path, limit)
        with patch.object(s,'read',side_effect=allowed):r=self.inspect()
        self.assertEqual(r['reported_child_cpu_sum'],'1.50'); self.assertTrue(calls)

    def test_unknown_successor_retains_paid_prefix(self):
        self.segment(); (self.root/'claims'/'two').mkdir()
        r=self.inspect(); self.assertEqual(r['reported_child_cpu_sum'],'1.50')
        self.assertEqual(r['records'][1]['status'],'UNKNOWN_OR_INVALID')

    def test_nonzero_wait_remains_paid(self):
        self.segment(exit_code=7,settled=False); r=self.inspect()
        self.assertEqual((r['records'][0]['status'],r['reported_child_cpu_sum']),('WAITED_NONZERO','1.50'))

    def test_cost_sums_are_exact_under_small_decimal_context(self):
        from decimal import localcontext
        self.segment(settled=False)
        self.mutate('one/RAW_WAIT.json','user_cpu_seconds','1234567890123456789012345678')
        self.mutate('one/RAW_WAIT.json','system_cpu_seconds','0.000000001')
        with localcontext() as context:
            context.prec=2
            self.assertEqual(self.inspect()['reported_child_cpu_sum'],'1234567890123456789012345678.000000001')
        self.mutate('one/RAW_WAIT.json','user_cpu_seconds','9'*128+'e128')
        self.mutate('one/RAW_WAIT.json','system_cpu_seconds','1e-128')
        self.assertEqual(self.inspect()['reported_child_cpu_sum'],'9'*128+'0'*128+'.'+'0'*127+'1')
        self.mutate('one/RAW_WAIT.json','user_cpu_seconds','1e1000000')
        self.assertEqual(self.inspect()['records'][0]['status'],'UNKNOWN_OR_INVALID')

    def test_absent_settlement_does_not_erase_wait(self):
        self.segment(settled=False);r=self.inspect()
        self.assertEqual((r['records'][0]['status'],r['reported_child_cpu_sum']),('WAITED_WITHOUT_SETTLEMENT','1.50'))

    def test_duplicate_process_is_not_counted_twice(self):
        self.segment();self.segment('two',pid=21);r=self.inspect()
        self.assertEqual([x['status'] for x in r['records']],['DUPLICATE_PROCESS_IDENTITY']*2)
        self.assertEqual(r['reported_child_cpu_sum'],'0')

    def test_orphan_directory_is_unknown(self):
        self.segment();(self.root/'two').mkdir();r=self.inspect()
        self.assertTrue(any('orphan' in x for x in r['unknowns']));self.assertFalse(r['whole_scope_complete'])

    def test_missing_owner_withholds_sum(self):
        self.segment();(self.root/'OWNER.json').unlink();r=self.inspect()
        self.assertEqual((r['status'],r['reported_child_cpu_sum']),('UNKNOWN_SNAPSHOT',None))

    def test_scope_digest_mismatch_rejected(self):
        wrong=dict(self.scope_ref,sha256='0'*64)
        with self.assertRaises(ValueError):m.inspect_scope(wrong,SOURCE)

    def test_original_source_mismatch_rejected(self):
        with self.assertRaises(ValueError):m.inspect_scope(self.scope_ref,'b'*64)

    def test_raw_mutations_rejected_without_zeroing_history(self):
        self.segment();path=self.root/'one/RAW_WAIT.json';original=s.decode(path.read_bytes())
        cases={'complete_wait':False,'fork_pid':True,'waited_pid':True,'exit_code':False,'wait_status':256,
               'source_sha256':'b'*64,'owner':dict(self.owner,birth_ticks=200),'user_cpu_seconds':'NaN',
               'system_cpu_seconds':'-1','wait_scope':'unowned','claim_ref':{'path':'/x','sha256':'f'*64},
               'process':dict(self.owner),'descendants':'unknown'}
        for field,value in cases.items():
            with self.subTest(field=field):
                self.put(path,dict(original,**{field:value}));r=self.inspect()
                self.assertEqual(r['records'][0]['status'],'UNKNOWN_OR_INVALID')
                self.assertIsNone(r['parent_inclusive_cpu_seconds']);self.assertTrue(r['unknowns'])

    def test_settlement_mutations_keep_paid_wait(self):
        self.segment();path=self.root/'one/SETTLEMENT.json';original=s.decode(path.read_bytes())
        for field,value in {'child_cpu_seconds':'0','process':self.owner,'raw_wait':{'path':'/x','sha256':'f'*64},'scope_id':'other','wait_scope':'other','descendants':'unknown'}.items():
            with self.subTest(field=field):
                self.put(path,dict(original,**{field:value}));r=self.inspect()
                self.assertEqual((r['records'][0]['status'],r['reported_child_cpu_sum']),('WAITED_INVALID_SETTLEMENT','1.50'))

    def test_duplicate_json_keys_are_rejected(self):
        self.segment();(self.root/'one/RAW_WAIT.json').write_text('{"a":1,"a":2}')
        self.assertEqual(self.inspect()['records'][0]['status'],'UNKNOWN_OR_INVALID')

    def test_symlink_receipt_is_not_followed(self):
        self.segment();p=self.root/'one/RAW_WAIT.json';p.unlink();p.symlink_to(self.base/'secret')
        self.assertEqual(self.inspect()['records'][0]['status'],'UNKNOWN_OR_INVALID')

    def test_caller_input_is_not_mutated(self):
        self.segment();before=copy.deepcopy(self.scope_ref);self.inspect();self.assertEqual(self.scope_ref,before)

    def test_new_call_revalidates_changes(self):
        self.segment();self.assertEqual(self.inspect()['reported_child_cpu_sum'],'1.50')
        self.mutate('one/RAW_WAIT.json','complete_wait',False)
        self.assertEqual(self.inspect()['records'][0]['status'],'UNKNOWN_OR_INVALID')

    def test_change_during_read_withholds_entire_snapshot(self):
        self.segment();original=m._ReadSet.recheck
        def change(reader):
            self.mutate('one/RAW_WAIT.json','complete_wait',False);original(reader)
        with patch.object(m._ReadSet,'recheck',change):r=self.inspect()
        self.assertEqual((r['status'],r['reported_child_cpu_sum']),('UNKNOWN_SNAPSHOT',None))

    def test_extent_limit_is_fail_closed(self):
        self.segment()
        with patch.object(m,'MAX_FILE_BYTES',10):
            with self.assertRaises(ValueError):self.inspect()

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(InventoryTests))
    print(json.dumps({'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'success':result.wasSuccessful(),'scope':'HANDMADE_METADATA_ONLY'},sort_keys=True))
    sys.exit(not result.wasSuccessful())
