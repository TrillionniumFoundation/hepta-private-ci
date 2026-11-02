"""Freeze explicit first-order-only repair without changing numerical fixtures."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from adapter_common import ROOT, sha, write


def run(previous, defect):
    previous_hash = 'd3ada27411e77ebc4be99dd96e7f6895fbd844e0fd985e7506d682088ee3f4ce'
    defect_hash = '2a8e827c04c7d60ffff377fd18337f75c8ffd4362fac55f068055bccfeb7a42f'
    if sha(previous) != previous_hash or sha(defect) != defect_hash:
        raise ValueError('Wrong preserved protocol or independent defect witness')
    protocol = json.loads(previous.read_text())
    if sha(ROOT/'ADAPTER_FIXTURES.json') != protocol['fixture_sha256']:
        raise ValueError('Fixed input cases must not change')
    protocol['schema'] = 'hcsn.hx-autograd-protocol.v3'
    protocol['frozen_utc'] = datetime.now(timezone.utc).isoformat()
    names = ('hx_autograd.py', 'adapter_common.py', 'audit_gradients.py', 'training_smoke.py',
             'readout_evidence.py', 'verify_first_order_identity.py', 'freeze_first_order_v3.py')
    protocol['source_sha256'] = {name: sha(ROOT/name) for name in names}
    protocol['revision'] = {
        'previous_protocol_sha256': previous_hash, 'independent_defect_sha256': defect_hash,
        'reason': 'once_differentiable alone allowed silently incomplete second derivatives through composite readouts. V3 rejects grad-enabled backward at entry, before any no_grad wrapper; ordinary first-order contraction remains unchanged.',
        'retained_attempts': 'V1 serialization failure, complete V2 sources/first-order results, and independently reproduced V2 higher-order defect remain archived.',
        'evaluation_scope': 'Same already opened six functional cases, 168 directions, steps, tolerances and 80-step training configuration; no new financial holdout.'}
    protocol['higher_order_contract'] = 'At the first financial VJP with create_graph=True, reject explicitly for all five raw fields and all three composite readouts in both coordinates. Pure identity operations outside the financial graph are ordinary PyTorch operations, not a financial Hessian.'
    protocol['first_order_regression_identity'] = {
        'gradients_sha256': 'ac15ecd17abecb7cc4e18058f464689ff07cd7478bf5a33f735290af7c9cf022',
        'training_sha256': '1a00a8aa7b4e3756811b18cf3fc9f60dbe2ef6c0e4e068184bc79a14a2d110a7',
        'rule': 'All first-order matrices/directional records, every training loss/gradient and initial/final tensors must remain exactly identical; new error checks and timing are separate.'}
    print(json.dumps(write(ROOT/'ADAPTER_PROTOCOL.json', protocol), indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--previous', type=Path, required=True)
    p.add_argument('--defect', type=Path, required=True)
    a = p.parse_args()
    run(a.previous, a.defect)
