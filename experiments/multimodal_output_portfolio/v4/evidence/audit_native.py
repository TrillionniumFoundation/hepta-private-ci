"""Independent successful MP1 transcript audit; no production imports.

This checks choices, budgets, state transitions and byte-level hash bindings.
It does not establish that the acknowledged hashes came from neural execution:
the separate runtime replay must bind the returned sessions to actual arrays.
"""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import time


MODALITIES = ('text', 'audio', 'image', 'video')
ACTIONS = ('EMIT', *(f'REFINE_{m}' for m in MODALITIES))
DECODERS = (6656, 69632, 53248, 200704)
INITIAL, REFINE, EMIT, BUDGET = 3584, 8704, 330240, 351232


def require(condition, detail):
    if not condition:
        raise AssertionError(detail)


def digest(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
            and value != '0' * 64, ('nonzero canonical SHA256', value))
    return value


def bundle(hashes, kind='latents'):
    require(kind in ('latents', 'outputs') and len(hashes) == 4, 'hash bundle contract')
    domain = f'hepta.modality-portfolio.{kind}.v1\0'.encode()
    return hashlib.sha256(domain + b''.join(bytes.fromhex(digest(h)) for h in hashes)).hexdigest()


def integer(value):
    require(isinstance(value, str) and re.fullmatch('0|[1-9][0-9]*', value), 'canonical integer')
    result = int(value)
    require(result < 2**64, 'u64 integer range')
    return result


