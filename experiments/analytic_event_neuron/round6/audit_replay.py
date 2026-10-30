"""Independent numeric checks plus actual shared-runtime/native execution replay.

The numerical reference is independent. Owner/native replay deliberately uses
the actual original implementations; it is not a second Rust implementation.
Measured latency/RSS and their runtime digests are not deterministic identities.
"""

import base64
from functools import lru_cache
import gzip
import itertools
import json
import math
from pathlib import Path
import shutil

import numpy as np

from ..native_adapter import Native
from ..round4.runtime_owner import Owner
from .audit_transport import digest
from . import reference


Q24 = 1 << 24
LEARNED = ('analytic', 'numeric', 'history')


@lru_cache(maxsize=16384)
def _continuation(weights, means, variances, noise, cost, order):
    law = {'schema': reference.SCHEMA, 'semantics': 'terminal', 'weights': weights,
           'means': means, 'variances': variances}
    if len(weights) == 1:
        return reference.gaussian_continuation(law, noise, cost)
    return reference.continuation_reference(law, noise, cost, order=order)


def reference_values(law, public, scale):
    weights, means, variances = reference.components(law)
    mean = float(weights @ means)
    amount = round(mean * Q24) / Q24
    repair = 2 * amount * mean - amount * amount - public['repair_cost']
    wait = None
    if len(public['residuals']) == 1:
        wait = _continuation(tuple(weights), tuple(means), tuple(variances),
                             scale * public['wait_variance'], public['repair_cost'], 256) - public['wait_cost']
    return {'repair_amount': amount, 'repair_gain': repair, 'wait_gain': wait}


class LoggedNative(Native):
    def __init__(self, binary, receipt, log):
        self.log = log
        super().__init__(binary, receipt)

    def _request(self, request):
        result = super()._request(request)
        self.log.write(json.dumps({'request': request, 'response': result}, sort_keys=True,
                                  separators=(',', ':'), allow_nan=False) + '\n')
        return result


