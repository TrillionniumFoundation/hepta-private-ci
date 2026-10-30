"""Pure/local archive metadata tests. No upload, remote readback or ACK publish."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from . import archive_io as api


class ArchiveMetadataTests(unittest.TestCase):
    def setUp(self):
        target = os.environ.get('HEPTA_ARCHIVE_IO_TEST_OUTPUT')
        if target:
            self.base = Path(target)/self._testMethodName; self.base.mkdir(parents=True, exist_ok=False)
        else:
            temporary = tempfile.TemporaryDirectory(prefix='archive-io-metadata-'); self.addCleanup(temporary.cleanup); self.base = Path(temporary.name)
        self.ops = self.base/'ops'; self.ops.mkdir()
        self.root = self.ops/'root_archive_io'
        for key, value in (('OPS', self.ops), ('ROOT', self.root)):
            patch = mock.patch.object(api, key, value); patch.start(); self.addCleanup(patch.stop)
        (self.base/'SYNTHETIC_TEST_FIXTURE.json').write_text(json.dumps({'remote_actions_executed': 0,
            'scope': 'Synthetic metadata fixtures only; no actual Library identities, remote receipts or ACK publication.'})+'\n')
        self.stage = self.ops/'durable/01_A-17'; self.stage.mkdir(parents=True)
        self.items = []
        for name in ('part-000.tar.gz', 'part-001.tar.gz', 'MANIFEST.json', 'VERIFIED.json', 'ARCHIVE_COST.json'):
            path = self.stage/name; path.write_bytes(('synthetic-'+name+'\n').encode()); self.items.append(api.descriptor(path))
        request = {'schema': 'hepta.fullstudy.library-archive-request.1',
                   'state': 'AWAITING_EXTERNAL_UPLOAD_AND_REMOTE_READBACK',
                   'required_ack_schema': 'hepta.fullstudy.library-archive-ack.1',
                   'binding': {'execution_episode': api.EPISODE, 'sequence': 1, 'label': 'A-17', 'completed_jobs': ['A-17']},
                   'items': self.items}
        self.request = api.write_json(self.stage/'REQUEST.json', request)
        self.request_input = self.base/'REQUEST_DESCRIPTOR.json'; api.write_json(self.request_input, self.request)
        self.identity = {'pid': os.getpid(), 'start_ticks': '1', 'process_group': os.getpgid(0), 'session': os.getsid(0), 'state': 'R'}
        api.write_json(self.ops/'STATUS.json', {'schema': 'hepta.fullstudy.execution05-status.1',
            'execution_episode': api.EPISODE, 'identity': self.identity, 'pid': os.getpid(),
            'awaiting_durable': {'request': self.request, 'ack_path': str(self.stage/'ACK.json')}})
        self.work = self.root/'01_A-17'

    def prepare(self):
        args = SimpleNamespace(request_descriptor=str(self.request_input), directory_id='synthetic-directory-not-a-real-service-id', work_directory=str(self.work))
        with contextlib.redirect_stdout(io.StringIO()):
            api.prepare_upload(args)
        return args

    def test_actual_source_and_four_official_helper_hashes_are_bound(self):
        value = api.code_identity()
        self.assertEqual(value['frozen_archive']['sha256'], api.ARCHIVE_SHA)
        self.assertEqual(value['frozen_supervisor']['sha256'], api.SUPERVISOR_SHA)
        self.assertEqual(value['frozen_external_step']['sha256'], api.EXTERNAL_STEP_SHA)
        observed = {Path(row['path']).name: row['sha256'] for row in value['official_library_helpers']}
        self.assertEqual(observed, api.HELPER_SHA)
        self.assertNotEqual(Path(value['frozen_archive']['path']).parent, api.OWN)

    def test_old_episode_request_is_rejected_in_new_paths(self):
        value = api.read(self.request['path']); value['binding']['execution_episode'] = 'execution04_durable_20261030'
        path = self.stage/'REQUEST.json'; path.write_text(json.dumps(value)+'\n')
        with self.assertRaisesRegex(ValueError, 'another execution episode'):
            api.request_value(api.descriptor(path))

    def test_prepare_preserves_order_of_all_five_items_and_cannot_repeat(self):
        args = self.prepare()
        expected = {'uploads': [{'local_path': row['path'], 'purpose': 'create_library_file', 'library_artifact_type': 'other',
                                'directory_id': args.directory_id} for row in self.items]}
        self.assertEqual(api.read(self.work/'UPLOAD_REQUEST.json'), expected)
        bound = api.read(self.work/'BOUND_REQUEST.json')
        self.assertEqual(bound['request'], self.request)
        self.assertEqual(bound['supervisor_identity'], api.stable_process_identity(self.identity))
        self.assertFalse((self.stage/'ACK.json').exists())
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'new work directory'):
            api.prepare_upload(args)

    def test_bound_helper_code_change_is_rejected_before_handoff(self):
        self.prepare()
        with mock.patch.object(api, 'code_identity', return_value={'changed': True}):
            with self.assertRaisesRegex(ValueError, 'Bound operational/helper code changed'):
                api.work_bound(self.work)

    def test_unknown_upload_result_is_rejected_without_readback_or_ack(self):
        self.prepare(); bound = api.read(self.work/'BOUND_REQUEST.json'); req = api.read(self.request['path'])
        rows = [{'local_path': row['path'], 'purpose': 'create_library_file', 'status': 'succeeded',
                 'local_metadata_applied': True, 'file_id': 'synthetic-file-'+str(i), 'file_name': Path(row['path']).name,
                 'library_file_id': 'synthetic-library-'+str(i), 'current_version_number': 0}
                for i, row in enumerate(self.items)]
        rows[0]['status'] = 'unknown'
        stdout = self.base/'SYNTHETIC_UPLOAD_STDOUT.json'; api.write_json(stdout, {'results': rows})
        with mock.patch.object(api, 'step', return_value=({'synthetic_wait4_fixture': True}, api.descriptor(stdout))):
            with self.assertRaisesRegex(ValueError, 'failed, uncertain'):
                api.upload_evidence(self.work, bound, req, self.base/'unused_wait4')
        self.assertFalse((self.work/'READBACK_PLAN.json').exists())
        self.assertFalse((self.stage/'ACK.json').exists())

    def test_version_zero_is_valid_but_unknown_version_is_rejected(self):
        row = {'file_id': 'synthetic-f', 'file_name': 'x.bin', 'library_file_id': 'synthetic-l', 'current_version_number': 0}
        self.assertEqual(api.remote(row), {'file_id': 'synthetic-f', 'file_name': 'x.bin', 'library_file_id': 'synthetic-l', 'version': 0})
        for invalid in (None, -1, True):
            with self.assertRaisesRegex(ValueError, 'current_version_number'):
                api.remote({**row, 'current_version_number': invalid})

    def test_materialization_response_envelopes_and_uncertainty_are_checked(self):
        path = self.base/'MATERIALIZATION_RESPONSE.json'
        payload = {'transfers': [], 'synthetic_test_fixture': True}
        for response in ({'structuredContent': payload}, {'structuredContent': {'result': payload}},
                         {'content': [{'type': 'text', 'text': json.dumps(payload)}]}):
            path.write_text(json.dumps(response)); self.assertEqual(api.materialize_payload(path), payload)
        for response in ({'isError': True}, {'structuredContent': {'warnings': ['synthetic warning']}},
                         {'structuredContent': {'unavailable_items': ['synthetic missing']}}):
            path.write_text(json.dumps(response))
            with self.assertRaises(ValueError):
                api.materialize_payload(path)

    def test_ack_publication_requires_explicit_cli_flag(self):
        values = []
        for extra in ([], ['--publish-ack']):
            with mock.patch.object(sys, 'argv', ['archive_io.py', 'ack', '--work-directory', str(self.work), *extra]), \
                 mock.patch.object(api, 'make_ack', side_effect=lambda args: values.append(args.publish_ack)):
                api.main()
        self.assertEqual(values, [False, True])
        self.assertFalse((self.stage/'ACK.json').exists())


if __name__ == '__main__':
    unittest.main()
