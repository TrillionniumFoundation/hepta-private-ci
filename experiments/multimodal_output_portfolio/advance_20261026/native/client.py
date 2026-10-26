"""Typed host IPC. Native owns action selection, admission, journals and NDU state."""

import hashlib
import json
from pathlib import Path
import struct
import subprocess
import time

from .common import sha, write


def feature_digest(features):
    encoded = b'hepta.neuron.input-features.q24.v1' + struct.pack('>Q', len(features))
    return hashlib.sha256(encoded + b''.join(struct.pack('>q', int(v)) for v in features)).hexdigest()


class Native:
    def __init__(self, binary, descriptor, root, resume=False):
        self.spec = json.loads(Path(descriptor).read_text())
        self.descriptor_sha256 = sha(descriptor)
        self.stderr = Path(str(root) + '.stderr.log').open('ab')
        self.process = subprocess.Popen([str(binary), str(descriptor), self.descriptor_sha256,
            str(root), 'resume' if resume else 'new'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=self.stderr, text=True, bufsize=1)
        line = self.process.stdout.readline()
        if not line:
            self.process.wait()
            self.stderr.close()
            raise RuntimeError('Native bootstrap failed; read ' + str(root) + '.stderr.log')
        self.ready = json.loads(line)
        if self.ready.get('ready') is not True:
            raise RuntimeError(self.ready)

    def call(self, command):
        began = time.perf_counter_ns()
        self.process.stdin.write(json.dumps(command, allow_nan=False) + '\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('Native process closed before operation receipt')
        result = json.loads(line)
        result['host_IPC_wall_ns'] = time.perf_counter_ns() - began
        return result

    def checked(self, command):
        result = self.call(command)
        if result['ok'] is not True:
            raise RuntimeError(result)
        return result['value']

    def decide(self, request, episode, features, route, remaining=2, missing=False, parent=None):
        return self.checked({'kind': 'decide', 'request_id': request, 'episode_id': episode,
            'parent_outcome_digest': parent, 'generation': 1, 'weights_sha256': self.spec['pins']['weights'],
            'objective_digest': self.descriptor_sha256, 'prefix_digest': feature_digest(features),
            'features': features, 'route': route, 'remaining': remaining, 'explicit_missing': missing})

    def observe(self, decision, receipt):
        event = decision['decision']
        return self.checked({'kind': 'observe', 'request_id': event['request_id'],
            'decision_digest': decision['decision_digest'], 'selected_action': event['selected_action'],
            'receipt_path': str(receipt), 'receipt_sha256': sha(receipt)})

    def close(self, pending=False):
        value = self.checked({'kind': 'disconnect' if pending else 'shutdown'})
        self.process.stdin.close()
        code = self.process.wait(timeout=30)
        self.stderr.close()
        if code: raise RuntimeError('Native exit status ' + str(code))
        return value

    def finish_if_alive(self):
        """An exception preserves pending journal state through graceful EOF."""
        if self.process.poll() is None:
            try:
                self.close(pending=True)
            except (RuntimeError, BrokenPipeError):
                if not self.process.stdin.closed:
                    self.process.stdin.close()
                self.process.wait(timeout=30)
        if not self.stderr.closed:
            self.stderr.close()


def descriptor(template, directory, stream_id, source_group_id, policy, mode='development', numeric=True):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    value = dict(template)
    value.update(stream_id=stream_id, source_group_id=source_group_id, policy=policy,
                 mode=mode, numeric_modulation=numeric)
    path = directory / 'descriptor.json'
    write(path, value)
    return path
