"""Bounded synthetic correlation controls, not native product evidence.

The existing collector controls independently exercise real /proc observations.
These cases isolate the exact allowlist and rejection semantics with explicit
synthetic FD/live records, without assigning any old H3 process a parent.
"""
from copy import deepcopy
import unittest

from live_fd_correspondence import FINAL_USE_CHILD_CASE as CASE
from live_fd_correspondence import FINAL_USE_GATE as GATE
from live_fd_correspondence import verify


EXE = '/controlled-target/debug/deps/codex_hepta_contracts-123abc'
ARGV = [EXE, '--exact', CASE, '--nocapture']
IMAGE = {'device': 1, 'inode': 2, 'bytes': 4096, 'mtime_ns': 20, 'ctime_ns': 30}
SOURCE = {'commit': 'a' * 40, 'tree': 'b' * 40, 'environment_sha256': 'c' * 64}
WRAPPER = {'pid': 100, 'ppid': 1, 'start_ticks': '10',
           'argv': ['/usr/bin/python3', '/controlled-wrapper.py'],
           'actual_executable': '/usr/bin/python3',
           'image': {'device': 1, 'inode': 9, 'bytes': 8192, 'mtime_ns': 2, 'ctime_ns': 3}}


def node(pid, parent, start):
    return {'pid': pid, 'ppid': parent, 'start_ticks': start,
            'argv': list(ARGV), 'actual_executable': EXE, 'image': dict(IMAGE)}


def observe(child, parent, chain):
    return {
        'source': dict(SOURCE), 'sha256': 'd' * 64, 'actual_executable': EXE,
        **IMAGE, 'pid': child['pid'], 'start_ticks': child['start_ticks'],
        'argv': list(ARGV), 'observed_selected_tests': [CASE],
        'wrapper_pid': 100, 'wrapper_start_ticks': '10',
        'wrapper_descendant_verified': True, 'post_open_task_and_exe_verified': True,
        'held_child_and_parent_images_stable_through_retention': True,
        'process_before': deepcopy(child), 'process_after': deepcopy(child),
        'direct_parent_before': deepcopy(parent), 'direct_parent_after': deepcopy(parent),
        'ancestor_chain_before': [{k: n[k] for k in ('pid', 'ppid', 'start_ticks')} for n in chain],
        'ancestor_chain_after': [{k: n[k] for k in ('pid', 'ppid', 'start_ticks')} for n in chain],
        'relationship_observed_before_unix': 100.0,
        'relationship_observed_after_unix': 101.0, 'captured_unix': 102.0,
    }


def fixture():
    outer = node(110, 100, '20')
    child = node(120, 110, '30')
    fd = {'records': [{'source': dict(SOURCE), 'sha256': 'd' * 64,
                      'actual_executable': EXE, 'argv': list(ARGV), **IMAGE,
                      'pid': 110, 'start_ticks': '20', 'exact_test': CASE,
                      'expected_binary_target': 'codex_hepta_contracts'}],
          'expected_binary_targets': ['codex_hepta_contracts'],
          'runner_declared_binary_counts': [1]}
    live = {'records': [observe(outer, WRAPPER, [outer, WRAPPER]),
                        observe(child, outer, [child, outer, WRAPPER])]}
    return fd, live


