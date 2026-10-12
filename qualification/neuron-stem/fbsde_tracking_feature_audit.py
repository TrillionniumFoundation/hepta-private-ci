"""Original-source binding of feature slots, proposals and state transitions.

No Torch, Encoder, learner or forward executor import. Checks consistency only,
not independent execution attestation, timing stability or natural-language truth.
"""
from pathlib import Path
import math
import re
from four_gate_common import digest, require, strict_loads
from fbsde_tracking_audit import audit_record, source_parts
from fbsde_tracking_features import audit_features


def audit(directory, originals):
    root = Path(directory)
    def read(name):
        path = root/name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size < 64*1024*1024,
                'bounded regular observation')
        return strict_loads(path.read_bytes())
    plan = read('plan.json'); feature_plan = read('feature-plan.json'); batches = read('encoding-batches.json')
    require(plan['feature_profile'] == feature_plan['feature_profile'], 'feature profile drift')
    expected = digest({'pipeline': {'encoder': feature_plan['encoder_identity'], 'scope': feature_plan['scope'],
                                   'generation': feature_plan['generation']}, 'profile': plan['feature_profile']})
    require(feature_plan['feature_binding'] == expected, 'feature identity drift')
    proposals = read('proposals.json'); report = audit_features(feature_plan, batches, proposals)
    by_id = {r['source_id']: r for r in originals}; index = {}; denied = []
    require(len(by_id) == len(originals), 'duplicate original source ID')
    for number, row in enumerate(proposals):
        require(row['source_id'] in by_id and row['arm'] in plan['arms'], 'proposal source/arm')
        text = by_id[row['source_id']]['input']; initial, operations, _, _ = source_parts(text)
        sentences = re.findall(r'(?:First|Then|Next|After that|Finally), [A-Z][a-z]+ and [A-Z][a-z]+ '
                               r'(?:swap books|switch partners|swap balls|swap their gifts|trade positions)\.', text)
        i = row['event_index']; names = tuple(initial)
        require(type(i) is int and 0 <= i < len(sentences), 'proposal event index')
        keys = [re.sub(r'\b('+'|'.join(re.escape(n) for n in names)+r')\b',
                       lambda m: 'SELF' if m[0] == name else 'OTHER', sentences[i]) for name in names]
        require(row['source_slot_texts'] == keys and row['texts_sha256'] == digest(keys), 'original event changed')
        scores = row['scores']
        require(len(scores) == len(names) and all(type(v) is float and math.isfinite(v) for v in scores), 'scores')
        key = (row['source_id'], row['arm'], i)
        require(key not in index, 'duplicate source/arm/event proposal'); index[key] = row
        if not row['returned']:
            require(number == len(proposals)-1, 'denied proposal followed by further policy work'); denied.append(key)
    outputs = 0
    for arm in plan['arms']:
        for record in read(arm+'.json'):
            source = by_id[record['source_id']]
            audit_record(source['input'], record)
            outputs += 1
            if arm in ('frozen_recurrent','learned_recurrent','verified_recurrent','fault_verified'):
                for step in record['trace']:
                    key = (record['source_id'], arm, step['index'])
                    require(key in index and index[key]['returned'], 'state applied absent/denied proposal')
                    row = index[key]; chosen = sorted(range(len(row['scores'])), key=lambda i: (-row['scores'][i],i))[:2]
                    if not (arm == 'fault_verified' and step['index'] == 0):
                        require(list(step['proposal']) == chosen, 'state proposal differs from recorded model output')
    report.update({'state_outputs_checked': outputs, 'denied_proposals': len(denied),
                   'complete_study': (root/'results.json').is_file(),
                   'model_execution_authenticated': False, 'budget_stability_established': False})
    return report