class Replay:
    def __init__(self, native_root, output, checks):
        self.output, self.checks = Path(output), checks
        self.output.mkdir(parents=True, exist_ok=False)
        self.log = gzip.open(self.output / 'NATIVE_REPLAY.jsonl.gz', 'xt')
        self.native = LoggedNative(Path(native_root) / 'analytic_event', Path(native_root) / 'BUILD_RECEIPT.json', self.log)
        self.rows, self.stages = 0, 0

    def owner(self, identity, model_sha, mode):
        root = self.output / f'working_{self.rows}'
        self.rows += 1
        return Owner(root, identity, model_sha, self.native, mode)

    def stage(self, owner, saved, model, arm, public, sequence, prior_checkpoint):
        checks = self.checks
        checks.require(saved['public'] == public and saved['public_sha256'] == digest(public), 'owner acquired information binding')
        scale = 1.0 if arm == 'uncalibrated' else model['calibration']['noise_scale']
        prior = model['gaussian_prior'] if arm in ('gaussian', 'probit') else model['prior']
        independent = reference.dense_posterior(prior, public['residuals'], public['variances'], scale)
        for key in ('weights', 'means', 'variances'):
            checks.close(saved['source_law'][key], independent[key], 'dense_posterior_' + key, 2e-11)
        replayed = owner.step(public, saved['source_law'], sequence, expected_checkpoint=prior_checkpoint)
        for key in ('subject', 'public_sha256', 'source_sha256', 'sequence', 'time', 'request_sha256',
                    'packet_base64', 'decoder', 'checkpoint_before', 'checkpoint_after', 'law'):
            checks.require(replayed[key] == saved[key], 'owner deterministic replay:' + key)
        checks.require(saved['authority'] == 'DENY_ALL' and saved['receiver_reopened_before_native']
                       and not saved['cross_owner_atomicity'], 'owner scope retained')
        checks.require(len(saved['native']) == len(replayed['native']) == len(saved['source_law']['weights']),
                       'every actual native component is present in replay')
        for original, actual in zip(saved['native'], replayed['native']):
            for key in ('sequence', 'checkpoint_before', 'checkpoint_after', 'temporal_state_digest',
                        'signals_q24', 'active_indices', 'abstain', 'authority'):
                checks.require(original[key] == actual[key], 'native typed semantic replay:' + key)
            for key in ('parameters_q24_decoded', 'probabilities', 'probabilities_q24', 'model_input_digest'):
                checks.require(original['head'][key] == actual['head'][key], 'native head semantic replay:' + key)
        received = saved['law']
        independent_logs = reference.event_logs(received['conditional_law'], received['lower'], received['upper'])
        checks.close(received['physical_log_probabilities'], independent_logs, 'independent_physical_log_probabilities', 5e-9)
        checks.close(received['native_mixture_probabilities'], np.exp(independent_logs), 'independent_native_CDF', 2e-12)
        self.stages += 1
        return replayed['checkpoint_after'], reference_values(received['conditional_law'], public, scale)

    def values(self, saved, independent):
        for key in ('repair_amount', 'repair_gain'):
            self.checks.close(saved[key], independent[key], 'decision_' + key, 3e-12)
        if independent['wait_gain'] is None:
            self.checks.require(saved['wait_gain'] is None, 'no third observation action')
        else:
            self.checks.close(saved['wait_gain'], independent['wait_gain'], 'decision_wait_gain', 3e-9)
        self.checks.require(saved['future_transport_quantization_included_in_bound'] is False
                           and saved['learned_future_readout_policy_included_in_integral'] is False,
                           'continuation approximation boundaries preserved')

    def features(self, public, received, model, arm, case, saved_native):
        precision = sum(1 / x for x in public['variances'])
        residual = sum(y / variance for y, variance in zip(public['residuals'], public['variances'])) / precision
        raw = np.array([residual, math.log(1 / precision), math.log(public['repair_cost'])])
        z = (raw - model['calibration']['public_center']) / model['calibration']['public_scale']
        if arm == 'history':
            powers = [p for p in itertools.product(range(4), repeat=3) if sum(p) <= 3]
            polynomial = [float(np.prod(z ** power)) for power in powers]
            centers = np.asarray(model['calibration']['history_centers'])
            self.checks.require(saved_native == [], 'history arm has no fabricated native feature calls')
            return np.concatenate([polynomial, np.exp(-0.5 * np.sum((centers - z) ** 2, axis=1))])
        p = received['probabilities']
        drives = np.tanh(z / 3) if arm == 'numeric' else np.array([p[2] - p[0], 2 * p[1] - 1, math.tanh(z[2] / 3)])
        self.checks.require(arm in ('analytic', 'numeric') and len(saved_native) == 3, 'three declared original sparse channels')
        features = []
        for channel, drive in enumerate(drives):
            count = round(float(drive) * Q24)
            actual = self.native.tick_pair(case + f'/channel{channel}', digest(public), count)
            original = saved_native[channel]
            self.checks.require(original['drive_q24'] == count and original['public_sha256'] == digest(public), 'native feature public binding')
            self.checks.require(original['case'] == actual['case'] and original['features'] == actual['features'], 'native feature value replay')
            self.checks.require(original['original_sparse_tick_calls'] == 2 and not original['checkpoint_reset_intervention'], 'two-tick retained sparse mechanism')
            for before, after in zip(original['ticks'], actual['ticks']):
                for key in before:
                    if key != 'native_ns':
                        self.checks.require(before[key] == after[key], 'original sparse tick semantic replay:' + key)
            last = actual['ticks'][1]
            features.extend([1.0] + [value / Q24 for name in ('activation_q24', 'eligibility_q24') for value in last[name]])
        return np.asarray(features)

    def archived_owner(self, archive, prefix, owner, saved_stages):
        root = prefix + '/owners/' + owner.subject
        document = archive.json(root + '/state.json')
        self.checks.require(digest(document['document']) == document['sha256'], 'original owner state document hash')
        state = document['document']
        self.checks.require(state['receipts'] == [s['runtime'] for s in saved_stages], 'archived owner receipts equal scored stages')
        self.checks.require(state['checkpoint'] == saved_stages[-1]['runtime']['checkpoint_after'], 'archived final owner checkpoint')
        for stage in saved_stages:
            native = stage['runtime']
            packet = archive.read(root + f"/packet-{native['sequence']}.bin")
            self.checks.require(packet == base64.b64decode(native['packet_base64'], validate=True), 'original packed bytes equal actual replay')
        witness = archive.json(root + '/witness.json')
        self.checks.require(digest(witness['document']) == witness['sha256'], 'original witness document hash')
        self.checks.require(witness['document']['records'][-1]['state_sha256'] == digest(state), 'independent witness binds final original state')
        shutil.rmtree(owner.root.parent)

    def close(self):
        self.native.close()
        self.log.close()
        return {'cases_replayed': self.rows, 'owner_stages_replayed': self.stages,
                'native_requests': self.native.calls, 'original_sparse_ticks': self.native.original_sparse_ticks,
                'native_roundtrip_ns': self.native.wall_ns,
                'replay': 'actual original Owner/Native plus independent numerical and information reconstruction',
                'operational_latency_RSS_and_runtime_digests_compared_exactly': False}
