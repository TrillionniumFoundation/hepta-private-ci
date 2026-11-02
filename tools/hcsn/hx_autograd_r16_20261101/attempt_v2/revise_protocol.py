"""Additive evidence-serialization repair; all numerical inputs/gates unchanged."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from adapter_common import ROOT, sha, write


def run(previous, failure):
    original = 'c633073b4ce6ac71468cb92c96edbd895956d10d8f3f7d3b122b778bc15e7c52'
    if sha(previous) != original:
        raise ValueError('Wrong initial protocol')
    protocol = json.loads(previous.read_text())
    if sha(ROOT/'ADAPTER_FIXTURES.json') != protocol['fixture_sha256']:
        raise ValueError('Fixtures must remain unchanged')
    if sha(ROOT/'hx_autograd.py') != protocol['source_sha256']['hx_autograd.py']:
        raise ValueError('The adapter is unchanged in this serialization revision')
    protocol['schema'] = 'hcsn.hx-autograd-protocol.v2'
    protocol['frozen_utc'] = datetime.now(timezone.utc).isoformat()
    protocol['source_sha256'] = {name: sha(ROOT/name) for name in (*protocol['source_sha256'], 'revise_protocol.py')}
    protocol['revision'] = {'previous_protocol_sha256': original, 'retained_failure_sha256': sha(failure),
                            'reason': 'Initial evidence serialization rejected numpy.int64. Only receipt predicates are converted to Python bool. Financial kernel, adapter, fixtures, finite-difference steps and all thresholds are unchanged.',
                            'evaluation_scope': 'The same opened fixed integration fixtures are rerun; no new independent financial validation is claimed.'}
    print(json.dumps(write(ROOT/'ADAPTER_PROTOCOL.json', protocol), indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--previous', type=Path, required=True)
    p.add_argument('--failure', type=Path, required=True)
    a = p.parse_args()
    run(a.previous, a.failure)
