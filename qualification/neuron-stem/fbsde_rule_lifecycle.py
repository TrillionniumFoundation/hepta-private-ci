"""Research-only current-use fences around the existing finite TransferTable.

A table is historical evidence, not authority over its current environment.
This single-process slot models an owner's generation/revision checks; it does
not replace native inference/artifact owners, durable WAL or source attestation.
"""
from dataclasses import dataclass
import json
from threading import RLock
import time
from four_gate_common import digest, require
from fbsde_transfer import TransferProblem, TransferTable, OPS
from fbsde_role_program import describe

PROFILE = 'revocable_rule_transfer_v1'


def bounded_receipt(value):
    # Validate structure BEFORE retaining external data; malformed content cannot
    # raise during ledger serialization and leave a verified-use handle active.
    require(type(value) is dict and set(value) == {'request_sha256','effect'} and
        type(value['request_sha256']) is str and len(value['request_sha256']) <= 64 and
        type(value['effect']) in (tuple,list) and len(value['effect']) == 3 and
        all(type(x) is int and x.bit_length() <= 8 for x in value['effect']),
        'malformed or oversized source receipt')
    return dict(request_sha256=value['request_sha256'], effect=tuple(value['effect']))


@dataclass(frozen=True)
class UseTicket:
    slot: str
    revision: int
    sequence: int
    identity: str


