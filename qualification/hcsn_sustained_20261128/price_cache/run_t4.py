"""Cloud runtime entry. Unpack only the hashes and input names sealed for this experiment."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
import zlib

INPUTS = {}  # replaced in the sealed single-file cloud worker
REQUEST = 'hcsn-price-native-1140569-20261128'


def control(torch, validation):
    """Ordinary linear image classifier trained with the same 16 minibatches."""
    import numpy as np
    torch.manual_seed(314)
    x, y, (train, dev, test) = validation.data()
    torch.cuda.synchronize()
    start = time.perf_counter()
    features = torch.as_tensor(x, device='cuda', dtype=torch.float64).flatten(1)
    labels = torch.as_tensor(y, device='cuda', dtype=torch.long)
    classifier = torch.nn.Linear(features.shape[1], 2, device='cuda', dtype=torch.float64)
    optimizer = torch.optim.AdamW(classifier.parameters(), lr=.016, weight_decay=.001)
    for rows in np.random.default_rng(314).choice(train, (16, 8)):
        optimizer.zero_grad(set_to_none=True)
        torch.nn.functional.cross_entropy(classifier(features[rows]), labels[rows]).backward()
        optimizer.step()

    def score(rows):
        with torch.no_grad():
            logits = classifier(features[rows])
            truth = labels[rows]
            acc = [(logits.argmax(1)[truth == c] == c).double().mean().item() for c in (0, 1)]
            return {'balanced_accuracy': sum(acc) / 2,
                    'ce': torch.nn.functional.cross_entropy(logits, truth).item()}

    scores = {'dev': score(dev), 'heldout': score(test)}
    torch.cuda.synchronize()
    return {'family': 'linear flattened image', 'parameters': sum(p.numel() for p in classifier.parameters()),
            'seed': 314, 'updates': 16, 'batch': 8, 'quality': scores,
            'input_already_loaded_fit_and_final_evaluations_s': time.perf_counter() - start}


def run(report):
    import torch
    report.update(framework=str(torch.__version__), framework_cuda=torch.version.cuda,
                  cuda_available=torch.cuda.is_available())
    if not torch.cuda.is_available():
        raise RuntimeError('Requested a T4. Torch reports no CUDA device.')
    device = torch.cuda.get_device_name()
    report['gpu'] = device
    if 'T4' not in device:
        raise RuntimeError('Observed a different device: ' + device)
    x = torch.arange(8, dtype=torch.float32, device='cuda')
    report['cuda_dot'] = (x @ x).item()
    if report['cuda_dot'] != 140.:
        raise RuntimeError('CUDA dot product failed')
    expected = {'population.py', 'he_xiong.py', 'fft_transport.py', 'digits01.npz', 'validate_prices.py'}
    if set(INPUTS) != expected:
        raise ValueError('Unexpected bundle components')
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for name, row in INPUTS.items():
            data = zlib.decompress(base64.b64decode(row['bytes'], validate=True))
            if hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('Source digest mismatch on ' + name)
            (folder / name).write_bytes(data)
        sys.path.insert(0, str(folder))
        import validate_prices
        output = folder / 'training.json'
        torch.set_num_threads(1)
        report['linear_control'] = control(torch, validate_prices)
        report['comparison'] = validate_prices.supervise('cuda', output, seeds=(314,))
        report['passed'] = True


if __name__ == '__main__':
    start = time.time()
    report = {'request_id': REQUEST, 'requested_device': 'T4', 'passed': False, 'start_unix': start,
              'inputs': {name: row['sha256'] for name, row in INPUTS.items()}}
    try:
        run(report)
    except Exception:
        report['error'] = traceback.format_exc()[-3000:]
    report['end_unix'] = time.time()
    Path('cloud_result.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
