"""Measured requested-view attempts; retain failures without granting a prediction.

This research journal is not native WAL, authentication or a timeout/preemption
service. The CPU limit is checked after the call; an overrun never reaches policy.
"""
import os
import time

from four_gate_common import canonical, digest, require
from four_gate_capture import tensor_digest

VIEW_CPU_LIMIT_NS = 100_000_000


class ViewBudgetExceeded(ValueError):
    """A completed physical call exceeded its unchanged admitted CPU budget."""


class AttemptJournal:
    """Write-once, hash-chained observations; fsync failures and final closure."""
    def __init__(self, path):
        self.stream = path.open('xb')
        self.previous = None
        self.sequence = 0

    def append(self, record):
        row = {**record, 'sequence': self.sequence, 'previous_sha256': self.previous}
        identity = digest(row)
        self.stream.write(canonical({**row, 'attempt_sha256': identity}) + b'\n')
        self.stream.flush()
        if row['status'] != 'returned':
            os.fsync(self.stream.fileno())
        self.previous = identity
        self.sequence += 1
        return identity

    def close(self):
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.stream.close()


def observe_view(view, text_source, encode, normalize, head, torch, head_identity,
                 journal, context, *, cpu_clock=time.process_time_ns,
                 wall_clock=time.perf_counter_ns):
    """Measure text/Encoder/Head/receipt work, then journal before returning.

    Serialization and hashing belong to view work. Journal I/O is excluded from
    the 100 ms view ceiling but INCLUDED in the caller's request/run envelope.
    A failed observation has no returned symbol, and the trial aborts unchanged.
    """
    start = cpu_clock(); wall = wall_clock()
    stages = {}; receipt = None; text_hash = None; stage = 'text'
    try:
        text = text_source(view)
        text_hash = digest(text)
        after = cpu_clock(); stages['text_cpu_ns'] = after-start
        stage = 'encoder'; before = after
        with torch.inference_mode():
            vector = encode([text])
        after = cpu_clock(); stages['encoder_cpu_ns'] = after-before
        stage = 'head'; before = after
        with torch.inference_mode():
            p = head(normalize(vector)).softmax(-1)[0]
        after = cpu_clock(); stages['head_cpu_ns'] = after-before
        stage = 'receipt'; before = after
        require(torch.isfinite(p).all().item(), 'nonfinite actual observation')
        probabilities = p.tolist()
        require(all(0 <= q <= 1 for q in probabilities) and abs(sum(probabilities)-1) < 1e-5,
                'invalid actual observation distribution')
        symbol = int(p.argmax().item())
        receipt = {'kind': 'actual_requested_forward', 'text_sha256': text_hash,
                   'vector_sha256': tensor_digest(vector), 'probabilities': probabilities,
                   'head_sha256': head_identity}
        after = cpu_clock(); stages['receipt_cpu_ns'] = after-before
        elapsed = after-start
        require(elapsed >= 0 and all(v >= 0 for v in stages.values()), 'nonmonotone CPU clock')
    except Exception as error:
        journal.append({**context, 'view': view, 'head_sha256': head_identity,
            'text_sha256': text_hash, 'status': 'execution_error', 'stage': stage,
            'error_type': type(error).__name__, 'phase_cpu_ns': stages,
            'cpu_ns': max(0, cpu_clock()-start), 'wall_ns': max(0, wall_clock()-wall),
            'limit_ns': VIEW_CPU_LIMIT_NS, 'prediction_returned': False})
        raise
    status = 'returned' if elapsed <= VIEW_CPU_LIMIT_NS else 'budget_exceeded'
    receipt.update(cpu_ns=elapsed, phase_cpu_ns=stages)
    record = {**context, 'view': view, 'head_sha256': head_identity,
              'text_sha256': text_hash, 'status': status, 'phase_cpu_ns': stages,
              'cpu_ns': elapsed, 'wall_ns': wall_clock()-wall,
              'limit_ns': VIEW_CPU_LIMIT_NS, 'prediction_returned': status == 'returned',
              'computed_receipt_sha256': digest(receipt)}
    receipt['attempt_sha256'] = journal.append(record)
    if status != 'returned':
        raise ViewBudgetExceeded('per-view CPU budget exceeded; rejected attempt retained')
    return symbol, receipt
