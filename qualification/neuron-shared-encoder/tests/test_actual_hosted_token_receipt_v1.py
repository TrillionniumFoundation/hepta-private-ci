"""Pure stdlib, no physical weights required to exercise archive rejection gates."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import struct
from zipfile import ZipFile

import pytest

from neuron_shared_encoder.actual_hosted_token_receipt_v1 import (
    _json, _safe_tensor_layout, audit_blob, sha,
    ARTIFACT_SHA256, EXPECTED_TENSORS, MODEL_ID,
)

REPO = Path(__file__).resolve().parents[1]


def test_frozen_actual_result_is_explicitly_non_authorizing():
    r = json.loads((REPO / 'ACTUAL_MODERNBERT_TOKEN_RESULT_20261015.json').read_text())
    assert r['schema'] == 'hepta.neuron.actual-hosted-token-archive-review.shadow.v1'
    assert r['artifact_zip_sha256'] == ARTIFACT_SHA256
    assert r['model_id'] == MODEL_ID
    assert r['actual_head_checkpoint_count'] == 12
    assert r['actual_original_holdout_cases'] == 32
    assert r['repeated_training_seeds'] == [11, 23, 47]
    assert r['max_original_input_tokens'] == 152
    assert r['mean_holdout_by_arm']['pooled_cached']['accuracy'] == pytest.approx(.61458333333)
    assert r['mean_holdout_by_arm']['token_query_prepared']['accuracy'] == pytest.approx(.60416666666)
    assert r['paired_token_minus_pooled']['accuracy']['point_estimate'] == pytest.approx(-.0104166666666)
    assert r['paired_token_minus_pooled']['brier']['point_estimate'] == pytest.approx(-.00456075231323)
    assert r['paired_token_minus_pooled']['nll']['point_estimate'] == pytest.approx(-.00815290111489)
    assert r['production_admission'] == 'BLOCKED'
    assert r['selection_authorized'] is False
    assert r['actual_future_outcomes_evaluated'] is False
    assert r['case_level_bootstrap_recomputed_from_original_predictions'] is False
    assert r['source_use_licence_independently_granted'] is False


def test_sha_fails_closed_on_wrong_artifact_and_bad_digest():
    with pytest.raises(ValueError, match='ZIP digest mismatch'):
        audit_blob(b'PK' + bytes(200), 'a' * 64)
    with pytest.raises(ValueError, match='exact artifact digest'):
        audit_blob(b'PK' + bytes(200), 'THIS_IS_NOT_A_SHA')


def test_extra_or_missing_zip_member_rejected_even_with_matching_self_hash():
    b = io.BytesIO()
    with ZipFile(b, 'w') as z:
        z.writestr('malicious.py', 'print("not executed")')
    raw = b.getvalue()
    with pytest.raises(ValueError, match='missing, extra or duplicate'):
        audit_blob(raw, sha(raw))


@pytest.mark.parametrize('data', [
    b'{"a":1,"a":2}\n', b'{"a":NaN}\n', b'{"a":1}',
    b'{"a":1}  \n', b'[]\n', b'{"a":Infinity}\n',
])
def test_json_rejects_duplicate_noncanonical_nonfinite_and_array(data):
    with pytest.raises(ValueError):
        _json(data)


def make_safe_tensor():
    offset = 0
    layout = {}
    for name, shape in sorted(EXPECTED_TENSORS.items()):
        size = 4
        for d in shape:
            size *= d
        layout[name] = {'dtype': 'F32', 'shape': shape,
                        'data_offsets': [offset, offset + size]}
        offset += size
    head = json.dumps(layout, separators=(',', ':')).encode()
    return struct.pack('<Q', len(head)) + head + bytes(offset)


def test_safe_tensors_layout_accepts_bounded_untrusted_read_only_bytes():
    _safe_tensor_layout(make_safe_tensor())


@pytest.mark.parametrize('fault', ['corrupt_length', 'bad_dtype', 'wrong_shape',
                                   'overlap', 'trailing_bytes', 'header_keys'])
def test_safetensors_rejects_malformed_layout(fault):
    raw = make_safe_tensor()
    n = struct.unpack('<Q', raw[:8])[0]
    hdr = json.loads(raw[8:8+n])
    if fault == 'corrupt_length':
        altered = struct.pack('<Q', 65535) + raw[8:]
    else:
        if fault == 'bad_dtype':
            hdr['query']['dtype'] = 'F16'
        elif fault == 'wrong_shape':
            hdr['query']['shape'] = [2, 384]
        elif fault == 'overlap':
            hdr['query']['data_offsets'] = [0, 3072]
        elif fault == 'header_keys':
            hdr['query']['command'] = 'RUN'
        body = json.dumps(hdr, separators=(',', ':')).encode()
        altered = struct.pack('<Q', len(body)) + body + raw[8+n:]
        if fault == 'trailing_bytes':
            altered += b'X'
    with pytest.raises(ValueError):
        _safe_tensor_layout(altered)


def test_hosted_artifact_can_be_reaudited_when_explicitly_staged():
    """CI can set HEPTA_RESEARCH_ARTIFACT_ZIP; otherwise no fabricated substitute."""
    file = os.environ.get('HEPTA_RESEARCH_ARTIFACT_ZIP')
    if file is None:
        pytest.skip('pinned actual GitHub artifact not staged in this isolated test')
    result = audit_blob(Path(file).read_bytes(), ARTIFACT_SHA256)
    pinned = json.loads((REPO / 'ACTUAL_MODERNBERT_TOKEN_RESULT_20261015.json').read_text())
    assert result == pinned
    assert result['production_admission'] == 'BLOCKED'
