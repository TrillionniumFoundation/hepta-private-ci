"""Final interface version over pinned Granite; no task quality scoring."""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

import torch

sys.path.insert(0, '/workspace/scratch/f1f83ab8f2f0/hepta/qa/stem-bakeoff')
from real_encoder import FrozenRealEncoder
from shared_feature_extract import SharedFeatureEncoder
from shared_feature_contract import SourceEvent

torch.set_num_threads(2)
root = Path(__file__).parent
meta = json.loads(Path('/tmp/hepta-granite97m-sealed-20261023.acquisition.json').read_text())
owner = FrozenRealEncoder(candidate='granite97m', snapshot='/tmp/hepta-granite97m-sealed-20261023',
    revision=meta['revision'], expected_inventory_sha256=meta['inventory_sha256'],
    operator_accepted_terms=True, max_tokens=128)
shared = SharedFeatureEncoder(owner)
texts = ['AttributeError after a missing dependency import. Read the traceback before selecting a repair.',
         '判断证据是否冲突；必要时回读原始日志。']
events = [SourceEvent('interface-smoke:en', 'v1', observed_at_ns=time.time_ns()),
          SourceEvent('interface-smoke:zh', 'v1', observed_at_ns=time.time_ns())]
detail = shared.extract_text(texts, events=events, expected_identity=owner.identity, retention='tokens')
detail_receipt = dict(shared.last_receipt)
global_only = shared.extract_text(texts, events=events, expected_identity=owner.identity)
difference = float((detail.read_global()-global_only.read_global()).abs().max())
assert difference == 0.0
assert global_only.read_tokens() is None
assert detail.feature_identity_digest == global_only.feature_identity_digest
assert detail_receipt['model_forward_calls'] == shared.last_receipt['model_forward_calls'] == 1
result = {'candidate':owner.candidate, 'inputs':texts, 'events':[asdict(v) for v in events],
    'detail_shape':list(detail.read_tokens().shape), 'global_shape':list(global_only.read_global().shape),
    'max_global_difference':difference, 'extractor_sha256':shared.extractor_sha256,
    'detail_character_span_count':int(detail.read_locations()['char_valid'].sum()),
    'same_feature_identity':detail.feature_identity_digest == global_only.feature_identity_digest,
    'detail_manifest':detail.manifest(), 'global_manifest':global_only.manifest(),
    'detail_receipt':detail_receipt, 'global_receipt':shared.last_receipt,
    'input_kind':'execution-fixture-without-quality-labels', 'quality_qualified':False,
    'authority':'DENY_ALL'}
(root/'granite_final_receipt.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'candidate':owner.candidate,'retained_modes':{
    'tokens':detail.retained_tensor_bytes,'global':global_only.retained_tensor_bytes},
    'max_global_difference':difference,'feature_identity':detail.feature_identity_digest,
    'extractor_sha256':shared.extractor_sha256}))
