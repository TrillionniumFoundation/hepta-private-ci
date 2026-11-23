"""Run a typed two-stage HIA policy against the two archived E4 replay panels."""

import argparse
import ctypes
import hashlib
import itertools
import json
import platform
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from hepta import __version__ as hepta_version
from hepta.hia_agent_assembly import assemble_program
from hepta.hia_program import HIAProgramRejected, execute_program


HEPTA_COMMIT = '8ba46fc7a112fc220cdcbbd48dc5d24fda76a738'
E4_COMMIT = 'e5072455d6fca43a447feae03a1f102d0b0ca402'
POLICY_SHA = 'de582bab5a35eff9dffb3953a5e97fe141542fda4c255e048c9659eca4190f54'
REPLAY_SHA = 'b39249e13f58fa05f2455f551c31c7354b2d2bf893204ec3a753798ce9f37bf9'
REASONS = {'invalid_test_patch': 1, 'business_tests_failed': 2, 'business_tests_passed': 3}
LIMITS = {'max_steps': 16, 'max_heap_bytes': 0, 'max_call_depth': 1}


def require(test, message):
    if not test:
        raise ValueError(message)


def load_pinned(path, expected):
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, f'Input hash mismatch: {path.name}')
    return json.loads(raw)


def encode_reason(text):
    if type(text) is not str:
        raise TypeError('A verifier reason must be a string')
    return REASONS.get(text, 0)


def native_entries(program, directory):
    from hepta.hia_program_native import build_program_machine

    path = Path(directory) / 'route.so'
    receipt = build_program_machine(program, path, linker='ld')
    require(receipt['ok'] and sorted(receipt['exports']) == ['route', 'select_result'],
            'Native build did not produce both expected exports')
    require(hashlib.sha256(path.read_bytes()).hexdigest() == receipt['artifact_sha256'],
            'Native output differs from its build receipt')
    image = ctypes.CDLL(str(path))
    image.route.argtypes = [ctypes.c_uint8]
    image.select_result.argtypes = [ctypes.c_bool, ctypes.c_bool]
    # Read the whole result byte and compare the actual C ABI output, including bool.
    image.route.restype = image.select_result.restype = ctypes.c_uint8
    fields = ('schema', 'target', 'profile', 'exports', 'implementation_sha256',
              'machine_text_sha256', 'object_sha256', 'artifact_sha256', 'artifact_bytes',
              'machine_text_bytes', 'toolchain', 'flags', 'function_frames')
    return image, {k: receipt[k] for k in fields}


def compare(root, native=False):
    policy = load_pinned(root / 'route_policy.json', POLICY_SHA)
    replay = load_pinned(root / 'REPLAY.json', REPLAY_SHA)
    require(replay['policy_sha256'] == POLICY_SHA, 'Replay must bind the policy being compared')
    source = Path(__file__).with_name('route.hepta').read_bytes()
    program = assemble_program(source)
    trace = {}
    panels = {}
    with TemporaryDirectory() as tmp:
        image, build = native_entries(program, tmp) if native else (None, None)
        totals = Counter()

        def run(entry, args):
            report = execute_program(program, entry, args, **LIMITS)
            require(report['status'] == 'returned' and not any(report['resources'].values()),
                    'Expected a successful allocation-free VM invocation')
            expected_type = bool if entry == 'route' else int
            value = report['result']
            require(type(value) is expected_type, 'Unexpected result type')
            if image is not None:
                # Only validated, in-range arguments cross the foreign interface.
                actual_byte = getattr(image, entry)(*args)
                require(actual_byte == int(value), f'Native/VM mismatch: {entry} {args}')
            totals[entry] += 1
            trace.setdefault(entry, set()).add(report['steps'])
            return value

        for panel, config in [('b2', policy['first_panel']), ('upstream', policy['transfer_panel'])]:
            summaries = []
            for row in replay['panels'][panel]['rows']:
                clean = run('route', [encode_reason(row['first_reason'])])
                # The first entry has no access to the recorded second-turn outcomes.
                adapter = config['other'] if clean else config['first']
                second_origin = adapter * 2 + ('/0' if clean else '/1')
                second_ok = row['clean_other_ok'] if clean else row['same_repair_ok']
                require(second_origin == row['second_origin'] and second_ok is row['second_ok'],
                        'Route origin or recorded second verdict mismatch')
                choice = run('select_result', [row['first_ok'], second_ok])
                require((choice == 2) is row['first_ok'] and (choice != 0) is row['retained'],
                        'Earliest selected turn or its verdict differs')
                summaries.append({'task': row['task'], 'reason_code': encode_reason(row['first_reason']),
                                  'second_origin': second_origin, 'selection_code': choice})
            require(len(summaries) == 6, 'Six paired tasks required in each exposed panel')
            panels[panel] = summaries

        # Exhaust the scalar input domains, including previously unseen reason codes.
        for reason in range(256):
            require(run('route', [reason]) is (reason == REASONS[policy['if_equals']]),
                    'The fallback differs from the fixed comparison')
        for first, second in itertools.product((False, True), repeat=2):
            expected = 2 if first else int(second)
            require(run('select_result', [first, second]) == expected, 'Incorrect turn selection')
        require(encode_reason('unrecognized_reason') == 0, 'Unknown string must use the else branch')
        try:
            encode_reason(None)
        except TypeError:
            pass
        else:
            raise ValueError('Host accepted a non-string reason')

        invalid = [('route', [True]), ('route', [-1]), ('route', [256]), ('route', ['1']),
                   ('select_result', [1, False]), ('select_result', [True, 0]), ('select_result', [True])]
        for entry, args in invalid:
            try:
                execute_program(program, entry, args, **LIMITS)
            except HIAProgramRejected as exc:
                require(exc.code == 'E_HIA_INPUT', 'Unexpected reason for invalid input rejection')
            else:
                raise ValueError(f'VM accepted a wrong type, range, or arity: {entry} {args}')
    return {
        'hepta_commit': HEPTA_COMMIT, 'hepta_version': hepta_version,
        'python_version': platform.python_version(), 'e4_input_commit': E4_COMMIT,
        'assembly_sha256': hashlib.sha256(source).hexdigest(), 'core_sha256': program.sha256,
        'policy_sha256': POLICY_SHA, 'replay_sha256': REPLAY_SHA, 'reason_encoding': REASONS,
        'unknown_reason_code': 0, 'selection_encoding': {'0': 'second_failed', '1': 'second_passed',
                                                        '2': 'first_passed'},
        'panels': panels, 'positive_evaluations_per_backend': dict(totals),
        'vm_steps_per_entry': {k: sorted(v) for k, v in trace.items()}, 'vm_limits': LIMITS,
        'vm_wrong_inputs_rejected': len(invalid), 'host_non_string_reason_rejected': True,
        'native_build': build, 'new_model_calls': 0, 'new_task_verifier_calls': 0,
        'new_independent_tasks': 0, 'new_training_runs': 0,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('panel_directory', type=Path, nargs='?', default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--native', action='store_true', help='Also execute the direct Linux x86-64 machine backend')
    args = parser.parse_args()
    print(json.dumps(compare(args.panel_directory, args.native), indent=2, sort_keys=True))
