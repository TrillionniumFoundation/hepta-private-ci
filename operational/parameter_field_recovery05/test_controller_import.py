"""CONTEXT_RECONSTRUCTION: synthetic imports and real tiny workers; no science."""

import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from . import controller
from .owned_children import run_controller


WORKER = r"""
import argparse, hashlib, json, resource
from pathlib import Path
parser = argparse.ArgumentParser()
for key in ('root','freeze','amendment','amendment-sha256','phase','seed'):
    parser.add_argument('--'+key)
args, unused = parser.parse_known_args()
phase = args.phase or 'C'
seed = int(args.seed) if args.seed is not None else None
root = Path(args.root)
endpoint = Path(__file__).name == 'endpoint_v2.py'
if endpoint:
    relative = 'stage_'+phase+('/endpoint_evaluation' if phase=='C' else '/endpoints')+'/ENDPOINTS.json'
else:
    token = phase+('-all' if seed is None else '-seed-'+str(seed))
    relative = 'operations/'+token+'.COMPLETE.json'
value = {'complete':True,'phase':phase,'seed':seed,'source_freeze_sha256':hashlib.sha256(Path(args.freeze).read_bytes()).hexdigest(),
         'operational_amendment_sha256':getattr(args,'amendment_sha256'),'attempt_id':'attempt02',
         'post_execution_storage_check':True,'process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
         'synthetic_test_worker':True,'scientific_gradient_microsteps':0}
path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(json.dumps(value,sort_keys=True)+'\n')
print(json.dumps({'synthetic_test_worker_completed':relative}),flush=True)
"""


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return desc(path)


