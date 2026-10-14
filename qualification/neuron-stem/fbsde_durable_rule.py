"""Disk checkpoint adapter for the EXISTING research RuleSlot, not a new owner.

No process-local use handle is serialized or restored. Every restart quarantines
an active table; it cannot turn historical identification into current authority.
Recovery attempts survive crashes and current owner anchors prevent old backups.
"""
import json
import time
from four_gate_common import digest, require
from fbsde_rule_lifecycle import RuleSlot, bounded_receipt
from fbsde_transfer import TransferProblem, OPS
from fbsde_rule_checkpoint import RuleCheckpoint

PROFILE = 'durable_rule_checkpoint_v1'


class DurableRuleSlot(RuleSlot):
    def __init__(self, store, public, context, history, saved, *, recovery_limit=5):
        require(not store.rows(), 'new slot requires empty create-only store')
        self._store = store; self._dead = False
        try: super().__init__(public,context,history,saved,recovery_limit=recovery_limit)
        except BaseException:
            store.close()
            raise

    def _snapshot(self):
        return dict(public=self._public, identity=self.identity, context=self._context,
            revision=self._revision, sequence=self._sequence, state=self._state,
            history=self._history, attempts=self._attempts, limit=self._recovery_limit,
            pending=len(self._pending), verifying=len(self._verifying), inflight=self._recovery_inflight)

    def _record(self, event, **data):
        require(not self._dead, 'durable slot closed; owner reconciliation required')
        try:
            if event == 'begin': data['application'] = self._application
            super()._record(event, **data)
            self._store.append(self._events[-1], self._snapshot())
        except BaseException:
            self._dead = True; self._state = 'quarantined'; self._table = None
            self._pending.clear(); self._verifying.clear()
            raise

    def begin(self, text, names, state):
        started = time.process_time_ns()
        with self._lock:
            self._application = dict(text=text, names=list(names), state=list(state))
            try:
                ticket = super().begin(text, names, state)
                self._cpu_bound(started)
                return ticket
            finally: self._application = None

    def _cpu_bound(self, started):
        if time.process_time_ns()-started > 100_000_000:
            self._dead = True; self._table = None; self._pending.clear(); self._state = 'quarantined'
            raise ValueError('durable use process CPU budget exceeded')

    def finish(self, ticket):
        started = time.process_time_ns()
        with self._lock:
            result = super().finish(ticket)
            self._cpu_bound(started)
            return result

    def close(self):
        with self._lock:
            self._dead = True; self._state = 'quarantined'; self._table = None
            self._pending.clear(); self._verifying.clear(); self._store.close()

    def checkpoint_anchor(self):
        with self._lock:
            require(not self._dead, 'closed slot has no new acknowledgement')
            return self._store.anchor()

    def verify(self, ticket, reveal):
        def durable_intent(request):
            with self._lock:
                # Persist pending source work BEFORE entering the external callback.
                self._record('verification_intent', request=request)
            return reveal(request)
        return super().verify(ticket, durable_intent)

    @classmethod
    def reopen(cls, store, current_context):
        """Owner-supplied current context, independently anchored store, no handles.

        An unfinished recovery retains its observations/attempts. A previously
        active table is retired and needs fresh recovery. Silent drift, root-directory
        replacement, and stale owner anchors remain outside this local guarantee.
        """
        try: return cls._restore(store, current_context)
        except BaseException:
            store.close()
            raise

    @classmethod
    def _restore(cls, store, current_context):
        rows = store.rows(); require(rows and rows[0]['event']['event'] == 'initial', 'missing initial checkpoint')
        original = rows[0]['event']; saved = rows[-1]['snapshot']
        public = saved['public']; old = saved['context']
        require(type(current_context) is dict and set(current_context) == set(old) and
            all(current_context[k] == old[k] for k in ('scope','environment')) and
            type(current_context['generation']) is int and current_context['generation'] >= old['generation'],
            'current owner context rollback or foreign environment')
        # Replay retained states and accounting, not merely hash validation.
        from fbsde_checkpoint_audit import validate_rows
        validate_rows(rows)
        value = object.__new__(cls)
        value._dead = False
        # Bootstrap the original already-qualified table without appending it again.
        value._store = _BootstrapSink()
        RuleSlot.__init__(value, public, original['context'], tuple(map(tuple,original['history'])),
            original['snapshot'], recovery_limit=saved['limit'])
        require(value.identity == saved['identity'], 'checkpoint source identity')
        value._events = [r['event'] for r in rows]
        value._context = dict(current_context); value._problem = TransferProblem.build(public,current_context)
        value._revision = saved['revision']+1; value._sequence = saved['sequence']
        value._attempts = saved['attempts']; value._pending.clear(); value._verifying.clear()
        value._recovery_inflight = None; value._table = None
        value._state = 'refused' if saved['state'] == 'refused' else 'quarantined'
        value._history = tuple(map(tuple,saved['history'])) if saved['state'] != 'active' else ()
        if current_context['generation'] > old['generation']: value._history = ()
        last = rows[-1]['event']
        # The parent's recovery_receipt is recorded just BEFORE applying its effect.
        # Reconcile this precise crash boundary once; never lose a paid observation.
        if last['event'] == 'recovery_receipt' and current_context == old:
            req, receipt = last['request'], last['receipt']
            if req['revision'] == saved['revision'] and last['error'] is None and receipt is not None:
                receipt = bounded_receipt(receipt)
                if receipt['request_sha256'] == digest(req):
                    effect = tuple(receipt['effect'])
                    if effect not in OPS: value._state = 'refused'
                    else:
                        value._history += ((OPS.index(tuple(req['state'])), OPS.index(effect)),)
                        try: value._problem.support(value._history)
                        except ValueError: value._state = 'refused'
        value._store = store
        value._record('restart_quarantine', prior_state=saved['state'], current_context=current_context,
            no_handles_restored=True, attempts=value._attempts)
        return value


class _BootstrapSink:
    def append(self, *_): pass
