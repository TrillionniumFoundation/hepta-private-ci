"""Real GitHub transport exercise: seventeen barriers and a later terminal packet."""

import argparse
import json
import os
from pathlib import Path
import time

from artifact_transport import LABELS, archive_barrier, archive_terminal_metadata, descriptor, write_json


def stages(root):
    config = descriptor(root / 'SYNTHETIC_CONFIG.json')
    previous, acknowledgments, costs = None, [], []
    for sequence, label in enumerate(LABELS, 1):
        source = root / 'sources' / label
        source.mkdir(parents=True)
        write_json(source / 'state.json', {'synthetic': True, 'sequence': sequence, 'label': label})
        (source / 'payload.bin').write_bytes(bytes(range(256)) * (sequence + 1))
        paths = {'synthetic/' + label + '/state.json': source / 'state.json',
                 'synthetic/' + label + '/payload.bin': source / 'payload.bin',
                 'control/SYNTHETIC_CONFIG.json': root / 'SYNTHETIC_CONFIG.json'}
        paths.update({f'prior_acks/{index:02d}.json': Path(item['path']) for index, item in enumerate(acknowledgments, 1)})
        binding = {'execution_episode': 'execution07_actions_20261031', 'sequence': sequence, 'label': label,
                   'pipeline_config': config, 'completed_jobs': list(LABELS[:min(sequence, 14)]),
                   'previous_ack': previous, 'synthetic_only': True}
        result = archive_barrier(label, paths, binding, root / 'barriers' / label)
        previous = result['ack']
        acknowledgments.append(previous)
        costs.append(result['cost'])
        print(json.dumps({'synthetic_barrier': label, 'artifact_id': result['artifact']['id'],
                          'verified_files': result['items_verified']}), flush=True)
    write_json(root / 'STAGES_COMPLETE.json', {'schema': 'hepta.synthetic.transport-stages.v1',
               'scientific_inputs_opened': False, 'acknowledgments': acknowledgments, 'costs': costs})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = args.output.absolute()
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / 'SYNTHETIC_CONFIG.json', {'schema': 'hepta.synthetic.transport-config.v1',
               'science_admission': False, 'labels': LABELS, 'source_head': os.environ.get('GITHUB_SHA')})
    start = time.monotonic()
    pid = os.fork()
    if pid == 0:
        try:
            os.setsid()
            stages(root)
            os._exit(0)
        except BaseException as error:
            write_json(root / 'FAILED.json', {'synthetic': True, 'error_type': type(error).__name__,
                                             'no_automatic_retry': True})
            os._exit(1)
    waited, status, usage = os.wait4(pid, 0)
    exit_code = os.waitstatus_to_exitcode(status)
    write_json(root / 'OUTER_WAIT4.json', {'schema': 'hepta.synthetic.outer-wait4.v1',
               'pid': pid, 'waited_pid': waited, 'exit_code': exit_code,
               'wall_seconds': time.monotonic() - start, 'user_cpu_seconds': usage.ru_utime,
               'system_cpu_seconds': usage.ru_stime, 'peak_rss_bytes': usage.ru_maxrss * 1024,
               'scope': 'Inclusive synthetic seventeen-barrier child and descendants; do not add nested costs twice.'})
    if exit_code != 0:
        raise SystemExit(exit_code)
    complete = json.loads((root / 'STAGES_COMPLETE.json').read_text())
    binding = {'execution_episode': 'execution07_actions_20261031', 'sequence': 18, 'label': 'terminal_metadata',
               'pipeline_config': descriptor(root / 'SYNTHETIC_CONFIG.json'), 'completed_jobs': list(LABELS[:14]),
               'previous_ack': complete['acknowledgments'][-1], 'synthetic_only': True}
    paths = {'terminal/STAGES_COMPLETE.json': root / 'STAGES_COMPLETE.json',
             'terminal/OUTER_WAIT4.json': root / 'OUTER_WAIT4.json',
             'control/SYNTHETIC_CONFIG.json': root / 'SYNTHETIC_CONFIG.json'}
    paths.update({f'prior_acks/{index:02d}.json': Path(item['path'])
                  for index, item in enumerate(complete['acknowledgments'], 1)})
    terminal = archive_terminal_metadata(paths, binding, root / 'terminal')
    write_json(root / 'TRANSPORT_SYNTHETIC_PASS.json', {'schema': 'hepta.synthetic.transport-pass.v1',
               'scientific_inputs_opened': False, 'science_admission': False, 'barriers': len(LABELS),
               'terminal': terminal, 'outer_wait4': descriptor(root / 'OUTER_WAIT4.json')})
    print(json.dumps({'synthetic_transport': 'PASS', 'barriers': len(LABELS),
                      'terminal_artifact_id': terminal['artifact']['id'], 'science_admission': False}))


if __name__ == '__main__':
    main()