def desc(path):
    value = path.read_bytes()
    return {"path": str(path), "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}


class FixtureBudget:
    """Filesystem-only test substitute; production installs the registered budget."""

    def __init__(self, root, registration):
        self.root = Path(root)
        self.registration = registration

    def check(self, *args, **kwargs):
        return self.inventory()

    def inventory(self):
        return {"logical_bytes": 0, "allocated_unique_inode_bytes": 0, "unique_inodes": 0,
                "synthetic_budget_fixture": True}

    def writer_lock(self):
        return contextlib.nullcontext()

    def write_json(self, path, value, allow_replace=False, **kwargs):
        path = Path(path)
        if path.exists() and not allow_replace:
            raise FileExistsError(path)
        return write(path, value)

    def write_bytes(self, path, payload, **kwargs):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with Path(path).open('xb') as stream:
            stream.write(payload)

    def append_bytes(self, path, payload):
        with Path(path).open('ab') as stream:
            stream.write(payload)


class ImportFixture:
    def __init__(self, base):
        self.base, self.old, self.fresh, self.source = base, base/'old_raw', base/'fresh_raw', base/'test_source'
        self.old.mkdir(); self.fresh.mkdir()
        package = self.source/'experiments/parameter_field_fullstudy_20261029'
        package.mkdir(parents=True)
        (package.parent/'__init__.py').write_text('')
        (package/'__init__.py').write_text('')
        self.source_files = {}
        for name in ('launch_v2.py', 'resource_v2.py', 'run_v2.py', 'architecture_run_v2.py', 'endpoint_v2.py'):
            path = package/name
            path.write_text(WORKER if name in ('run_v2.py', 'architecture_run_v2.py', 'endpoint_v2.py') else '# synthetic controller fixture\n')
            self.source_files[path.relative_to(self.source).as_posix()] = desc(path)['sha256']
        self.protocol = write(base/'PROTOCOL.json', {'synthetic_test_fixture': True})
        self.old_profile = self.profile(base/'old_profile.json', self.old)
        self.old_freeze = self.freeze(base/'old_freeze.json', self.old_profile)
        self.old_job = self.job('A-17', self.old, self.old_profile, self.old_freeze)
        queue = write(base/'old_queue.json', {'schema': 'hepta.fullstudy.queue.2', 'attempt_id': 'attempt02', 'finalize': False, 'jobs': [self.old_job]})
        config = write(base/'old_config.json', {'raw_root': str(self.old), 'source_root': str(self.source), 'source_commit': 'b'*40,
            'descriptors': {'amendment': self.old_profile, 'initial_queue': queue}})
        self.parent = {'registered_commit': 'a'*40, 'synthetic_test_fixture': True}
        science = write(self.old/'stage_A/seed-17/COMPLETE.json', {
            'complete': True, 'phase': 'A', 'seed': 17, 'path_count': 16, 'costs': {'scheduled_gradient_microsteps': 39168},
            'registered_commit': 'b'*40, 'source_freeze_sha256': self.old_freeze['sha256'], 'assets': {},
            'cpu_seconds': 123.0, 'wall_seconds': 70.0, 'synthetic_test_fixture': True})
        operation = write(self.old/'operations/A-seed-17.COMPLETE.json', {
            'complete': True, 'phase': 'A', 'seed': 17, 'attempt_id': 'attempt02', 'source_freeze_sha256': self.old_freeze['sha256'],
            'operational_amendment_sha256': self.old_profile['sha256'], 'post_execution_storage_check': True,
            'registered_commit': 'b'*40, 'scientific_parent': self.parent, 'process_peak_rss_bytes': 486211584,
            'scientific_complete': {**science, 'path': 'stage_A/seed-17/COMPLETE.json'}})
        result = write(self.old/'controller/A-17.RESULT.json', {'complete': True, 'exit_code': 0,
            'completion': {**operation, 'path': 'operations/A-seed-17.COMPLETE.json'}, 'wall_seconds': 71.0,
            'process_peak_rss_bytes': 486211584})
        payload = self.old/'stage_A/seed-17/bank/synthetic.blob'; payload.parent.mkdir(); payload.write_bytes(b'closed synthetic A17 payload\n')
        anchors = {'controller_result': result, 'operation_complete': operation, 'scientific_complete': science,
                   'source_freeze': self.old_freeze, 'profile': self.old_profile, 'config': config}
        expected = {'registered_commit': 'b'*40, 'source_freeze_sha256': self.old_freeze['sha256'],
                    'profile_sha256': self.old_profile['sha256'], 'assets': {}}
        pins = write(base/'IMPORT_PINS.json', {'anchors': anchors, 'expected': expected, 'fresh_raw': str(self.fresh)})
        rows = []
        for source, relative in ((science, 'stage_A/seed-17/COMPLETE.json'), (operation, 'operations/A-seed-17.COMPLETE.json'),
                                 (result, 'imports/execution04/A-17/ORIGINAL_CONTROLLER_RESULT.json'),
                                 (desc(payload), 'stage_A/seed-17/bank/synthetic.blob')):
            target = self.fresh/relative; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source['path'], target)
            rows.append({'source': source, 'relative': relative})
        self.receipt_value = {'schema': controller.RECEIPT_SCHEMA, 'complete': True, 'imported': True, 'executed_here': False,
            'source_episode': controller.SOURCE_EPISODE, 'target_episode': controller.TARGET_EPISODE, 'seed': 17,
            'fresh_raw': str(self.fresh), 'source_root': str(self.source), 'pins': pins, 'anchors': anchors, 'expected': expected,
            'scientific_parent': self.parent, 'materialize': rows, 'new_scheduled_gradient_microsteps': 0,
            'scientific_workers_started': 0, 'original_seals_modified': False, 'synthetic_test_fixture': True}
        self.receipt_path = self.fresh/'imports/execution04/A-17/IMPORT_RECEIPT.json'
        self.receipt = write(self.receipt_path, self.receipt_value)
        self.new_profile = self.profile(base/'new_profile.json', self.fresh)
        self.new_freeze = self.freeze(base/'new_freeze.json', self.new_profile)
        self.args = SimpleNamespace(root=str(self.fresh), queue=str(base/'new_queue.json'), freeze=self.new_freeze['path'],
            freeze_sha256=self.new_freeze['sha256'], amendment=self.new_profile['path'], amendment_sha256=self.new_profile['sha256'],
            resume_admission=False, recover_zero_work=False)

    def profile(self, path, raw):
        return write(path, {'status': 'REGISTERED_PRE_ENDPOINT', 'execution_ready': True, 'attempt_id': 'attempt02', 'raw_root': str(raw),
            'proposed_resource_contract': {'global_raw_logical_bytes': 2*1024**3, 'minimum_private_allocatable_bytes': 256*1024**2,
                                          'C_training_evidence_bytes': 350*1024**2},
            'concurrency': {'max_workers': 2, 'memory_margin_bytes': 1024**3, 'worker_reservation_bytes': 768*1024**2}})

    def freeze(self, path, profile):
        return write(path, {'allowed_phases': ['OPS', 'A', 'B', 'C', 'W', 'R'], 'attempt_id': 'attempt02', 'execution_kind': 'controller',
            'operational_amendment_sha256': profile['sha256'], 'registered_commit': 'b'*40,
            'source_files': self.source_files, 'artifacts': {}, 'protocol_sha256': self.protocol['sha256']})

    def job(self, label, raw, profile, freeze):
        endpoint = label.endswith('_endpoint'); phase = label[0]
        seed = int(label.split('-')[1]) if '-' in label else None
        module = 'endpoint_v2' if endpoint else 'architecture_run_v2' if phase == 'C' else 'run_v2'
        argv = ['-B', '-m', 'experiments.parameter_field_fullstudy_20261029.'+module]
        if module != 'architecture_run_v2':
            argv += ['--phase', phase]
        if seed is not None:
            argv += ['--seed', str(seed)]
        argv += ['--freeze', freeze['path'], '--root', str(raw), '--amendment', profile['path'],
                 '--amendment-sha256', profile['sha256'], '--protocolR' if phase == 'R' else '--protocol', self.protocol['path'], '--execute']
        if endpoint:
            completion = 'stage_'+phase+('/endpoint_evaluation' if phase == 'C' else '/endpoints')+'/ENDPOINTS.json'
        else:
            completion = 'operations/'+phase+('-all' if seed is None else '-seed-'+str(seed))+'.COMPLETE.json'
        group = 'singleton' if endpoint or phase == 'W' else 'reconstruction' if phase == 'R' else 'training'
        return {'id': label, 'phase': phase, 'seed': seed, 'group': group, 'completion': completion,
                'argv': argv, 'freeze_sha256': freeze['sha256'], 'requires': []}

    def configure_core(self):
        core = controller.ControllerCore(self.receipt)
        core.StorageBudget = FixtureBudget
        core.memory_profile = lambda: {'current': 0, 'limit': 8*1024**3, 'effective_current': 0, 'clean_inactive_file': 0, 'oom': 0, 'oom_kill': 0}
        core.memory_admission = lambda reservation, margin, pending: {**core.memory_profile(), 'allowed': True, 'required_headroom': reservation+margin+pending}
        core.pending_growth = lambda root: 0
        return core

    def queue(self, core, finalize=True):
        jobs = [core.imported_job]
        for previous, label in zip(controller.ORDER, controller.ORDER[1:]):
            job = self.job(label, self.fresh, self.new_profile, self.new_freeze); job['requires'] = [previous]; jobs.append(job)
        return {'schema': 'hepta.fullstudy.queue.2', 'attempt_id': 'attempt02', 'finalize': finalize, 'jobs': jobs}


