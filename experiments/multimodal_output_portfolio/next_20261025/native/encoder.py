"""Public 511-coordinate ABI: original 478 plus one frozen 32-wide value encoder.

The deployed first layer is part of the explicitly costed Python model service.
The original correctness network and both value output layers run in Rust.
No observer, target, source identity, future random state or action is encoded
into the 32-wide teacher hidden state.
"""

import numpy as np
import torch

from ...abc_followup.native.forecast import ACTIONS, Q, public_input, quantize
from ...abc_next.observability import input_evidence, observed_features
from ...abc_next.sensor_run import load_sensor
from ...abc_next.value import features, load_controller
from .common import SENSOR, TEACHER, sha, write


class PublicEncoder:
    def __init__(self):
        self.sensor = load_sensor(SENSOR)
        self.teacher = load_controller(TEACHER)
        if self.teacher.hidden != 32 or self.teacher.mode != 'enriched':
            raise ValueError('The fixed 511-wide ABI requires the original enriched 32-wide teacher')

    @torch.inference_mode()
    def encode(self, model, frame, observation):
        work = {}
        evidence = input_evidence(self.sensor, observation, work)
        public = observed_features(model, frame, sensor=self.sensor, evidence=evidence, work=work)
        head = self.teacher.one if frame.remaining == 1 else self.teacher.two
        x = features(public, self.teacher.mode)
        hidden = head.network[:2]((x - head.mean) / head.scale)
        hidden_q24 = quantize(hidden.double().numpy())
        raw = head(x)[0].double().numpy()
        result = []
        for action in ACTIONS:
            original = public_input(model, frame, observation, action)[0]
            result.append(np.concatenate((original, hidden_q24[0], [frame.remaining * Q])).tolist())
        if len(result[0]) != 511 or not np.array_equal(result[0][478:], result[1][478:]):
            raise ValueError('Candidate public value encodings differ')
        return result, raw, work, hidden[0].double().numpy()

    def export(self, path):
        heads = []
        for head in (self.teacher.one, self.teacher.two):
            heads.append({'weight': head.network[2].weight.detach().double().tolist(),
                          'bias': head.network[2].bias.detach().double().tolist()})
        write(path, {'schema': 'hepta.next.native-value-layers.v1', 'hidden': 32,
                     'teacher_sha256': sha(TEACHER), 'sensor_sha256': sha(SENSOR),
                     'gamma': 2., 'action_cost_already_in_targets': .002,
                     'actions': ['stop', 'refine_semantic', 'refine_image', 'refine_text', 'couple'],
                     'heads': heads, 'new_trainable_parameters': 0})


def projected_moments(export, x):
    head = export['heads'][int(x[510] // Q) - 1]
    hidden = np.asarray(x[478:510], dtype=np.float64) / Q
    raw = np.asarray(head['weight']) @ hidden + np.asarray(head['bias'])
    return np.where(raw > 20., raw, np.logaddexp(0., raw)) + 1e-8
