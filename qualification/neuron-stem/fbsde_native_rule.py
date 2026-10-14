"""Research composition of the existing durable RuleSlot and native owners.

The native process independently verifies CURRENT, selection and FinalUse.
These JSON descriptors only bind evidence and work; they grant no authority.
There is no automatic retry after an unknown native or local finish outcome.
"""
import hashlib
import json
from pathlib import Path
import select
import subprocess
import time

from four_gate_common import require, strict_loads
from fbsde_rule_lifecycle import UseTicket
from fbsde_transfer import OPS

SCHEMA = 'hepta.rule-artifact.research.v1'
MAX_LINE = 65536


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


class NativeRulePort:
    """Bounded subprocess transport to the native qualification executable.

    Fixture signing keys live only in that executable's qualification harness.
    A deployment must supply its existing native owner and independent issuer.
    """
    def __init__(self, executable, directory, *, timeout=20):
        self.root = Path(directory)
        require(self.root.is_dir(), 'existing private native directory')
        self._log = (self.root / 'native-stderr.log').open('ab')
        self._process = subprocess.Popen([str(Path(executable).resolve()), str(self.root.resolve())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log, bufsize=0)
        self._timeout = timeout
        self._closed = False
        self.calls = []

    def call(self, value):
        require(not self._closed, 'native transport closed')
        raw = canonical(value) + b'\n'
        require(len(raw) <= MAX_LINE, 'bounded native request')
        cpu, wall = time.process_time_ns(), time.perf_counter_ns()
        try:
            self._process.stdin.write(raw)
            response = bytearray()
            deadline = time.monotonic() + self._timeout
            while not response.endswith(b'\n'):
                remaining = deadline - time.monotonic()
                require(remaining > 0 and select.select([self._process.stdout], [], [], remaining)[0],
                        'native response timed out; outcome unknown')
                byte = self._process.stdout.read(1)
                require(byte and len(response) < MAX_LINE, 'native response lost or oversized')
                response.extend(byte)
            result = strict_loads(bytes(response))
            require(type(result) is dict and type(result.get('ok')) is bool, 'native response shape')
            return result
        except BaseException:
            self._closed = True
            raise
        finally:
            self.calls.append(dict(command=value.get('command'), cpu_ns=time.process_time_ns()-cpu,
                wall_ns=time.perf_counter_ns()-wall, request_bytes=len(raw)))

    def close(self):
        if not self._closed:
            try: self.call(dict(command='quit'))
            except (OSError, ValueError): pass
        self._closed = True
        if self._process.stdin: self._process.stdin.close()
        if self._process.stdout: self._process.stdout.close()
        try: self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try: self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill(); self._process.wait()
        self._log.close()


class NativeRuleSlotConsumer:
    """Additive use route; never restores an active table or a pending handle.

    Python's slot lock covers native execution and the local durable finish.
    The native adapter holds its existing artifact owner and FinalUse fences.
    Successful native execution followed by uncertain SQLite finish loses
    availability: its cost remains charged, and no result is returned or retried.
    """
    def __init__(self, slot, port):
        self.slot, self.port = slot, port
        self._verified = {}
        self._closed = False
        self.costs = []
        with slot._lock:
            status = slot.status()
            require(status['state'] == 'active' and not status['pending'], 'fresh active rule export required')
            require(not slot._verifying, 'source verification pending')
            self.bundle = dict(schema=SCHEMA, slot=slot.identity, revision=status['revision'],
                generation=status['context']['generation'], scope=status['context']['scope'],
                environment=status['context']['environment'], table=slot._table.snapshot(),
                checkpoint_anchor=slot.checkpoint_anchor())
            payload = canonical(self.bundle)
            self.descriptor = dict(checkpoint_digest=hashlib.sha256(payload).hexdigest(),
                rule_revision=self.bundle['revision'], generation=self.bundle['generation'], authority_epoch=1,
                scope_digest=hashlib.sha256(canonical(status['context'])).hexdigest())
            result = port.call(dict(command='init', payload_hex=payload.hex(), **self.descriptor))
            require(result['ok'], 'native owner/independent selection admission refused')

    def verify(self, ticket, reveal):
        require(not self._closed, 'native rule consumer closed')
        matched = self.slot.verify(ticket, reveal)
        with self.slot._lock:
            if matched:
                self.slot._current(ticket)
                self._verified[ticket] = ticket
        return matched

    def finish(self, ticket):
        cpu, wall = time.process_time_ns(), time.perf_counter_ns()
        attempt = dict(sequence=getattr(ticket, 'sequence', None), native_response=None, returned=False)
        try:
            with self.slot._lock:
                require(not self._closed, 'native rule consumer closed')
                request, predicted, effect_index = self.slot._current(ticket)
                require(type(ticket) is UseTicket and self._verified.get(ticket) is ticket,
                        'successful current source verification required')
                require(ticket not in self.slot._verifying, 'source verification pending')
                require(ticket.revision == self.bundle['revision'] and
                    request['generation'] == self.bundle['generation'], 'new native candidate required')
                # Remove the process-local admission before native entry. Unknown
                # results can never cause reuse of this same ticket.
                del self._verified[ticket]
                operation = OPS[effect_index]
                normalized = tuple(request['state'][index] for index in operation)
                response = self.port.call(dict(command='execute', **self.descriptor,
                    sequence=ticket.sequence, input_state=list(request['state']),
                    expected_prediction_q24=[x * (1 << 24) for x in normalized],
                    checkpoint_anchor=self.slot.checkpoint_anchor()))
                attempt['native_response'] = response
                require(response['ok'] and response.get('sequence') == ticket.sequence and
                    response.get('checkpoint_digest') == self.descriptor['checkpoint_digest'] and
                    response.get('rule_revision') == ticket.revision and
                    response.get('generation') == request['generation'] and
                    response.get('effect') == list(normalized), 'native final-use refused or receipt mismatch')
                result = self.slot.finish(ticket)
                require(result == predicted, 'local finish differs from verified native effect')
                attempt['returned'] = True
                return result
        except BaseException:
            self._closed = True
            self._verified.clear()
            with self.slot._lock:
                if not self.slot._dead and self.slot.status()['state'] == 'active':
                    self.slot._retire('native_final_use_refused_or_unknown')
            raise
        finally:
            attempt.update(cpu_ns=time.process_time_ns()-cpu, wall_ns=time.perf_counter_ns()-wall)
            self.costs.append(attempt)

    def close(self):
        self._closed = True
        self._verified.clear()
        self.port.close()
