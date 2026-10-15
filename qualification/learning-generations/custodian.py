#!/usr/bin/env python3
"""Local research role process. Keys never leave this process.

Fresh arithmetic instances are a synthetic task domain, not real user demand.
This process boundary does not establish separate administrative control. Native
signatures authenticate bounded research statements, not production authority.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import secrets
import sys
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def create(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as handle:
        handle.write(canonical(value) + b'\n')
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def result(operation, a, b):
    if operation == 'add':
        return a + b
    if operation == 'multiply':
        return a * b
    if operation == 'xor':
        return a ^ b
    if operation == 'subtract':
        return a - b
    raise ValueError('unknown operation')


OPERATIONS = ('subtract', 'add', 'multiply', 'xor')
QUERIES = ('bootstrap', 'familyalpha', 'familybeta', 'familygamma')
STRATA = {'generator': {'a_modulus': 2, 'a_residue': 1},
          'evaluator': {'a_modulus': 4, 'a_residue': 0},
          'future-custodian': {'a_modulus': 4, 'a_residue': 2}}


class Custodian:
    def __init__(self, role, directory):
        self.role, self.directory = role, Path(directory)
        self.directory.mkdir(mode=0o700)
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        self.used, self.released, self.prepared = set(), set(), {}
        self.sequence = 0
        self.operations = OPERATIONS
        self.configured = False
        self.head = '0' * 64
        self.started = time.monotonic_ns()

    def record(self, kind, body):
        self.sequence += 1
        value = dict(sequence=self.sequence, previous=self.head, role=self.role,
                     pid=os.getpid(), kind=kind, observed_unix_micros=time.time_ns() // 1000,
                     body=body)
        value['signature'] = self.key.sign(canonical(value)).hex()
        self.head = digest(value)
        create(self.directory / f'{self.sequence:06}.json', value)
        return value

    def tasks(self, generation, count, partition):
        rows = []
        for family in range(generation + 1):
            for _ in range(count):
                while True:
                    if self.role == 'generator':
                        a = 2 * secrets.randbelow(50000) + 3
                    elif self.role == 'evaluator':
                        a = 4 * secrets.randbelow(25000) + 4
                    elif self.role == 'future-custodian':
                        a = 4 * secrets.randbelow(25000) + 6
                    else:
                        raise ValueError('only declared material roles draw task operands')
                    b = secrets.randbelow(100000) + 3
                    identity = (family, a, b)
                    # Exact accidental action equivalence is excluded before
                    # predictions; it cannot turn a wrong operator into success.
                    answers = [result(op, a, b) for op in self.operations]
                    if identity not in self.used and len(set(answers)) == len(answers):
                        break
                self.used.add(identity)
                row = dict(query=QUERIES[family], a=a, b=b, expected=answers[family],
                           partition=partition, nonce=secrets.token_hex(16))
                row['id'] = digest(row)
                rows.append(row)
        return rows

    def handle(self, request):
        command = request['command']
        if command == 'hello':
            return dict(public_key=self.public, pid=os.getpid(), role=self.role)
        if command == 'configure':
            if self.configured or self.used or sorted(request['operations']) != sorted(OPERATIONS):
                raise ValueError('immutable complete task profile')
            self.operations = tuple(request['operations'])
            self.material_keys = request["material_keys"]
            if set(self.material_keys) != {"evaluator", "future-custodian"}:
                raise ValueError("exact material custodians required")
            self.observer_key = request['observer_key']
            self.configured = True
            return self.record('task-profile', dict(queries=QUERIES, operations=self.operations, operand_strata=STRATA))
        if command == 'sign':
            raw = bytes.fromhex(request['payload'])
            if not 1 <= len(raw) <= 1048576:
                raise ValueError('bounded signing payload')
            signature = self.key.sign(raw).hex()
            self.record('native-signature', dict(payload_sha256=hashlib.sha256(raw).hexdigest(),
                        payload_hex=raw.hex(), signature=signature))
            return dict(signature=signature)
        if command == 'training':
            if self.role != 'generator':
                raise ValueError('training custodian role')
            generation = request['generation']
            if type(generation) is not int or not 0 <= generation <= 3:
                raise ValueError('generation bounds')
            rows = self.tasks(generation, 8, f'training-{generation}')
            return self.record('training-release', dict(generation=generation, tasks=rows, operand_stratum=STRATA[self.role]))
        if command == 'observe':
            if self.role != 'observer':
                raise ValueError('training observation role')
            row, operation = request['task'], request['operation']
            family = QUERIES.index(row['query'])
            expected = result(self.operations[family], row['a'], row['b'])
            actual = result(operation, row['a'], row['b'])
            if row['expected'] != expected or row['a'] % 2 != 1:
                raise ValueError('generator target or declared training stratum differs from independent arithmetic')
            return self.record('actual-training-observation', dict(task=row['id'], operation=operation,
                actual=actual, expected=expected, correct=actual == expected))
        if command == 'observe_future':
            if self.role != 'observer':
                raise ValueError('independent future observation role')
            observed = request['observation']
            public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.material_keys[observed['role']]))
            public.verify(bytes.fromhex(observed['signature']), canonical({k:v for k,v in observed.items() if k != 'signature'}))
            body = observed['body']
            if observed['kind'] != 'actual-evaluation' or not 0 < body['starts_unix_micros'] < body['ends_unix_micros'] <= time.time_ns()//1000:
                raise ValueError('real observed future interval')
            outputs = {item['task']:item for item in body['outputs']}
            counts = {'candidate':0,'parent':0}
            for task in body['tasks']:
                expected = result(self.operations[QUERIES.index(task['query'])], task['a'], task['b'])
                stratum = STRATA[observed['role']]
                if expected != task['expected'] or task['a'] % stratum['a_modulus'] != stratum['a_residue']:
                    raise ValueError('independent future target/declared stratum')
                logged = outputs[task['id']]
                if (logged['logged_operation'] not in self.operations or logged['behavior_probability_q32'] != 2**30
                        or logged['logged_actual'] != result(logged['logged_operation'], task['a'], task['b'])
                        or logged['logged_correct'] != (logged['logged_actual'] == expected)
                        or not body['starts_unix_micros'] <= logged['decision_at'] <= logged['outcome_observed_at'] <= body['ends_unix_micros']):
                    raise ValueError('independent logged action/outcome/clock')
                for who in counts:
                    choices = body['choices' if who == 'candidate' else 'parent_choices']
                    actual = result(choices[task['query']], task['a'], task['b'])
                    if outputs[task['id']][who] != actual:
                        raise ValueError('independent future action execution')
                    correct = actual == expected
                    if correct != outputs[task['id']][who+'_correct']:
                        raise ValueError('independent future outcome')
                    counts[who] += correct
            if counts != body['counts'] or len(outputs) != len(body['tasks']):
                raise ValueError('independent future counts')
            return self.record('actual-future-observation', dict(name=body['name'], source_sha256=digest(observed),
                custody_role=observed['role'], counts=counts, starts_unix_micros=body['starts_unix_micros'],
                ends_unix_micros=body['ends_unix_micros'], sample_count=len(outputs)))
        if command in ('prepare_future', 'future', 'consumer'):
            if self.role not in ('evaluator', 'future-custodian'):
                raise ValueError('future custodian role')
            name = request['name']
            if not isinstance(name, str) or not 1 <= len(name) <= 80 or not all(c.isascii() and (c.isalnum() or c == '-') for c in name):
                raise ValueError('bounded future window name')
            if name in self.released:
                raise ValueError('future window already released')
            reservation = material = None
            if command == 'future':
                if name not in self.prepared:
                    raise ValueError('actual material must be sealed before native consumption')
                commitment, material, rows = self.prepared[name]
                manifest_raw = bytes.fromhex(request['material_manifest_hex'])
                if not 1 <= len(manifest_raw) <= 4 * 1048576:
                    raise ValueError('bounded actual material manifest')
                manifest = json.loads(manifest_raw)
                reservation = request['reservation']
                anchor = reservation['anchor']
                Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.observer_key)).verify(
                    bytes.fromhex(reservation['signature']), canonical(anchor))
                if anchor['holdout_digest'] != hashlib.sha256(manifest_raw).hexdigest():
                    raise ValueError('native reservation must bind actual sealed material manifest')
                for field in ('plan_digest', 'use_digest'):
                    if len(bytes.fromhex(anchor[field])) != 32 or anchor[field] == '0'*64:
                        raise ValueError('native holdout receipt identity')
                if not material['observed_unix_micros'] < anchor['recorded_unix_micros'] <= time.time_ns()//1000:
                    raise ValueError('actual material sealed before durable reservation')
                manifests = manifest['materials']
                if len(manifests) != 2 or {m['role'] for m in manifests} != set(self.material_keys):
                    raise ValueError('exact two-custodian material manifest')
                for entry in manifests:
                    Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.material_keys[entry['role']])).verify(
                        bytes.fromhex(entry['signature']), canonical({k:v for k,v in entry.items() if k != 'signature'}))
                if material not in manifests:
                    raise ValueError('own exact sealed material missing from native reservation')
                generation = commitment['body']['generation']
                candidate_choices = commitment['body']['choices']
                parent_choices = commitment['body']['parent_choices']
                sealed = (self.directory / material['body']['sealed_filename']).read_bytes()
                if sealed != canonical(rows) + b'\n' or hashlib.sha256(sealed).hexdigest() != material['body']['task_bytes_sha256']:
                    raise ValueError('sealed material changed before release')
            else:
                generation = request['generation']
                if type(generation) is not int or not 1 <= generation <= 3 or name in self.prepared:
                    raise ValueError('future window reused or outside profile')
                raw = Path(request['candidate']).read_bytes()
                if not 8 <= len(raw) <= 1048576 or hashlib.sha256(raw).hexdigest() != request['candidate_sha256']:
                    raise ValueError('candidate bytes differ from commitment')
                candidate_choices, parent_choices = request['choices'], request['parent_choices']
                commitment = self.record('candidate-commitment', dict(name=name, generation=generation,
                    candidate_sha256=request['candidate_sha256'], candidate_bytes=len(raw),
                    choices=candidate_choices, parent_choices=parent_choices))
                # The acknowledged immutable candidate precedes task randomness.
                # Only material commitments leave this process until reservation.
                rows = self.tasks(generation, 2048 if command == 'prepare_future' else 8, name)
                if command == 'prepare_future':
                    filename = name + '.sealed-tasks'
                    create(self.directory / filename, rows)
                    sealed = canonical(rows) + b'\n'
                    material = self.record('material-commitment', dict(name=name, generation=generation,
                        candidate_sha256=request['candidate_sha256'], commitment=digest(commitment),
                        sealed_filename=filename, task_bytes_sha256=hashlib.sha256(sealed).hexdigest(),
                        operand_stratum=STRATA[self.role],
                        task_bytes=len(sealed), sample_count=len(rows), task_ids=[row['id'] for row in rows]))
                    self.prepared[name] = commitment, material, rows
                    return material
            if command == 'future':
                del self.prepared[name]
            self.released.add(name)
            starts = time.time_ns() // 1000
            self.record('future-release', dict(name=name, commitment=digest(commitment), tasks=rows,
                material_commitment=digest(material) if material else None, reservation=reservation))
            started = time.monotonic_ns()
            outputs = []
            for row in rows:
                logged_operation = self.operations[secrets.randbelow(len(self.operations))]
                decision_at = time.time_ns() // 1000
                logged_actual = result(logged_operation, row['a'], row['b'])
                outcome_at = time.time_ns() // 1000
                predicted = {role: result(choices[row['query']], row['a'], row['b'])
                    for role, choices in [('candidate', candidate_choices), ('parent', parent_choices)]}
                outputs.append(dict(task=row['id'], **predicted,
                    logged_operation=logged_operation, logged_actual=logged_actual,
                    logged_correct=logged_actual == row['expected'], behavior_probability_q32=2**30,
                    decision_at=decision_at, outcome_observed_at=outcome_at,
                    candidate_correct=predicted['candidate'] == row['expected'],
                    parent_correct=predicted['parent'] == row['expected']))
            counts = {role: sum(row[f'{role}_correct'] for row in outputs) for role in ('candidate', 'parent')}
            # Eight tails: two windows, candidate/parent, lower/upper.
            # Hoeffding + union bound gives family alpha <= .05.
            # Unit of analysis is a task instance, never the number of actions.
            radius = math.sqrt(math.log(160) / (2 * len(rows)))
            intervals = {role: [max(0, math.floor((count / len(rows) - radius) * 2**32)),
                                min(2**32, math.ceil((count / len(rows) + radius) * 2**32))]
                         for role, count in counts.items()}
            return self.record('actual-evaluation', dict(name=name, generation=generation,
                commitment=digest(commitment), tasks=rows, outputs=outputs, counts=counts,
                choices=candidate_choices, parent_choices=parent_choices,
                material_commitment=digest(material) if material else None, reservation=reservation,
                intervals=intervals, task_execution_wall_ns=time.monotonic_ns() - started,
                starts_unix_micros=starts, ends_unix_micros=time.time_ns() // 1000,
                sample_count=len(rows)))
        if command == 'close':
            if self.prepared:
                raise ValueError('unreleased sealed material remains')
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return self.record('completed-process', dict(wall_ns=time.monotonic_ns() - self.started,
                cpu_user_seconds=usage.ru_utime, cpu_system_seconds=usage.ru_stime,
                peak_rss_bytes=usage.ru_maxrss * 1024))
        raise ValueError('unknown bounded study command')


def main():
    custodian = Custodian(sys.argv[1], sys.argv[2])
    while True:
        line = sys.stdin.buffer.readline(8 * 1048576 + 1)
        if not line:
            break
        if len(line) > 8 * 1048576:
            raise ValueError('bounded request')
        request = json.loads(line)
        started = time.monotonic_ns()
        response = custodian.handle(request)
        print(json.dumps(dict(result=response, wall_ns=time.monotonic_ns() - started)), flush=True)
        if request['command'] == 'close':
            break


if __name__ == '__main__':
    main()