class LiveFdCorrespondenceControls(unittest.TestCase):
    def test_exact_live_helper_binds_existing_outer_without_adding_a_case(self):
        fd, live = fixture()
        before = deepcopy(fd)
        result = verify(GATE, fd, live)
        self.assertEqual(result['errors'], [])
        self.assertEqual(len(result['direct_fd_matches']), 1)
        self.assertEqual(len(result['auxiliary_processes']), 1)
        self.assertFalse(result['auxiliary_processes'][0]['test_outcome_credit'])
        self.assertEqual(result['auxiliary_processes'][0]['parent_pid'], 110)
        self.assertEqual(fd, before)
        # Polling need not have seen the outer: its exact FD record is mandatory.
        result = verify(GATE, fd, {'records': live['records'][1:]})
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['direct_fd_matches'], [])
        self.assertEqual(len(result['auxiliary_processes']), 1)

    def test_wrong_gate_parent_argv_source_or_image_cannot_be_a_helper(self):
        for fault in ('gate', 'target', 'parent', 'case', 'argv', 'source', 'image', 'parent_image', 'missing_outer'):
            with self.subTest(fault=fault):
                fd, live = fixture()
                r = live['records'][1]
                gate = GATE
                if fault == 'gate':
                    gate = 'full-evidence-library'
                elif fault == 'target':
                    fd['expected_binary_targets'] = ['codex_hepta_evidence']
                elif fault == 'parent':
                    for key in ('direct_parent_before', 'direct_parent_after'):
                        r[key]['pid'] = 111
                    for key in ('process_before', 'process_after'):
                        r[key]['ppid'] = 111
                    for key in ('ancestor_chain_before', 'ancestor_chain_after'):
                        r[key][0]['ppid'] = 111
                        r[key][1]['pid'] = 111
                elif fault == 'case':
                    r['observed_selected_tests'] = ['final_use::tests::unrecognized_child']
                elif fault == 'argv':
                    r['argv'].append('--ignored')
                    for key in ('process_before', 'process_after'):
                        r[key]['argv'].append('--ignored')
                elif fault == 'source':
                    r['source']['environment_sha256'] = 'e' * 64
                elif fault == 'image':
                    r['inode'] += 1
                    for key in ('process_before', 'process_after'):
                        r[key]['image']['inode'] += 1
                elif fault == 'parent_image':
                    for key in ('direct_parent_before', 'direct_parent_after'):
                        r[key]['image']['inode'] += 1
                elif fault == 'missing_outer':
                    fd['records'] = []
                result = verify(gate, fd, {'records': [r]})
                self.assertTrue(result['errors'])
                self.assertEqual(result['auxiliary_processes'], [])

    def test_unstable_or_incomplete_relationships_and_extra_helpers_are_rejected(self):
        for fault in ('changed_child', 'changed_parent', 'changed_chain', 'wrong_wrapper',
                      'missing_parent', 'held_image_changed', 'duplicate', 'second_helper'):
            with self.subTest(fault=fault):
                fd, live = fixture()
                r = live['records'][1]
                if fault == 'changed_child':
                    r['process_after']['start_ticks'] = '99'
                elif fault == 'changed_parent':
                    r['direct_parent_after']['argv'] = ['/different-exec']
                elif fault == 'changed_chain':
                    r['ancestor_chain_after'][0]['ppid'] = 111
                elif fault == 'wrong_wrapper':
                    for key in ('ancestor_chain_before', 'ancestor_chain_after'):
                        r[key][-1]['start_ticks'] = '999'
                elif fault == 'missing_parent':
                    del r['direct_parent_before']
                elif fault == 'held_image_changed':
                    r['held_child_and_parent_images_stable_through_retention'] = False
                elif fault == 'duplicate':
                    live['records'].append(deepcopy(r))
                elif fault == 'second_helper':
                    extra = deepcopy(r)
                    extra['pid'] = 121
                    extra['start_ticks'] = '31'
                    for key in ('process_before', 'process_after'):
                        extra[key]['pid'] = 121
                        extra[key]['start_ticks'] = '31'
                    for key in ('ancestor_chain_before', 'ancestor_chain_after'):
                        extra[key][0]['pid'] = 121
                        extra[key][0]['start_ticks'] = '31'
                    live['records'].append(extra)
                self.assertTrue(verify(GATE, fd, live)['errors'])
        # An unobserved short process receives no invented polling attribution.
        result = verify(GATE, fixture()[0], {'records': []})
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['direct_fd_matches'], [])
        self.assertEqual(result['auxiliary_processes'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
