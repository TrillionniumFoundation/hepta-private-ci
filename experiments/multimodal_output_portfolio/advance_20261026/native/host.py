"""Actual public encoders, renderer, codecs and observations serving native decisions.

This module has no hidden-target argument. Waveform acquisition is performed
only after a native pending acquire decision. Python executes the frozen media
components; Rust executes posterior/value layers and the unmodified owner.
"""

import json
from pathlib import Path
import time

import numpy as np
import torch

from ...next_20261025.media.audio_sources import load_audio
from ...next_20261025.media.repair.cache_audit import CachedFrozenAudit
from ...next_20261025.media.runtime import observe_bundle
from ...v7_media.corpus import speech_spectrum
from ...v6.observer import Recognizer
from ...next_20261025.media.ensemble_event import PRIMARY
from ..joint.model import FrozenPortfolio
from .calibrate import quantize
from .common import sha, write


class PortfolioHost:
    def __init__(self, settings, observer_directory):
        self.settings = settings
        self.portfolio = FrozenPortfolio(settings['renderer_paths'])
        self.image_observer = Recognizer().eval().requires_grad_(False)
        self.image_observer.load_state_dict(torch.load(settings['image_observer'], weights_only=True, map_location='cpu')['state_dict'])
        self.speech_observer = CachedFrozenAudit(Path(settings['asr_assets']), observer_directory, Path(settings['event_cache']))
        self.identity = sha(Path(__file__))
        self.real_audio_acquisitions = 0

    @torch.inference_mode()
    def encode(self, public_task):
        encoded = self.portfolio.encode(public_task)
        if len(encoded.features) != 1:
            raise ValueError('Each original owner stream receives one independent public request')
        features = np.concatenate((encoded.features[0].double().numpy().ravel(),
                                   encoded.raw_probabilities[0].double().numpy().ravel()))
        return quantize(features).tolist(), {'encoder_wall_ns': encoded.wall_ns,
            'route': encoded.route, 'actual_frozen_frontend_executed': True}

    def _receipt(self, decision, started, received):
        event = decision['decision']
        return {'schema': 'hepta.advance.actual-outcome.v1', 'request_id': event['request_id'],
            'decision_digest': decision['decision_digest'], 'action': event['selected_action'],
            'observer_sha256': self.identity, 'private_truth_utility_supplied': False,
            'decision_received_ns': received, 'generation_started_ns': started}

    @torch.inference_mode()
    def acquire(self, decision, root, public_rows, source_group_id, output):
        received = time.perf_counter_ns()
        if decision['decision']['selected_action'] != 101 or decision['status']['pending'] is None:
            raise ValueError('Actual external acquisition requires a committed native pending action')
        # Only identity fields are passed to the source loader; labels/speaker
        # outcomes are not visible to the CNN. No waveform cache is reused.
        rows = [{'path': row['path'], 'sha256': row['sha256']} for row in public_rows]
        if len(rows) != 2:
            raise ValueError('Two actual external source utterances required')
        started = time.perf_counter_ns()
        waves = load_audio(root, rows)
        logits = self.portfolio.model.audio_input(speech_spectrum(waves))
        # The selected CNN returns digit logits; posterior adapter is not used
        # to manufacture a different observation for the frozen label likelihood.
        if isinstance(logits, tuple): logits = logits[0]
        labels = logits.argmax(-1).reshape(-1).tolist()
        if len(labels) != 2: raise ValueError('Actual source CNN did not return two public labels')
        self.real_audio_acquisitions += 1
        receipt = self._receipt(decision, started, received)
        receipt.update(evidence_origin='external_source_audio', target_supplied=False,
            source_group_id=source_group_id, external_audio_label=10 * labels[0] + labels[1],
            source_wav_paths=[str(Path(root) / row['path']) for row in rows],
            source_wav_sha256=[row['sha256'] for row in rows], utility_q32=0,
            source_acquisition_cached=False, source_CNN_wall_ns=time.perf_counter_ns() - started,
            observed_ns=time.perf_counter_ns())
        write(output, receipt)
        return receipt

    @torch.inference_mode()
    def emit(self, decision, directory, receipt_path, diagnostic_transport_fault=None):
        received = time.perf_counter_ns()
        code = decision['decision']['selected_action']
        if not isinstance(code, int) or not 0 <= code < 100 or decision['status']['pending'] is None:
            raise ValueError('Actual renderer requires an admitted native output action')
        started = time.perf_counter_ns()
        generated = self.portfolio.render(code, directory, decision['decision']['request_id'])
        media = generated['output']
        paths = {key: Path(value['path']) for key, value in media['files'].items()}
        original_caption_sha256 = sha(paths['text'])
        if diagnostic_transport_fault is not None:
            if diagnostic_transport_fault == 'valid_caption_substitution':
                # Explicit engineering fault: generated code remains recorded;
                # the delivered caption is replaced after actual generation.
                original = paths['text'].read_text()
                replacement = 'left 9 right 9 relation equal'
                if original.strip() == replacement: replacement = 'left 0 right 0 relation equal'
                paths['text'].write_text(replacement + '\n')
            elif diagnostic_transport_fault == 'caption_truncation':
                paths['text'].write_text('truncated delivery\n')
            else:
                raise ValueError('Unregistered engineering transport fault')
        observed = observe_bundle(paths, self.image_observer, self.speech_observer)
        caption = observed['caption_digits']
        audio = observed['speech']['predictions'][PRIMARY]
        agreement = (caption is not None and observed['image_digits'] == caption and audio == caption
                     and observed['video_digits'] == [v for digit in caption for v in [digit] * 10])
        delivery = observed['content_checks']['moving_video'] and observed['content_checks']['nonempty_audio']
        # This bounded scalar is a target-free delivery proxy. A consistent
        # wrong code can receive +1; true target utility is scored offline only.
        utility = 1 - int(caption is None) - int(not (agreement and delivery))
        receipt = self._receipt(decision, started, received)
        receipt.update(evidence_origin='own_generated_output', target_belief_updated=False,
            media={k: str(v) for k, v in paths.items()}, media_sha256={k: sha(v) for k, v in paths.items()},
            clock=media['clock'], codec_observation={'target_supplied': False,
                'lossless_roundtrip': media['lossless_roundtrip'], 'public_observation': observed},
            utility_q32=utility * (1 << 32), utility_semantics='target-free crossmodal delivery agreement proxy',
            diagnostic_transport_fault=diagnostic_transport_fault, original_generated_caption_sha256=original_caption_sha256,
            generated_parameter_sha256=generated.get('renderer_parameter_sha256'), observed_ns=time.perf_counter_ns())
        write(receipt_path, receipt)
        return receipt, observed