class ControllerImportTests(unittest.TestCase):
    def setUp(self):
        target = os.environ.get('HEPTA_CONTROLLER_TEST_OUTPUT')
        if target:
            self.base = Path(target)/self._testMethodName; self.base.mkdir(parents=True, exist_ok=False)
        else:
            temporary = tempfile.TemporaryDirectory(prefix='hepta-controller-import-'); self.addCleanup(temporary.cleanup); self.base = Path(temporary.name)
        self.fixture = ImportFixture(self.base)
        patcher = mock.patch.object(controller.legacy, 'ROOT', self.fixture.source); patcher.start(); self.addCleanup(patcher.stop)
        location = mock.patch.object(controller.legacy, '__file__', str(self.fixture.source/'experiments/parameter_field_fullstudy_20261029/launch_v2.py'))
        location.start(); self.addCleanup(location.stop)

    def test_only_A17_root_rebinding_is_accepted(self):
        f = self.fixture; core = f.configure_core(); job = core.imported_job
        expected = copy.deepcopy(f.old_job); position = expected['argv'].index('--root')+1; expected['argv'][position] = str(f.fresh)
        self.assertEqual(job, expected)
        public_record = core.import_record; public_record['job_changes'].clear()
        public_result = core.imported_result; public_result['origin']['job_changes'].clear()
        self.assertEqual(len(core.import_record['job_changes']), 1)
        self.assertEqual(len(core.imported_result['origin']['job_changes']), 1)
        self.assertEqual(core.validate_queue(f.queue(core), f.fresh)[0], expected)
        altered = f.queue(core); altered['jobs'][0]['argv'][altered['jobs'][0]['argv'].index('--amendment-sha256')+1] = f.new_profile['sha256']
        with self.assertRaisesRegex(ValueError, 'Only A17'):
            core.validate_queue(altered, f.fresh)

    def test_wrong_seed_import_rejected_even_with_updated_receipt_descriptor(self):
        f = self.fixture; value = copy.deepcopy(f.receipt_value); value['seed'] = 29
        updated = write(f.receipt_path, value)
        with self.assertRaisesRegex(ValueError, 'Only completed execution04 A-17'):
            controller.ControllerCore(updated)

    def test_import_payload_tamper_rejected(self):
        f = self.fixture; (f.fresh/'stage_A/seed-17/bank/synthetic.blob').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'descriptor bytes differ'):
            controller.ControllerCore(f.receipt)

    def test_original_seal_tamper_rejected(self):
        f = self.fixture; p = Path(f.receipt_value['anchors']['controller_result']['path']); v = json.loads(p.read_text()); v['exit_code'] = 7; write(p, v)
        with self.assertRaisesRegex(ValueError, 'descriptor bytes differ'):
            controller.ControllerCore(f.receipt)

    def test_incomplete_final_grid_and_lost_serial_predecessor_rejected(self):
        f = self.fixture; core = f.configure_core(); queue = f.queue(core); queue['jobs'].pop()
        with self.assertRaisesRegex(ValueError, 'full fixed fourteen-job grid'):
            core.validate_queue(queue, f.fresh)
        queue = f.queue(core); queue['jobs'][1]['requires'] = []
        with self.assertRaisesRegex(ValueError, 'serial predecessor'):
            core.validate_queue(queue, f.fresh)

    def test_import_cannot_enable_legacy_resume_or_reuse_controller_directory(self):
        f = self.fixture; core = f.configure_core(); write(Path(f.args.queue), f.queue(core))
        f.args.resume_admission = True
        with self.assertRaisesRegex(ValueError, 'never enables legacy'):
            core.run(f.args)
        self.assertFalse((f.fresh/'controller').exists())
        f.args.resume_admission = False; (f.fresh/'controller').mkdir()
        with self.assertRaisesRegex(ValueError, 'must be new'):
            core.run(f.args)

    def test_nonimported_A29_still_requires_new_profile_before_any_spawn(self):
        f = self.fixture; core = f.configure_core(); queue = f.queue(core)
        job = queue['jobs'][1]; job['argv'][job['argv'].index('--amendment-sha256')+1] = f.old_profile['sha256']
        write(Path(f.args.queue), queue)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'Job source/profile identity differs'):
                run_controller(core, core.run, self.base/'owned', f.args)
        closure = json.loads((self.base/'owned/CLOSURE.json').read_text())
        self.assertEqual(closure['attempt_count'], 0)
        imported = json.loads((f.fresh/'controller/A-17.RESULT.json').read_text())
        self.assertTrue(imported['imported']); self.assertFalse(imported['executed_here'])
        self.assertEqual(imported['wall_seconds'], 0.0); self.assertEqual(imported['cpu_seconds'], 0.0)
        self.assertFalse((f.fresh/'controller/A-17.START.json').exists())

    def test_real_tiny_workers_execute_thirteen_successors_and_close_fourteen_jobs(self):
        f = self.fixture; core = f.configure_core(); write(Path(f.args.queue), f.queue(core))
        old_result_before = Path(f.receipt_value['anchors']['controller_result']['path']).read_bytes()
        legacy_subprocess = controller.legacy.subprocess
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(run_controller(core, core.run, self.base/'owned', f.args,
                                            binding={'synthetic_test_fixture': True, 'scientific_workers_started': 0}))
        self.assertIs(controller.legacy.subprocess, legacy_subprocess)
        execution = json.loads((f.fresh/'controller/EXECUTION.json').read_text())
        self.assertTrue(execution['complete']); self.assertEqual(set(execution['jobs']), set(controller.ORDER))
        self.assertEqual(execution['imported_jobs'], ['A-17'])
        self.assertEqual(execution['scientific_jobs_executed_here'], controller.ORDER[1:])
        self.assertFalse((f.fresh/'controller/A-17.START.json').exists())
        self.assertEqual(json.loads((f.fresh/'controller/A-17.IMPORT.json').read_text()), core.import_record)
        self.assertEqual(json.loads((f.fresh/'controller/A-17.RESULT.json').read_text()), core.imported_result)
        imported = execution['jobs']['A-17']; self.assertTrue(imported['imported']); self.assertFalse(imported['executed_here'])
        self.assertEqual(imported['scheduled_gradient_microsteps'], 0)
        self.assertEqual(imported['origin']['scientific_cost_owner'], controller.SOURCE_EPISODE+':A-17')
        self.assertEqual(len(imported['origin']['job_changes']), 1)
        self.assertEqual(imported['process_peak_rss_bytes'], 486211584)
        a29 = json.loads((f.fresh/'controller/A-29.START.json').read_text())
        self.assertEqual(a29['worker_reservation_bytes'], 671088640)
        closure = json.loads((self.base/'owned/CLOSURE.json').read_text())
        self.assertEqual(closure['attempt_count'], 13); self.assertEqual(closure['returned_children'], 13)
        self.assertTrue(closure['accounting_complete_for_attempted_direct_workers'])
        self.assertTrue(closure['all_returned_direct_children_reaped'])
        self.assertTrue(all(row['wait4']['exit_code'] == 0 for row in closure['children']))
        self.assertEqual(Path(f.receipt_value['anchors']['controller_result']['path']).read_bytes(), old_result_before)
        self.assertEqual((f.fresh/'imports/execution04/A-17/ORIGINAL_CONTROLLER_RESULT.json').read_bytes(), old_result_before)
        self.assertEqual(json.loads((f.fresh/'ACTIVE_WORKERS.json').read_text())['workers'], [])
        self.assertTrue(all(not Path('/proc/%d' % row['pid']).exists() for row in closure['children']))


if __name__ == '__main__':
    unittest.main()
