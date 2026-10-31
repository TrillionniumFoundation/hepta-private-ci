"""Costed public encoders for a compact 103-coordinate native H2 ABI.

Four observed-absence coordinates, two public candidate action flags, horizon,
32 frozen teacher activations, and 64 learned correctness activations. Neither
targets nor outcome/source identities nor future innovations enter either head.
"""

import json

import numpy as np
import torch

from ...abc_followup.native.forecast import Q, public_input, quantize
from ...abc_next.observability import input_evidence, observed_features
from ...abc_next.sensor_run import load_sensor
from ...abc_next.value import features, load_controller
from .admission import hidden as admission_hidden
from .common import SENSOR, TEACHER, sha, write
from .qualification import ACTIONS


FLAGS = ((0, 0), (-Q, 0), (0, -Q), (Q, 0), (0, Q))
WIDTH, HORIZON, TEACHER_START, ADMISSION_START = 103, 6, 7, 39


class PublicEncoder:
    def __init__(self, predictor_path):
        self.sensor = load_sensor(SENSOR)
        self.teacher = load_controller(TEACHER)
        self.predictor = json.loads(predictor_path.read_text())
        if (self.teacher.hidden != 32 or self.teacher.mode != 'enriched'
                or self.predictor['schema'] != 'hepta.next.native-h2-public-admission.v2'
                or self.predictor['teacher_sha256'] != sha(TEACHER)):
            raise ValueError('Wrong frozen public encoder identities')

    @torch.inference_mode()
    def encode(self, model, frame, observation):
        work = {}
        evidence = input_evidence(self.sensor, observation, work)
        public = observed_features(model, frame, sensor=self.sensor, evidence=evidence, work=work)
        head = self.teacher.one if frame.remaining == 1 else self.teacher.two
        x = features(public, self.teacher.mode)
        value_hidden = head.network[:2]((x - head.mean) / head.scale)
        correctness_hidden = admission_hidden(self.predictor, public.numpy(), frame.remaining)[0]
        value_q24 = quantize(value_hidden.double().numpy())[0]
        correctness_q24 = quantize(correctness_hidden)
        original = public_input(model, frame, observation, 'refine_text')[0]
        observed_absence = [int(original[i]) for i in (448, 449, 460, 471)]
        inputs = [observed_absence + list(flags) + [frame.remaining * Q]
                  + value_q24.tolist() + correctness_q24.tolist() for flags in FLAGS]
        if any(len(row) != WIDTH for row in inputs):
            raise ValueError('Invalid compact ABI')
        work['admission_public_first_layer_calls'] = 1
        work['admission_first_layer_multiply_adds'] = 763 * 64
        work['teacher_public_first_layer_calls'] = 1
        return inputs, head(x)[0].double().numpy(), work, correctness_hidden

    def export(self, path):
        heads = [{'weight': head.network[2].weight.detach().double().tolist(),
                  'bias': head.network[2].bias.detach().double().tolist()}
                 for head in (self.teacher.one, self.teacher.two)]
        write(path, {'schema': 'hepta.next.native-h2-value-layers.v1', 'hidden': 32,
                     'teacher_sha256': sha(TEACHER), 'sensor_sha256': sha(SENSOR),
                     'gamma': 2., 'action_cost_already_in_targets': .002,
                     'actions': ACTIONS, 'heads': heads,
                     'new_value_trainable_parameters': 0,
                     'ABI': {'width': WIDTH, 'absence': [0, 1, 2, 3], 'action_flags': [4, 5],
                             'horizon': HORIZON, 'teacher_hidden': [7, 39], 'admission_hidden': [39, 103]}})


def projected_moments(export, x):
    head = export['heads'][int(x[HORIZON] // Q) - 1]
    latent = np.asarray(x[7:39], dtype=np.float64) / Q
    raw = np.asarray(head['weight']) @ latent + np.asarray(head['bias'])
    return np.where(raw > 20., raw, np.logaddexp(0., raw)) + 1e-8
