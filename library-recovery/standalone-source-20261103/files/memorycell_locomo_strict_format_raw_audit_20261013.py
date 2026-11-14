#!/usr/bin/env python3
"""Read-only, label-free paired audit of two ORIGINAL LoCoMo Qwen answer ZIPs.

A citation label only proves source delivery, not semantic support. Do not
read benchmark gold, normalize original answers, or promote either intervention.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

OLD_SHA = '14dc63bfb0e25b8b15f7b48ba8e1afd4cef4d13f8617d08d28a533baa7a202a0'
NEW_SHA = '25e7fc3d60e53328a49efabcd34df4a6e223a43e16cc2aff1790824a31150b74'
OLD_COMMIT = '2db775a9b423f5d53c2ec1cf69d4e67da02e35bd'
NEW_COMMIT = 'c34e73312e9ef1626712f984d4c70c50af335aef'
REFUSAL = 'I do not have enough evidence.'
CITE = re.compile(r'\[(E[1-9][0-9]*)\]')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(raw):
    def pairs(items):
        ans = {}
        for key, val in items:
            if key in ans:
                raise ValueError('duplicate JSON field')
            ans[key] = val
        return ans
    def invalid(name):
        raise ValueError('nonfinite JSON number')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)


def sealed(path, expected):
    raw = path.read_bytes()
    if sha(raw) != expected or len(raw) > 8 * 1024 * 1024:
        raise ValueError('original artifact SHA mismatch')
    with zipfile.ZipFile(path) as z:
        members = {}
        for item in z.infolist():
            posix = PurePosixPath(item.filename)
            if (item.is_dir() or posix.is_absolute() or '..' in posix.parts
                or '\\' in item.filename or stat.S_ISLNK(item.external_attr >> 16)
                or item.filename in members):
                raise ValueError('invalid ZIP member')
            members[item.filename] = z.read(item)
    if not 0 < len(members) <= 24 or 'SHA256SUMS' not in members:
        raise ValueError('invalid original artifact census')
    listed = set()
    for row in members['SHA256SUMS'].decode().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (?:\./)?(.+)', row)
        if not match:
            raise ValueError('bad manifest row')
        digest, filename = match.groups()
        if filename in listed or filename not in members or sha(members[filename]) != digest:
            raise ValueError('tampered ZIP manifest')
        listed.add(filename)
    if listed != set(members) - {'SHA256SUMS'}:
        raise ValueError('missing manifest member')
    return members


def census(members, commit):
    ready = read_json(members['run/READY.json'])
    if (members['tested-commit.txt'].decode().strip() != commit
        or ready['generating_commit'] != commit
        or ready['planned'] != 16 or ready['succeeded'] != 16
        or ready['failed'] != 0
        or ready['raw_sha256'] != sha(members['run/raw-answers.jsonl'])
        or ready['production_accepted'] is not False):
        raise ValueError('incomplete original reader source')
    raw = members['run/raw-answers.jsonl']
    if not raw.endswith(b'\n'):
        raise ValueError('incomplete original answer journal')
    records = [read_json(x) for x in raw.splitlines()]
    if (len(records) != 16 or len({x['question_id'] for x in records}) != 16
        or any(x['status'] != 'succeeded' for x in records)
        or any(x['mode'] not in ('publisher_support', 'publisher_refusal_support') for x in records)):
        raise ValueError('missing/duplicate original inference')
    if ready['original_decisions_zip_sha256'] != '3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097':
        raise ValueError('original frozen input plan changed')
    return ready, {x['question_id']:x for x in records}


def metrics(rows):
    result = dict(exact_refusal=0, refusal_mixed_with_other_text=0,
                  answers_with_delivered_citations=0, undelivered_citation_labels=0,
                  input_tokens=0, output_tokens=0, cumulative_reader_seconds=0.0)
    for row in rows.values():
        answer = row['answer']
        refusal_present = REFUSAL.lower() in answer.lower()
        result['exact_refusal'] += answer == REFUSAL
        result['refusal_mixed_with_other_text'] += refusal_present and answer != REFUSAL
        available = {x['label'] for x in row['receipt']['delivered_evidence']}
        cited = set(CITE.findall(answer))
        result['answers_with_delivered_citations'] += bool(cited)
        result['undelivered_citation_labels'] += len(cited - available)
        result['input_tokens'] += row['receipt']['input_tokens']
        result['output_tokens'] += row['receipt']['generated_tokens']
        result['cumulative_reader_seconds'] += row['receipt']['seconds']
        if (type(row['receipt']['answer_postprocessed']) is not bool
            or row['receipt']['answer_postprocessed']):
            raise ValueError('unsealed generated answer')
    return result


def audit(old_path, new_path):
    a = sealed(old_path, OLD_SHA)
    b = sealed(new_path, NEW_SHA)
    old, before = census(a, OLD_COMMIT)
    new, after = census(b, NEW_COMMIT)
    if (old['reader_identity'] != new['model_identity']
        or old['original_public_zip_sha256'] != new['original_public_zip_sha256']
        or old['privileged_plan_sha256'] != new['original_plan_sha256']
        or old['publisher_support_retrieval_privileged'] is not True
        or new['source_selection_publisher_privileged'] is not True
        or new['answers_postprocessed'] is not False
        or new['trained_parameters'] != 0 or old['weight_updates'] != 0
        or not read_json(b['host.json'])['host_eligible']):
        raise ValueError('different reader, source privileges, or CPU gate')
    if set(before) != set(after):
        raise ValueError('different actual question census')
    for qid in before:
        left, right = before[qid], after[qid]
        if (left['mode'] != right['mode']
            or left['selected'] != right['selected']
            or left['source_census_sha256'] != right['source_census_sha256']
            or left['family_proxy_digest'] != right['family_proxy_digest']
            or left['receipt']['delivered_evidence'] != right['receipt']['delivered_evidence']):
            raise ValueError('changed original evidence or source family')
    old_metrics, new_metrics = metrics(before), metrics(after)
    if old_metrics['undelivered_citation_labels'] or new_metrics['undelivered_citation_labels']:
        raise ValueError('undelivered E-label in original output')
    return {
        'schema':'hepta.memory-cell.locomo-format-original-answer-audit.v1',
        'historical_commit':OLD_COMMIT, 'new_generating_commit':NEW_COMMIT,
        'historical_reader_artifact_id':11792880133, 'historical_reader_zip_sha256':OLD_SHA,
        'new_reader_artifact_id':11801623797, 'new_reader_zip_sha256':NEW_SHA,
        'new_reader_run_id':38370785532,'new_reader_run_attempt':2,
        'original_member_hashes_verified_per_artifact':11,
        'model_identity':old['reader_identity'],
        'paired_original_question_count':len(before),
        'paired_original_delivered_evidence_identical':True,
        'answer_text_changed':sum(before[q]['answer'] != after[q]['answer'] for q in before),
        'historical_unmodified_answers':old_metrics,
        'new_unmodified_answers':new_metrics,
        'exact_refusal_improved':new_metrics['exact_refusal'] > old_metrics['exact_refusal'],
        'mixed_refusal_reduced':new_metrics['refusal_mixed_with_other_text'] < old_metrics['refusal_mixed_with_other_text'],
        'original_gold_answers_read':False,'new_model_calls_in_this_audit':0,
        'independent_semantic_judge':False,'source_selection_publisher_privileged':True,
        'parametric_memory_gain_established':False,'production_accepted':False,
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('historical',type=Path)
    parser.add_argument('new',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=audit(args.historical,args.new)
    with args.output.open('x',encoding='utf-8') as f:
        json.dump(result,f,indent=2,sort_keys=True,allow_nan=False)
        f.write('\n')
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':
    main()
