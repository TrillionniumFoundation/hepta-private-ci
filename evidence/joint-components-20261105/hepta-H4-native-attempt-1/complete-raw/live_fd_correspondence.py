"""Correlate bounded live observations with the existing exact FD ledger.

The one fixed FinalUse self-spawn helper is auxiliary process evidence only.
It never adds a test outcome or substitutes for a missing outer FD record.
This protocol requires the new contemporaneous observations and cannot be used
to assign a parent to an older H3 polling record.
"""
import math


FINAL_USE_GATE = 'final-use-profile-controls'
FINAL_USE_TARGET = 'codex_hepta_contracts'
FINAL_USE_CHILD_CASE = 'final_use::tests::killed_owner_releases_lock_but_keeps_claim'
IMAGE_FIELDS = ('device', 'inode', 'bytes', 'mtime_ns', 'ctime_ns')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def image(record):
    return {field: record[field] for field in IMAGE_FIELDS}


def stable_observation(record):
    child = record['process_before']
    parent = record['direct_parent_before']
    require(child == record['process_after'], 'child identity or argv changed')
    require(parent == record['direct_parent_after'], 'direct parent identity or argv changed')
    require(child['pid'] == record['pid'] and child['start_ticks'] == record['start_ticks'],
            'record does not identify the observed child')
    require(child['argv'] == record['argv'] and child['actual_executable'] == record['actual_executable'],
            'record argv or executable differs from live observations')
    require(child['image'] == image(record), 'record image differs from opened child image')
    require(child['ppid'] == parent['pid'] and parent['pid'] != child['pid'],
            'direct parent is not the observed child PPID')
    require(record['wrapper_descendant_verified'] is True
            and record['post_open_task_and_exe_verified'] is True
            and record['held_child_and_parent_images_stable_through_retention'] is True,
            'opened images or wrapper relationship were not verified')
    before = record['relationship_observed_before_unix']
    after = record['relationship_observed_after_unix']
    require(all(isinstance(v, (int, float)) and math.isfinite(v)
                for v in (before, after, record['captured_unix']))
            and 0 < before <= after <= record['captured_unix'],
            'relationship observation timestamps are invalid')
    chain = record['ancestor_chain_before']
    require(chain == record['ancestor_chain_after'] and 2 <= len(chain) <= 64,
            'ancestor chain changed or was incomplete')
    require(len({node['pid'] for node in chain}) == len(chain), 'ancestor chain repeats a PID')
    for node in chain:
        require(isinstance(node['pid'], int) and node['pid'] > 1
                and isinstance(node['ppid'], int)
                and isinstance(node['start_ticks'], str) and node['start_ticks'].isdigit()
                and int(node['start_ticks']) > 0, 'ancestor identity is malformed')
    for left, right in zip(chain, chain[1:]):
        require(left['ppid'] == right['pid'], 'ancestor chain skips a parent')
    require(chain[0] == {k: child[k] for k in ('pid', 'ppid', 'start_ticks')}
            and chain[1] == {k: parent[k] for k in ('pid', 'ppid', 'start_ticks')},
            'ancestor chain disagrees with child or direct parent observation')
    require((chain[-1]['pid'], chain[-1]['start_ticks'])
            == (record['wrapper_pid'], record['wrapper_start_ticks']),
            'ancestor chain does not end at the exact bound wrapper')
    return child, parent


def match_image_and_source(observed, outer):
    require(observed['source'] == outer['source'], 'source or execution configuration differs')
    require(observed['sha256'] == outer['sha256'] and image(observed) == image(outer),
            'actual image differs from the exact FD image')
    require(observed['actual_executable'] == outer['actual_executable'],
            'actual executable path differs from the exact FD image')


def verify(gate, artifacts, live):
    result = {
        'schema': 'hepta-live-fd-correspondence-v1', 'gate': gate,
        'direct_fd_matches': [], 'auxiliary_processes': [], 'errors': [],
        'scope': 'Only observed live processes are correlated. A recognized helper is not an additional case; polling can miss short processes. No old-run parent attribution.',
    }
    records = artifacts['records']
    seen = set()
    for observed in live['records']:
        key = observed.get('pid'), observed.get('start_ticks')
        try:
            require(key not in seen, 'duplicate live process identity')
            seen.add(key)
            child, parent = stable_observation(observed)
            exact = [r for r in records if (r['pid'], r['start_ticks']) == key]
            if exact:
                require(len(exact) == 1, 'live PID has more than one exact FD record')
                outer = exact[0]
                match_image_and_source(observed, outer)
                require(observed['argv'] == outer['argv']
                        and observed['observed_selected_tests'] == [outer['exact_test']],
                        'live exact case argv differs from its FD record')
                result['direct_fd_matches'].append({'pid': key[0], 'start_ticks': key[1],
                                                   'exact_test': outer['exact_test']})
                continue
            require(gate == FINAL_USE_GATE
                    and artifacts['expected_binary_targets'] == [FINAL_USE_TARGET]
                    and artifacts['runner_declared_binary_counts'] == [1],
                    'an unmatched live process is not allowed for this gate or target')
            require(observed['observed_selected_tests'] == [FINAL_USE_CHILD_CASE],
                    'unmatched live process is not the one declared helper case')
            parents = [r for r in records
                       if r['exact_test'] == FINAL_USE_CHILD_CASE
                       and (r['pid'], r['start_ticks']) == (parent['pid'], parent['start_ticks'])]
            require(len(parents) == 1, 'helper direct parent is not its unique exact outer FD')
            outer = parents[0]
            require(outer['expected_binary_target'] == FINAL_USE_TARGET,
                    'helper outer FD belongs to a different target')
            match_image_and_source(observed, outer)
            expected_argv = [outer['actual_executable'], '--exact', FINAL_USE_CHILD_CASE, '--nocapture']
            require(child['argv'] == parent['argv'] == outer['argv'] == expected_argv,
                    'helper or outer complete argv differs from the fixed self-spawn contract')
            require(parent['actual_executable'] == outer['actual_executable']
                    and parent['image'] == image(outer),
                    'opened direct-parent image differs from the outer FD image')
            require(result['auxiliary_processes'] == [], 'more than one self-spawn helper was observed')
            result['auxiliary_processes'].append({
                'pid': child['pid'], 'start_ticks': child['start_ticks'],
                'parent_pid': parent['pid'], 'parent_start_ticks': parent['start_ticks'],
                'exact_test': FINAL_USE_CHILD_CASE, 'sha256': observed['sha256'],
                'bytes': observed['bytes'], 'test_outcome_credit': False,
                'image_binding': 'child and held direct-parent FDs identify the same file object; its digest also matches the independent outer FD record',
                'relationship_observed_before_unix': observed['relationship_observed_before_unix'],
                'relationship_observed_after_unix': observed['relationship_observed_after_unix'],
                'scope': 'Direct relationship at the two live observation points; neither task is claimed live at hash/copy completion',
            })
        except (KeyError, TypeError, ValueError) as error:
            result['errors'].append({'pid': key[0], 'start_ticks': key[1], 'error': str(error)})
    return result
