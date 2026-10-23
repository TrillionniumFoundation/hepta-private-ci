"""Persistent caller of the real codex-hepta-ndu feedback-generation binary."""

import hashlib
from pathlib import Path
import subprocess
import time


class NativeBridge:
    def __init__(self, binary, transcript):
        self.binary = str(Path(binary).resolve())
        self.binary_sha256 = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
        self.process = subprocess.Popen([self.binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, bufsize=1)
        self.transcript = transcript
        self.transcript_sha256 = hashlib.sha256()
        self.requests = 0
        self.request_round_trip_wall_seconds = 0.
        self.sessions = 0
        self.sid = 0
        self.version = 0
        self.depth = 0
        self.remaining = 0
        self.sealed = True
        self.started = time.perf_counter()

    def _exchange(self, *fields):
        started = time.perf_counter()
        command = '\t'.join(str(value) for value in fields)
        if len(command) > 4095 or '\n' in command:
            raise ValueError('invalid native command length')
        self.process.stdin.write(command + '\n')
        self.process.stdin.flush()
        response = self.process.stdout.readline().rstrip('\n')
        self.request_round_trip_wall_seconds += time.perf_counter() - started
        payload = ('> ' + command + '\n< ' + response + '\n').encode()
        self.transcript.write(payload.decode())
        self.transcript_sha256.update(payload)
        self.requests += 1
        parts = response.split('\t')
        if len(parts) < 7 or parts[0] != 'OK' or parts[1] != fields[0]:
            raise RuntimeError('native feedback rejected command: ' + response[:512])
        if int(parts[2]) != self.sid:
            raise AssertionError('native session mismatch')
        self.version, self.remaining, self.depth = (int(x) for x in parts[3:6])
        return parts

    def begin(self, condition, latent_digest, profile, horizon):
        if not self.sealed:
            raise RuntimeError('previous native session has not emitted all four outputs')
        self.sid += 1
        self.sessions += 1
        self.condition, self.profile = condition, profile
        self._exchange('INIT', self.sid, profile['emit_all'] + horizon * profile['refinement'],
                       profile['emit_all'], profile['refinement'], horizon, condition, latent_digest)
        self.sealed = False

    def choose(self, observed):
        fields = ['CHOOSE', self.sid, self.version, self.depth, self.condition,
                  observed['latent_sha256'], 'emit', repr(observed['stop_value']), self.profile['emit_all']]
        if observed['continue_value'] is not None:
            fields += ['refine', repr(observed['continue_value']), self.profile['refinement']]
        result = self._exchange(*fields)
        if len(result) != 8 or result[6] != observed['action']:
            raise AssertionError('native/Python selected action mismatch')
        target = observed['stop_value'] if result[6] == 'emit' else observed['continue_value']
        if abs(float(result[7]) - target) > 1e-12:
            raise AssertionError('native selected value mismatch')
        return result[6]

    def refined(self, latent_digest):
        self._exchange('REFINED', self.sid, self.version, self.depth, self.condition, latent_digest)

    def emitted(self, hashes):
        parts = self._exchange('EMITTED', self.sid, self.version,
                               *(hashes[name] for name in ('text', 'audio', 'image', 'video')))
        if parts[6] != 'sealed':
            raise AssertionError('native stream was not sealed')
        self.sealed = True

    def close(self):
        if not self.sealed:
            raise RuntimeError('incomplete native generation session')
        self.process.stdin.close()
        status = self.process.wait(timeout=10)
        stderr = self.process.stderr.read()
        self.process.stdout.close()
        self.process.stderr.close()
        if status != 0 or stderr:
            raise RuntimeError(f'native process failure: status={status}, stderr={stderr[:512]}')
        return {'binary': self.binary, 'binary_sha256': self.binary_sha256,
                'sessions': self.sessions, 'requests': self.requests,
                'transcript_sha256': self.transcript_sha256.hexdigest(),
                'process_lifetime_wall_seconds': time.perf_counter() - self.started,
                'request_round_trip_wall_seconds': self.request_round_trip_wall_seconds,
                'timing_scope': 'round trips include Python/IPC/native; lifetime also includes waiting for model training and execution',
                'native_action_and_budget_executed': True,
                'production_neuron_runtime_deployed': False,
                'attestation': 'caller-supplied hashes and local process, not signed external attestation'}
