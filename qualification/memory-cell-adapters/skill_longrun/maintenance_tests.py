"""Boundary regressions on invented data; no fitting or formal study is run."""

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import canonical, command, executions, sha
from owner import create
from owner_read import guard
from targets import mutate
from tensor_cell import CellConfig, OutputSpec, TensorCell


class SkillMaintenanceTests(unittest.TestCase):
    def test_mutation_changes_observable_behavior_without_model_feedback(self):
        for seed in (731, 732, 733):
            previous = {'kind': 'skill', 'index': 3, 'source_id': 'invented-source', 'version': 0,
                        'active': True, 'value': [0, 0, 0, 6]}
            for stage in range(1, 65):
                updated = mutate(previous, seed, stage)
                self.assertNotEqual(updated['value'], previous['value'])
                self.assertNotEqual([r['result']['value'] for r in executions(updated['value'])],
                                    [r['result']['value'] for r in executions(previous['value'])])
                self.assertEqual(updated['version'], previous['version']+1)
                self.assertTrue(updated['active'])
                self.assertNotEqual(updated['source_id'], previous['source_id'])
                self.assertEqual(updated['value'][-1], 6)
                previous = updated

    def test_persisted_request_is_exact_child_stdin(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root/'echo_child.py'
            script.write_text('import hashlib,json,sys\nraw=sys.stdin.buffer.read()\n'
                              'print(json.dumps({"request_sha256":hashlib.sha256(raw).hexdigest(),"decoded":json.loads(raw)}))\n')
            frame = {'program': [5, 1, 2, 6], 'label': '例外\nrecord'}
            response, process = command(sys.executable, script, frame, root/'child')
            raw = (root/'child.request.json').read_bytes()
            self.assertEqual(raw, canonical(frame)+b'\n')
            self.assertEqual(process['request'], {'bytes': len(raw), 'sha256': sha(raw)})
            self.assertEqual(response['request_sha256'], sha(raw))
            self.assertEqual(response['decoded'], frame)
            self.assertTrue(process['passed'])

    def test_actual_owner_refuses_stale_and_revoked_and_fresh_reader_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            encoder = 'a'*64
            rows = [{'kind': 'skill', 'index': i, 'source_id': f'invented-{i}', 'version': 0,
                     'value': [0, 0, 0, 6]} for i in range(8)]
            database = root/'owner.sqlite'
            create(database, rows)
            features = {kind: np.zeros((8, 384), dtype=np.float32) for kind in ('semantic', 'skill')}
            feature_path = root/'canonical.npz'
            np.savez(feature_path, **features)
            config = CellConfig('test-only-untrained', seed=42,
                                outputs=tuple(OutputSpec(f'op{i}', 'multiclass', 7) for i in range(4)))
            cell = TensorCell(config, encoder, source_ids=[r['source_id'] for r in rows])
            checkpoint = root/'checkpoint'
            cell.save(checkpoint)
            self.assertEqual(cell.training_history, [])
            with sqlite3.connect(database) as db:
                db.execute("UPDATE sources SET identity='changed-source',version=1 WHERE kind='skill' AND idx=0")
                db.execute("UPDATE sources SET active=0 WHERE kind='skill' AND idx=1")
            for workflow, status in ((0, 'stale_source'), (1, 'revoked')):
                result = guard(checkpoint, encoder, database, features, [workflow], status)
                self.assertTrue(result['passed'])
                self.assertEqual(result['model_reads']['calls'], 0)
                self.assertEqual(result['reads']['explicit_values'], 0)
                self.assertTrue(result['stop']['passed'])
            request = {'checkpoint': str(checkpoint), 'encoder_sha': encoder, 'database': str(database),
                       'canonical_features_path': str(feature_path), 'protocol_sha256': 'b'*64}
            result, process = command(sys.executable, HERE/'owner_read.py', request, root/'read')
            self.assertTrue(process['passed'], result)
            self.assertEqual(result['gradient_steps'], 0)
            self.assertFalse(result['training_modules_loaded'])
            self.assertEqual(result['target_module_import_audit'], [])
            self.assertEqual(result['parameter_sha256'], cell.parameter_digest())
            parameter, sql = result['arms']
            self.assertEqual(parameter['rows'][0]['result']['status'], 'stale_source')
            self.assertEqual(sql['rows'][0]['result']['value'], rows[0]['value'])
            for arm in (parameter, sql):
                self.assertEqual(arm['rows'][1]['result']['status'], 'revoked')
                self.assertEqual(arm['rows'][1]['executions'], [])
                self.assertTrue(arm['stop']['passed'])
            self.assertEqual(parameter['sql_audit']['source_payload_column_authorizations'], 0)
            self.assertEqual(parameter['reads']['explicit_values'], 0)


if __name__ == '__main__':
    unittest.main()
