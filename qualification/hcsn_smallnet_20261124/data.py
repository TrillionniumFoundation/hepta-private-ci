"""Causal delayed-evidence task with disjoint generative source identities.

The label is sign(A+B), A,B iid uniform[-1,1]. Before B arrives the exact Bayes
accuracy is 3/4; after it arrives it is one. Thus waiting has a real information
opportunity. Sources change positive gain, nuisance correlation/noise and cue
arrival. These are simulated sources, not independent human or sensor datasets.
"""

from dataclasses import dataclass
import hashlib

import numpy as np
import torch


@dataclass(frozen=True)
class TaskBatch:
    x: torch.Tensor
    y: torch.Tensor
    source: torch.Tensor
    initial_margin: torch.Tensor
    late_step: torch.Tensor
    ids: tuple

    def select(self, indices):
        ids = tuple(self.ids[int(i)] for i in indices)
        return TaskBatch(self.x[:, indices], self.y[indices], self.source[indices],
                         self.initial_margin[indices], self.late_step[indices], ids)

    def digest(self):
        h = hashlib.sha256()
        for tensor in (self.x, self.y, self.source, self.initial_margin, self.late_step):
            a = tensor.detach().cpu().contiguous().numpy()
            h.update(str((a.dtype.str, a.shape)).encode())
            h.update(a.tobytes())
        h.update('\n'.join(self.ids).encode())
        return h.hexdigest()


SOURCE_IDS = {
    'smoke_train': tuple(range(10, 14)), 'smoke_dev': tuple(range(20, 22)),
    'train': tuple(range(100, 112)), 'dev': tuple(range(200, 204)),
    'test': tuple(range(300, 308)),
    'adapt_train': tuple(range(400, 406)), 'adapt_dev': tuple(range(500, 504)),
    'adapt_test': tuple(range(600, 608)),
}


def make_data(split, *, per_source=48, length=12, dtype=torch.float32):
    """No target is supplied in input; earlier prefixes never contain late B."""
    if split not in SOURCE_IDS or length < 10 or per_source < 1:
        raise ValueError('declared split, length >= 10, and positive size required')
    xs, ys, groups, margins, late_steps, ids = [], [], [], [], [], []
    for source in SOURCE_IDS[split]:
        rng = np.random.default_rng(20261124 + 1009 * source)
        n = per_source
        a, b = rng.uniform(-1, 1, (2, n))
        gain = rng.uniform(.85, 1.15)
        noise = rng.uniform(.08, .35)
        correlation = rng.uniform(-.5, .7)
        late = rng.integers(4, 7, n)
        if split.startswith('adapt'):
            noise *= 1.6
            late = rng.integers(5, 8, n)
        x = np.zeros((length, n, 6), dtype=np.float64)
        x[0, :, 0] = gain * a
        x[0, :, 2] = 1
        x[late, np.arange(n), 1] = gain * b
        x[late, np.arange(n), 3] = 1
        x[:, :, 4] = np.arange(length)[:, None] / (length - 1)
        for t in range(length):
            x[t, :, 5] = noise * rng.normal(size=n)
            if t:
                x[t, :, 5] += correlation * x[t - 1, :, 5]
        xs.append(x)
        ys.append((a + b > 0).astype(np.int64))
        groups.extend([source] * n)
        margins.append(rng.uniform(.45, .85, n))
        late_steps.append(late)
        ids.extend(f'{split}:{source}:{i}' for i in range(n))
    return TaskBatch(torch.as_tensor(np.concatenate(xs, 1), dtype=dtype),
                     torch.as_tensor(np.concatenate(ys)), torch.tensor(groups),
                     torch.as_tensor(np.concatenate(margins), dtype=dtype),
                     torch.as_tensor(np.concatenate(late_steps)), tuple(ids))


def probability_metrics(logits, batch, *, stop_confidence=.8, waiting_cost=.04):
    """Source is the uncertainty unit; outputs are descriptive, not p-values."""
    probabilities = logits.detach().double().softmax(-1)
    final = probabilities[-1]
    prediction = final.argmax(-1)
    target = torch.nn.functional.one_hot(batch.y, 2).double()
    per_source = {}
    for source in batch.source.unique().tolist():
        select = batch.source == source
        per_source[str(source)] = float((prediction[select] == batch.y[select]).double().mean())
    confidence = probabilities.max(-1).values
    eligible = confidence >= stop_confidence
    eligible[-1] = True
    stopping = eligible.to(torch.int64).argmax(0)
    columns = torch.arange(len(batch.y))
    stopped_prediction = probabilities[stopping, columns].argmax(-1)
    stop_accuracy = (stopped_prediction == batch.y).double().mean()
    cost = waiting_cost * stopping.double() / (len(logits) - 1)
    first = probabilities[0].argmax(-1)
    pre_late = probabilities[batch.late_step - 1, columns].argmax(-1)
    return {
        'accuracy': float((prediction == batch.y).double().mean()),
        'brier': float((final - target).square().sum(-1).mean()),
        'cross_entropy': float(torch.nn.functional.cross_entropy(logits[-1].double(), batch.y)),
        'early_accuracy': float((first == batch.y).double().mean()),
        'pre_late_accuracy': float((pre_late == batch.y).double().mean()),
        'stop_accuracy': float(stop_accuracy),
        'mean_stop_step': float(stopping.double().mean()),
        'stopping_utility': float(((stopped_prediction == batch.y).double() - cost).mean()),
        'stop_before_late_fraction': float((stopping < batch.late_step).double().mean()),
        'source_accuracy': per_source,
        'worst_source_accuracy': min(per_source.values()),
        'examples': len(batch.y), 'sources': len(per_source),
    }