class NativeAudit:
    """Consume a persisted request/response stream, one sealed session at a time."""

    def __init__(self, path):
        path = Path(path)
        self.stream = gzip.open(path, 'rb') if path.suffix == '.gz' else path.open('rb')
        self.digest = hashlib.sha256()
        self.requests, self.sessions, self.last_sid = 0, 0, 0

    def _exchange(self, allow_eof=False):
        left = self.stream.readline()
        if not left and allow_eof:
            return None
        right = self.stream.readline()
        require(left.startswith(b'> ') and right.startswith(b'< ')
                and left.endswith(b'\n') and right.endswith(b'\n'), 'complete transcript framing')
        require(len(left) - 2 <= 4096, 'native bounded request')
        self.digest.update(left + right)
        command = left[2:-1].decode('ascii').split('\t')
        response = right[2:-1].decode('ascii').split('\t')
        require(command[:1] == ['MP1'] and response[:2] == ['MP1', 'OK'],
                ('successful MP1 exchange required', command, response))
        self.requests += 1
        return command, response

    @staticmethod
    def _response(response, command, sid, version, remaining, counts, phase, hashes):
        expected = ['MP1', 'OK', command, str(sid), str(version), str(remaining),
                    str(sum(counts)), *map(str, counts), phase, bundle(hashes)]
        require(response[:13] == expected, ('native state response', expected, response))

    def session(self):
        initial = self._exchange(allow_eof=True)
        if initial is None:
            return None
        command, response = initial
        require(len(command) == 22 and command[1] == 'INIT', 'new session must begin with INIT')
        sid, condition = integer(command[2]), integer(command[3])
        require(sid > self.last_sid and condition < 8, 'monotone session and semantic condition')
        q_hash = hashlib.sha256(struct.pack('<8f', *(float(i == condition) for i in range(8)))).hexdigest()
        require(command[4] == q_hash, 'q digest binds actual one-hot format and condition')
        profile = tuple(map(integer, command[5:16]))
        require(profile == (BUDGET, INITIAL, 2, *DECODERS, *(REFINE,) * 4), 'fixed cost profile')
        hashes = list(map(digest, command[16:20]))
        mode, token = command[20:22]
        require(mode in ('ADAPTIVE', 'COMMITTED', 'CLEAN'), 'registered policy mode')
        plan = () if token == '-' else tuple(token.split(','))
        require((mode == 'COMMITTED' or not plan) and len(plan) <= 2
                and all(action in ACTIONS[1:] for action in plan), 'INIT-bound fixed plan')
        remaining, version, counts = BUDGET - INITIAL, 0, [0] * 4
        self._response(response, 'INIT', sid, version, remaining, counts, 'ready', hashes)
        require(len(response) == 13, 'INIT response field count')
        result = {'session_id': sid, 'condition': condition, 'q_hash': q_hash,
                  'policy_mode': mode, 'plan': tuple(ACTIONS.index(a) - 1 for a in plan),
                  'initial_latent_hashes': list(hashes), 'events': []}
        while True:
            command, response = self._exchange()
            require(len(command) == 20 and command[:4] == ['MP1', 'CHOOSE', str(sid), str(version)]
                    and command[4] == bundle(hashes), 'current CHOOSE identity and all-latent binding')
            candidates = {}
            for index in range(5, 20, 3):
                action, value, cost = command[index:index + 3]
                require(action in ACTIONS and action not in candidates, 'complete unique five-action table')
                score = float(value)
                require(math.isfinite(score), 'finite action utility')
                require(integer(cost) == (EMIT if action == 'EMIT' else REFINE), 'candidate action cost')
                candidates[action] = score
            depth, eligible, selected = sum(counts), [], None
            committed = plan[depth] if depth < len(plan) else 'EMIT'
            for action in ACTIONS:
                physical = (remaining >= EMIT if action == 'EMIT' else
                            depth < 2 and remaining >= REFINE + EMIT)
                policy = mode == 'ADAPTIVE' or action == ('EMIT' if mode == 'CLEAN' else committed)
                feasible = bool(physical and policy)
                eligible.append(feasible)
                if not feasible:
                    require(candidates[action] == 0., 'ineligible action must have finite zero placeholder')
                elif selected is None or candidates[action] > candidates[selected] + 1e-12:
                    selected = action
            require(selected is not None, 'at least one feasible action')
            event = {'version_before': version, 'depth_before': depth,
                     'remaining_before': remaining, 'latent_hashes_before': list(hashes),
                     'scores': [candidates[a] for a in ACTIONS], 'eligible': eligible,
                     'action': ACTIONS.index(selected), 'selected_value': candidates[selected]}
            remaining -= EMIT if selected == 'EMIT' else REFINE
            version += 1
            if selected != 'EMIT':
                counts[ACTIONS.index(selected) - 1] += 1
            phase = 'await_outputs' if selected == 'EMIT' else 'await_refinement'
            self._response(response, 'CHOOSE', sid, version, remaining, counts, phase, hashes)
            require(len(response) == 15 and response[13] == selected
                    and float(response[14]) == candidates[selected], 'native feasible argmax and exact f64 score')
            command, response = self._exchange()
            if selected == 'EMIT':
                require(len(command) == 13 and command[:5] ==
                        ['MP1', 'EMITTED', str(sid), str(version), bundle(hashes)], 'emission ACK identity')
                require(tuple(command[5::2]) == MODALITIES, 'complete uniquely named output bundle')
                outputs = list(map(digest, command[6::2]))
                self._response(response, 'EMITTED', sid, version, remaining, counts, 'sealed', hashes)
                require(response[13:] == command[5:] + [bundle(outputs, 'outputs')],
                        'sealed output ACK and domain-separated output bundle')
                result['output_hashes'] = dict(zip(MODALITIES, outputs))
            else:
                require(len(command) == 9 and command[:5] ==
                        ['MP1', 'REFINED', str(sid), str(version), selected], 'selected-modality ACK identity')
                changed = list(map(digest, command[5:]))
                target = ACTIONS.index(selected) - 1
                require(all(old == new for m, (old, new) in enumerate(zip(hashes, changed)) if m != target),
                        'three unselected latent states must remain unchanged')
                hashes = changed
                self._response(response, 'REFINED', sid, version, remaining, counts, 'ready', hashes)
                require(len(response) == 13, 'refinement ACK field count')
            event.update(version_after=version, remaining_after=remaining, latent_hashes_after=list(hashes))
            result['events'].append(event)
            if selected == 'EMIT':
                break
        self.last_sid, self.sessions = sid, self.sessions + 1
        result.update(refinement_counts=list(counts), spent_macs=BUDGET - remaining,
                      remaining_macs=remaining, version=version, sealed=True)
        require(result['spent_macs'] == INITIAL + sum(counts) * REFINE + sum(DECODERS), 'complete MAC identity')
        return result

    def finish(self, receipt=None):
        require(self.stream.read() == b'', 'extra native commands or incomplete session coverage')
        self.stream.close()
        result = {'sessions': self.sessions, 'requests': self.requests,
                  'transcript_sha256': self.digest.hexdigest()}
        if receipt is not None:
            require(all(receipt[key] == value for key, value in result.items()), 'native receipt count/hash')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transcript', type=Path, required=True)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    audit, modes, choices, total_macs = NativeAudit(args.transcript), {}, [0] * 5, 0
    while (session := audit.session()) is not None:
        mode = session['policy_mode']
        modes[mode] = modes.get(mode, 0) + 1
        total_macs += session['spent_macs']
        for event in session['events']:
            choices[event['action']] += 1
    receipt = json.loads(args.receipt.read_text()) if args.receipt else None
    result = {'passed': True, **audit.finish(receipt), 'policy_mode_sessions': modes,
              'selected_action_counts': dict(zip(ACTIONS, choices)), 'native_accounted_macs': total_macs,
              'neural_execution_bound': False, 'production_authorization_attested': False,
              'auditor_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'transcript_file_sha256': hashlib.sha256(args.transcript.read_bytes()).hexdigest(),
              'audit_wall_seconds': time.perf_counter() - started,
              'audit_process_cpu_seconds': time.process_time() - cpu, 'audit_linear_macs': 0}
    with args.output.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
