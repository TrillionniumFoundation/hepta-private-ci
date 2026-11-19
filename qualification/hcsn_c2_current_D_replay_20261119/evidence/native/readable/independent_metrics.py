"""Independent NumPy metrics; trainer metric code is never called."""

import numpy as np
from audit_io import require


def metrics(logits, labels):
    logits, labels = np.asarray(logits), np.asarray(labels)
    require(logits.ndim == 2 and logits.shape[1] == 11 and len(logits) > 0, 'expected N by 11 logits')
    require(labels.shape == (len(logits),) and labels.dtype.kind in 'iu'
            and np.all((0 <= labels) & (labels < 11)) and np.isfinite(logits).all(), 'invalid logits/labels')
    shifted = logits - logits.max(axis=1, keepdims=True)
    logp = shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))
    probability, predicted = np.exp(logp), logits.argmax(axis=1)
    matrix = np.zeros((11, 11), dtype=np.int64)
    np.add.at(matrix, (labels, predicted), 1)
    support, output, correct = matrix.sum(axis=1), matrix.sum(axis=0), matrix.diagonal()
    f1 = np.divide(2 * correct, support + output, out=np.zeros(11), where=support + output > 0)
    confidence = probability.max(axis=1)
    bins = np.minimum(14, np.floor(confidence * 15).astype(int))
    ece = 0.
    for index in range(15):
        selected = bins == index
        if selected.any():
            ece += selected.mean() * abs(confidence[selected].mean() - (predicted[selected] == labels[selected]).mean())
    squared = np.square(probability - np.eye(11)[labels])
    return dict(events=len(labels), accuracy=float(np.mean(predicted == labels)),
                macro_f1_11_classes=float(f1.mean()), macro_f1_present_classes=float(f1[support > 0].mean()),
                balanced_accuracy_present_classes=float(np.mean(correct[support > 0] / support[support > 0])),
                nll=float(-logp[np.arange(len(labels)), labels].mean()),
                brier_half_sum=float(.5 * squared.sum(axis=1).mean()), brier_mean_classes=float(squared.mean()),
                ece_15_equal_width_bins=float(ece), confusion_matrix=matrix.tolist())


def compare_metrics(actual, expected, tolerance):
    require(set(actual) == set(expected), 'metric schema differs')
    require(actual['confusion_matrix'] == expected['confusion_matrix'], 'confusion matrix differs')
    require(actual['events'] == expected['events'], 'event count differs')
    difference = {key: abs(actual[key] - expected[key]) for key in actual if key != 'confusion_matrix'}
    require(all(np.isfinite(value) and value <= tolerance for value in difference.values()),
            'full-D metric mismatch: ' + str(difference))
    return difference