class RuleSlot:
    """One live slot; old evidence/handles cannot restore its former revision.

    Source calls run outside the lock, then recheck the exact revision. Recovery
    has a lifetime attempt budget (including failures), not a fresh budget each
    time a mismatch occurs. History from a retired model is archived, not mixed
    with the NEW stationary-model hypothesis or erased from the audit trail.
    """
    def __init__(self, public, context, history, saved, *, recovery_limit=5):
        require(type(recovery_limit) is int and 0 <= recovery_limit <= 6, 'recovery attempt limit')
        self._public = json.loads(json.dumps(public))
        self._context = dict(context)
        self._problem = TransferProblem.build(public, context)
        full = dict(binding=self._problem.binding, **context)
        self._table = TransferTable.restore(saved, self._problem, history, full)
        self.identity = digest([PROFILE, public, context, saved])
        self._lock = RLock(); self._revision = 0; self._sequence = 0
        self._pending = {}; self._verifying = set(); self._state = 'active'; self._history = ()
        self._recovery_limit = recovery_limit; self._attempts = 0; self._recovery_inflight = None
        self._events = []; self._record('initial', snapshot=saved, history=history, context=context)

    def _record(self, event, **data):
        require(len(self._events) < 512, 'bounded lifecycle records')
        row = dict(event=event, revision=self._revision, state=self._state,
                   sequence=len(self._events), previous=digest(self._events[-1]) if self._events else None, **data)
        # Copies detach mutable caller-owned receipts and contexts.
        self._events.append(json.loads(json.dumps(row)))

    def _retire(self, reason):
        self._revision += 1; self._table = None; self._pending.clear(); self._verifying.clear()
        self._state = 'quarantined'; self._history = ()
        self._record('retire', reason=reason, attempts=self._attempts)

    def advance_generation(self, generation):
        with self._lock:
            require(type(generation) is int and generation > self._context['generation'], 'monotone owner generation')
            self._context['generation'] = generation
            self._retire('owner_generation_changed')
            self._problem = TransferProblem.build(self._public, self._context)
            self._record('context', context=self._context, problem=self._problem.identity)

    def begin(self, text, names, state):
        started = time.process_time_ns()
        with self._lock:
            require(self._state == 'active', 'rule is not currently active')
            require(len(self._pending) < 16, 'bounded pending uses')
            full = dict(binding=self._problem.binding, **self._context)
            value = self._table.apply(text, names, state, full)
            roles = describe(text, names)['roles']; normalized = tuple(state[j] for j in roles)
            self._sequence += 1
            request = dict(protocol=PROFILE, slot=self.identity, revision=self._revision,
                generation=self._context['generation'], environment=self._context['environment'],
                scope=self._context['scope'], sequence=self._sequence,
                state=normalized, table_sha256=digest(self._table.snapshot()), purpose='verify_use')
            ticket = UseTicket(self.identity, self._revision, self._sequence, digest(request))
            require(time.process_time_ns()-started <= 100_000_000, 'rule use CPU budget')
            self._pending[ticket] = (request, value, self._table.effects[OPS.index(normalized)], ticket)
            self._record('begin', ticket=ticket.__dict__, request=request, predicted=value)
            return ticket

    def _current(self, ticket):
        require(type(ticket) is UseTicket and ticket.slot == self.identity and
            ticket.revision == self._revision and self._state == 'active' and
            ticket in self._pending and self._pending[ticket][3] is ticket, 'stale, consumed or foreign rule use')
        return self._pending[ticket][:3]

    def verify(self, ticket, reveal):
        with self._lock:
            request, _, expected = self._current(ticket)
            require(ticket not in self._verifying, 'verification already in flight')
            self._verifying.add(ticket)
            request = dict(request); revision = self._revision
        started = time.process_time_ns(); receipt = None; error = None
        try: receipt = bounded_receipt(reveal(dict(request)))
        except Exception as exc: error = str(exc)[:512]
        cpu = time.process_time_ns()-started
        with self._lock:
            self._verifying.discard(ticket)
            self._record('verification', request=request, receipt=receipt, error=error, cpu_ns=cpu)
            # A response to a retired request cannot rehabilitate a model or publish.
            if revision != self._revision or ticket not in self._pending:
                self._record('late_receipt', request_sha256=digest(request)); return False
            valid = (error is None and type(receipt) is dict and
                     set(receipt) == {'request_sha256','effect'} and receipt['request_sha256'] == digest(request))
            if not valid:
                self._retire('invalid_or_missing_receipt'); return False
            effect = receipt['effect']
            typed = type(effect) in (list,tuple) and len(effect) == 3 and all(type(x) is int for x in effect)
            if not typed or tuple(effect) not in OPS:
                self._retire('unsupported_effect'); return False
            if OPS.index(tuple(effect)) != expected:
                self._retire('observed_rule_mismatch'); return False
            self._record('verification_match', request_sha256=digest(request))
            return True

    def finish(self, ticket):
        with self._lock:
            _, value, _ = self._current(ticket)
            require(ticket not in self._verifying, 'verification pending')
            del self._pending[ticket]
            self._record('finish', ticket=ticket.__dict__, value=value)
            return value

    def relearn(self, reveal):
        """Cheap first-informative experiments; caller cannot install old snapshots.

        Up to recovery_limit total source attempts for this slot. All current
        recovery observations filter the same new model. Receipt failure pauses
        acquisition with the attempt consumed. The next call resumes its history.
        """
        while True:
            begin = time.process_time_ns()
            with self._lock:
                if self._state == 'active': return True
                if self._state == 'refused': return False
                support = self._problem.support(self._history)
                agreed = self._problem.agreement(support)
                if all(x is not None for x in agreed):
                    full = dict(binding=self._problem.binding, **self._context)
                    table = TransferTable.from_support(self._problem, self._history, full)
                    self._table = TransferTable.restore(table.snapshot(), self._problem, self._history, full)
                    self._state = 'active'
                    self._record('reactivate', snapshot=table.snapshot(), history=self._history,
                                 attempts=self._attempts, context=self._context)
                    return True
                if self._attempts >= self._recovery_limit:
                    self._record('recovery_exhausted', attempts=self._attempts); return False
                state = next(i for i,x in enumerate(agreed) if x is None)
                request = dict(protocol=PROFILE, purpose='relearn', slot=self.identity,
                    revision=self._revision, generation=self._context['generation'],
                    environment=self._context['environment'], scope=self._context['scope'],
                    state=OPS[state], sequence=self._attempts, history_sha256=digest(self._history),
                    remaining=self._recovery_limit-self._attempts, declared_budget=self._recovery_limit)
                require(time.process_time_ns()-begin <= 100_000_000, 'recovery decision CPU budget')
                require(self._recovery_inflight is None, 'recovery already in flight')
                self._recovery_inflight = digest(request)
                self._attempts += 1; revision = self._revision
                self._record('recovery_request', request=request)
            start = time.process_time_ns(); receipt = None; error = None
            try: receipt = bounded_receipt(reveal(dict(request)))
            except Exception as exc: error = str(exc)[:512]
            with self._lock:
                self._recovery_inflight = None
                self._record('recovery_receipt', request=request, receipt=receipt, error=error,
                             cpu_ns=time.process_time_ns()-start)
                if revision != self._revision:
                    self._record('late_receipt', request_sha256=digest(request)); return False
                valid = (error is None and type(receipt) is dict and set(receipt) == {'request_sha256','effect'}
                         and receipt['request_sha256'] == digest(request))
                if not valid: return False
                effect = receipt['effect']
                if not (type(effect) in (tuple,list) and len(effect)==3 and all(type(x) is int for x in effect)
                        and tuple(effect) in OPS):
                    self._state = 'refused'; self._record('refuse', reason='unsupported_effect'); return False
                self._history += ((state, OPS.index(tuple(effect))),)
                try: self._problem.support(self._history)
                except ValueError:
                    self._state = 'refused'; self._record('refuse', reason='nonstationary_or_outside_family'); return False

    def status(self):
        with self._lock:
            return dict(state=self._state, revision=self._revision, context=dict(self._context),
                recovery_attempts=self._attempts, recovery_limit=self._recovery_limit, pending=len(self._pending))

    def records(self):
        with self._lock: return json.loads(json.dumps(self._events))
