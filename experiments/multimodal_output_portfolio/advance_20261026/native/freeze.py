"""Freeze exact executed dependencies before opening the next source role."""

import argparse
import json
from pathlib import Path
import sys
import time

from .common import AREA, REPO, sha, write
from .dependencies import project_closure


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    settings = json.loads(args.settings.read_text())
    template = json.loads(args.template.read_text())
    runtime = json.loads(args.runtime.read_text())
    build = json.loads(args.build.read_text())
    pins = project_closure([AREA / name for name in ('evaluate.py', 'smoke.py', 'package.py', 'promote.py')])
    for path, expected in runtime['pins'].items():
        if sha(path) != expected:
            raise ValueError('Executed dependency changed before freeze: ' + path)
        pins[path] = expected
    assets = [Path(p) for p in settings['renderer_paths'].values()]
    assets += [Path(settings['image_observer']), Path(settings['event_cache'])]
    event_cache = json.loads(Path(settings['event_cache']).read_text())
    for name in event_cache['component_manifest_sha256']:
        manifest = Path(settings['asr_assets']) / ('whisper-' + name) / 'manifest.json'
        assets.append(manifest)
        for row in json.loads(manifest.read_text())['sources']:
            assets.append(manifest.parent / row['path'])
    assets.extend(Path(row['actual_wave_file']) for row in event_cache['events'])
    assets.extend(Path(path) for path in event_cache['frozen_source_sha256'])
    assets += [args.binary, args.build, args.runtime, args.settings, args.template,
               AREA / 'PROTOCOL.json', AREA / 'REFERENCE_SELECTION.json',
               args.calibration / 'REPORT.json', args.calibration / 'old-development-public.npz',
               args.calibration / 'old-development-offline-labels.json', Path(sys.executable).resolve()]
    assets += [Path(template[k]) for k in ('weights_path', 'calibration_path', 'verification_path', 'likelihood_path', 'observer_path')]
    assets += [Path(row['path']) for row in build['dependencies'].values()]
    for source in (args.build.parent / 'src').glob('*.rs'): assets.append(source)
    assets.extend(AREA.glob('*.rs'))
    for path in assets: pins[str(path.resolve())] = sha(path)
    # Include the exact launcher and reader source as well as models; the
    # source gate verifies every pin before reading the prospective images.
    pins[str(Path(__file__).resolve())] = sha(__file__)
    write(args.output / 'TEMPLATES.json', {'dynamic': str(args.template), 'fixed_late': str(args.template)})
    pins[str((args.output / 'TEMPLATES.json').resolve())] = sha(args.output / 'TEMPLATES.json')
    protocol = {'schema': 'hepta.advance.native-prospective-execution.v1', 'frozen_unix_ns': time.time_ns(),
        'phase': 'qualification', 'source_roles': ['qualification_id', 'qualification_ood'],
        'source_allocation_sha256': sha(args.allocation), 'frozen_candidate_sha256': dict(sorted(pins.items())),
        'task_seed': 419731, 'bootstrap_seed': 46117, 'bootstrap_replicates': 10000,
        'native_protocol_sha256': sha(AREA / 'PROTOCOL.json'), 'primary_reference': 'fixed_late',
        'selection_rule': 'Frozen old-development strongest fixed reference; no new-source adaptation',
        'new_source_outcomes_opened': False, 'policy_qualification_is_separate': True,
        'old_baseline_evidence': 'Offline composition of actual old CNN observations and actual finite renderer endpoint observations, not extra original-owner runs'}
    write(args.output / 'QUALIFICATION_SPEC.json', protocol)
    write(AREA / 'FROZEN_QUALIFICATION.json', {'spec_path': str(args.output / 'QUALIFICATION_SPEC.json'),
        'spec_sha256': sha(args.output / 'QUALIFICATION_SPEC.json'), 'exact_dependency_count': len(pins),
        'binary_sha256': sha(args.binary), 'weights_sha256': template['pins']['weights'],
        'calibration_sha256': template['pins']['calibration'], 'native_protocol_sha256': sha(AREA / 'PROTOCOL.json'),
        'new_sources_opened': False, 'models_and_native_gate_frozen_before_new_source': True})
    print(json.dumps({'spec': str(args.output / 'QUALIFICATION_SPEC.json'), 'sha256': sha(args.output / 'QUALIFICATION_SPEC.json'),
                      'exact_dependency_count': len(pins)}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('template', 'runtime', 'build', 'binary', 'settings', 'calibration', 'allocation', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    run(p.parse_args())
