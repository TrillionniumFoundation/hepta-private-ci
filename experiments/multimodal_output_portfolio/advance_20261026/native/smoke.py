"""Actual old-source four-modal owner, late evidence, recovery and numeric history.

Transport faults are explicit engineering probes. They are excluded from
qualification and source efficacy evaluation and do not change model weights.
"""

import argparse
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch

from ...closure_20261025.media.coherent import motion_targets
from ...next_20261025.joint.model import PublicTask
from ...next_20261025.media.audio_sources import load_audio
from ...v6.data import Observation
from ...v7.data import make_batch
from ...v7.sources import load_roles
from ...v7_media.corpus import speech_spectrum
from .calibrate import calibrated
from .client import Native, descriptor
from .common import AREA, sha, write
from .episode import run_episode
from .host import PortfolioHost
from .dependencies import runtime_snapshot
from .evaluate import score_closed


def run(args):
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    args.output.mkdir(parents=True, exist_ok=False)
    began = time.perf_counter_ns()
    settings = json.loads(args.settings.read_text())
    template = json.loads(args.template.read_text())
    source = json.loads((args.calibration / 'old-development-offline-labels.json').read_text())['source']
    rows = source['cases_identity']
    if source['role'] != 'development' or source['new_confirmation_sources_opened']:
        raise ValueError('Old source development only')
    write(args.output / 'REGISTRATION.json', {'schema': 'hepta.advance.actual-native-smoke.v1',
        'created_unix_ns': time.time_ns(), 'new_sources_used': False,
        'transport_probes': {'positive': 'Unchanged actual generated caption',
            'zero': 'After generation replace caption with a different valid pair',
            'negative': 'After generation truncate caption into an invalid string'},
        'proxy': '1-invalid_caption-any_crossmodal_disagreement; no target truth used',
        'faults_affect_formal_evaluation': False, 'expected_policy_benefit': None,
        'binary_sha256': sha(args.binary), 'template_sha256': sha(args.template),
        'source_pins': {str(p): sha(p) for p in AREA.glob('*.py')}})
    host = PortfolioHost(settings, args.output / 'event-observer')
    shared = Path(settings['shared'])
    corpus = load_roles(shared / 'abc2-assets/mnist', shared / 'abc2-runs/source-recovery-001/source-manifest.json', roles=('development',))
    audio_rows = json.loads(Path(settings['audio_allocation']).read_text())['roles']['qualification']
    by_sha = {row['sha256']: row for row in audio_rows}
    audio_by_pair = {row['pair']: row for row in rows if row['route'] == 'audio'}

    def public_case(index):
        row = rows[index]
        pair = row['pair']
        start = pair // 16 * 16
        batch = make_batch(corpus, 'development', 16, source['seed'] + start, view=row['view'], offset=start)
        k = pair - start
        if list(batch.source_ids[k]) != row['image_source_ids']:
            raise ValueError('Old source reconstruction differs from frozen public cache')
        observation = Observation(batch.observation.pixels[k:k+1], batch.observation.mask[k:k+1], batch.observation.text_tokens[k:k+1])
        late = [by_sha[s] for s in audio_by_pair[pair]['speech_sources']]
        route = row['route']
        if route == 'image': task = PublicTask(route, observation=observation)
        elif route == 'text': task = PublicTask(route, text_digits=batch.target.labels[k:k+1].clone())
        elif route == 'audio':
            waves = load_audio(settings['audio_root'], [{'path': r['path'], 'sha256': r['sha256']} for r in late])
            task = PublicTask(route, spectrum=speech_spectrum(waves).unsqueeze(0))
        else: task = PublicTask(route, video=motion_targets(batch.target.pixels[k:k+1]))
        return task, late if route in ('image', 'video') else None

    outputs = []
    for route in ('image', 'text', 'audio', 'video'):
        index = next(i for i, row in enumerate(rows) if row['route'] == route)
        task, late = public_case(index)
        outputs.append(run_episode(host, task, binary=args.binary, template=template,
            directory=args.output / ('route-' + route), case_id='smoke.' + route,
            source_group='old.development.pair0', policy='dynamic',
            source_audio_root=settings['audio_root'], source_audio_rows=late, recover=route == 'text'))

    # Select an old public uncertainty case, without inspecting future waveform
    # bytes. This is engineering exercise coverage, not a source efficacy sample.
    public = np.load(args.calibration / 'old-development-public.npz')
    calibration = json.loads(Path(template['calibration_path']).read_text())
    offline = json.loads((args.calibration / 'old-development-offline-labels.json').read_text())
    acquisition_p = {r['index']: r['raw'] for r in offline['acquisitions']}
    candidates = [i for i, row in enumerate(rows) if row['route'] == 'image'
                  and calibrated(public['law'][i].max(), calibration['roles']['emit']) < .75
                  and calibrated(acquisition_p[i], calibration['roles']['acquire']) >= .75]
    if not candidates: raise ValueError('No old uncertainty case for genuine acquisition smoke')
    task, late = public_case(candidates[0])
    acquisition = run_episode(host, task, binary=args.binary, template=template,
        directory=args.output / 'external-audio', case_id='smoke.external', source_group='old.development.external',
        policy='fixed_late', source_audio_root=settings['audio_root'], source_audio_rows=late, recover=True)
    outputs.append(acquisition)

    # Same subsequent literal public input after three actually delivered byte histories.
    task = PublicTask('text', text_digits=torch.tensor([[3, 1]]))
    features, _ = host.encode(task)
    probes = []
    for name, fault in (('positive', None), ('zero', 'valid_caption_substitution'), ('negative', 'caption_truncation')):
        directory = args.output / ('numeric-' + name)
        spec = descriptor(template, directory, 'probe.' + name, 'old.literal.same-input', 'fixed_initial')
        native = Native(args.binary, spec, directory / 'owner')
        first = native.decide(name + '.prior', name + '.episode0', features, 'text', 1)
        receipt, _ = host.emit(first, directory / 'media', directory / 'ACTUAL_PRIOR.json', fault)
        committed = native.observe(first, directory / 'ACTUAL_PRIOR.json')
        second = native.decide(name + '.same', name + '.episode1', features, 'text', 1)
        write(directory / 'SAME_INPUT_DECISION.json', second)
        if second['decision']['selected_action'] is not None:
            native.checked({'kind': 'cancel', 'request_id': name + '.same', 'decision_digest': second['decision_digest']})
        closed = native.close()
        probes.append({'history': name, 'actual_proxy_q32': receipt['utility_q32'],
            'original_caption_sha256': receipt['original_generated_caption_sha256'],
            'delivered_caption_sha256': receipt['media_sha256']['text'],
            'modulator': committed['status']['modulator'], 'same_input_selected': second['decision']['selected_action'],
            'same_input_ticks': second['decision']['ticks'], 'closed': closed})
    host.portfolio.assert_frozen()
    if not callable(score_closed):
        raise ValueError('Final offline scorer import was not captured')
    runtime_snapshot(args.output / 'RUNTIME_DEPENDENCIES.json')
    report = {'schema': 'hepta.advance.actual-native-smoke-result.v1', 'new_sources_used': False,
        'actual_bundles': sum(r['actual_output_bundle'] for r in outputs) + len(probes),
        'four_route_initial_outputs': {r['route']: r['actual_output_bundle'] for r in outputs[:4]},
        'external_audio_actually_acquired': acquisition['actual_external_acquisitions'],
        'external_audio_final_action': acquisition['final_action'], 'numeric_history': probes,
        'numeric_history_choices_changed': len({r['same_input_selected'] for r in probes}) > 1,
        'numeric_history_is_true_target_utility': False, 'policy_benefit_claimed': False,
        'actual_encoder_decoder_original_owner_NDU_cycle': True,
        'new_source_qualification': False, 'authority': 'deny_all', 'daemon_deployment': False,
        'wall_ns': time.perf_counter_ns() - began,
        'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
    write(args.output / 'REPORT.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'numeric_history'}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'template', 'calibration', 'settings', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    run(p.parse_args())
