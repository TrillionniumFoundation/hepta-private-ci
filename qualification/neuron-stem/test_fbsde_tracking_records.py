"""Evidence retention, finite allocation and unchanged encoded record contracts."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import weakref
from four_gate_common import canonical
from fbsde_tracking_records import RecordBuffer, audit_recording, COMPACT


class RecordTests(unittest.TestCase):
    def buffer(self, **kwargs):
        return RecordBuffer({'used': 0, 'limit': 1024*1024}, **kwargs)

    def test_snapshot_does_not_retain_nested_object_graph(self):
        class Row(dict):
            pass
        row = Row(trace=[{'before': [1,2], 'after': [2,1]}]); reference = weakref.ref(row)
        b = self.buffer(); b.append(row); row['trace'][0]['after'][0] = 99
        del row
        self.assertIsNone(reference())
        self.assertEqual(list(b), [{'trace':[{'before':[1,2], 'after':[2,1]}]}])

    def test_iterator_cannot_mutate_stored_record(self):
        b=self.buffer(); b.append({'x':[1]}); next(iter(b))['x'].append(2)
        self.assertEqual(list(b), [{'x':[1]}])

    def test_row_limit_rejects_without_changing_prefix(self):
        b=self.buffer(max_rows=1); b.append({'a':1})
        with self.assertRaisesRegex(ValueError,'capacity'): b.append({'a':2})
        self.assertEqual(list(b),[{'a':1}])

    def test_byte_limit_rejects_without_changing_shared_usage(self):
        budget={'used':0,'limit':20}; a=RecordBuffer(budget); b=RecordBuffer(budget)
        a.append({'a':1}); b.append({'b':2}); before=dict(budget)
        with self.assertRaisesRegex(ValueError,'byte budget'): b.append({'c':3})
        self.assertEqual(budget,before); self.assertEqual(len(b),1)

    def test_row_bytes_and_nonfinite_rejected(self):
        b=self.buffer(max_row_bytes=8)
        for row in ({'text':'long'}, {'p':float('nan')}):
            with self.assertRaises(ValueError): b.append(row)
        self.assertEqual(len(b),0)

    def test_output_preserves_json_semantics_and_hash(self):
        b=self.buffer(); original=[{'x':'雪\n一','v':(1,2)},{'x':False}]
        for row in original:b.append(row)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'out.json'; report=b.write_once(p)
            self.assertEqual(json.loads(p.read_bytes()),json.loads(canonical(original)))
            self.assertEqual(report['file_sha256'],hashlib.sha256(p.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError,'sealed'):b.append({})
            with self.assertRaisesRegex(ValueError,'sealed'):b.write_once(Path(d)/'second.json')

    def test_existing_file_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'out.json';p.write_bytes(b'keep');b=self.buffer()
            with self.assertRaises(FileExistsError):b.write_once(p)
            self.assertEqual(p.read_bytes(),b'keep');self.assertFalse(b.sealed)

    def test_empty_stream_valid(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'out.json';r=self.buffer().write_once(p)
            self.assertEqual(json.loads(p.read_bytes()),[]);self.assertEqual(r['rows'],0)

    def fixture(self, root):
        b=self.buffer();b.append({'x':[1,2]});m=b.write_once(root/'proposals.json')
        (root/'plan.json').write_text(json.dumps({'record_profile':COMPACT,'arms':[]}))
        record={'profile':COMPACT,'streams':{'proposals':m},'retained_payload_bytes':b.nbytes,
                'shared_payload_limit_bytes':1024*1024,'recording_cpu_ns':1}
        (root/'record-retention.json').write_text(json.dumps(record));return record

    def test_independent_saved_array_audit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.fixture(p);r=audit_recording(p)
            self.assertEqual(r['rows'],1);self.assertFalse(r['budget_stability_established'])

    def test_rehashed_false_count_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);m=self.fixture(p);m['streams']['proposals']['rows']=2
            (p/'record-retention.json').write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'count'):audit_recording(p)

    def test_rehashed_false_byte_budget_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);m=self.fixture(p);m['retained_payload_bytes']+=1
            (p/'record-retention.json').write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'shared'):audit_recording(p)

    def test_modified_original_array_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.fixture(p);(p/'proposals.json').write_text('[{"x":[9,2]}]')
            with self.assertRaisesRegex(ValueError,'byte hash'):audit_recording(p)


if __name__=='__main__':unittest.main()
