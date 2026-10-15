"""E25: six previously UNUSED validation passages; frozen loss, no score-selection.

Original source is aps/super_glue MultiRC at the same pinned revision.  This
isolates passages from the old four but is NOT a new data family/time window.
The source-owner job holds public train truth and separate private eval truth.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

TRAIN_SHA = 'ced6d731a335a0e4fbd29f6f382f291518952c0f449448361d294000c39e6728'
VAL_SHA = '5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada'
ARCHIVE_SHA = '1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17'
ORIGINAL_SOURCE_HEAD = '6f8cf0930a51bce97fc22a09e3c5923a082abae9'
MODERNBERT_SNAPSHOT_SHA = '43138a5545ce4e7996d91735f2330519a8913304d3abf257f6cfdfbe0541283d'
SEED = 7347


def old_source_groups(archive: str) -> tuple[str, ...]:
    path = Path(archive)
    if sha256(path.read_bytes()).hexdigest() != ARCHIVE_SHA:
        raise ValueError('historical successful real pretrained ZIP changed')
    with ZipFile(path) as z:
        if len(z.namelist()) != len(set(z.namelist())):
            raise ValueError('duplicate original ZIP member')
        entry = 'multirc-native-candidate-audit/audit.json'
        data = z.read(entry)
        if len(data) > 200000: raise ValueError('oversized historic source')
        obj = json.loads(data)
    if obj.get('actual_candidate_count') != 33 or obj.get('question_count') != 8:
        raise ValueError('original previous source size changed')
    groups = tuple(dict.fromkeys(x['source_group'] for x in obj['rows']))
    if len(groups) != 4 or any(len(g) != 32 for g in groups):
        raise ValueError('expected original 4 passage source groups')
    return groups


def exclude_previous_source_passages(validation_rows: list[dict], original_groups: set[str]) -> list[dict]:
    """Remove complete old paragraphs by SOURCE ID, never by outcome/label.

    Source group hash matches original multirc_materials._digest JSON encoding.
    We do not import/consult label or a model prediction anywhere here.
    """
    if (type(validation_rows) is not list or not validation_rows
            or type(original_groups) is not set or len(original_groups) != 4
            or any(type(g) is not str or len(g) != 32 for g in original_groups)):
        raise ValueError('historical source group inventory required')
    from next_round_matrix import _digest
    seen = {}
    excluded = set()
    result = []
    for row in validation_rows:
        if type(row) is not dict or set(row) != {'paragraph','question','answer','label','idx'}:
            raise ValueError('complete original source row schema')
        idx = row['idx']
        if type(idx) is not dict or set(idx) != {'paragraph','question','answer'} or any(
            type(z) is not int or not 0 <= z <= 10**9 for z in idx.values()
        ):
            raise ValueError('bad original validation id')
        p = row['paragraph']
        if p is None:
            # The original selector excludes malformed records by complete
            # paragraph. Reject ambiguous ID/text cases downstream.
            result.append(row)
            continue
        if type(p) is not str:
            raise ValueError('invalid paragraph type')
        pid = idx['paragraph']
        if pid in seen and seen[pid] != p:
            raise ValueError('one source paragraph has conflicting text')
        seen[pid] = p
        group = sha256(f'validation:passage:{pid}:{_digest(p)}'.encode()).hexdigest()[:32]
        if group in original_groups:
            excluded.add(group)
        else:
            result.append(row)
    if excluded != original_groups:
        raise ValueError('previous four source identities not found in pinned source')
    return result


def exhaustive_unused_source_census(remaining_rows: list[dict]) -> tuple[set[str], dict]:
    """Verify *all* original eligible unused passages, not merely first six.

    This must run on the original label-owner's full SHA-pinned validation
    table AFTER exact historical four passages are excluded and BEFORE
    prepare_panels can select or encode any unused passage. The original
    complete-passage admission policy examines source structure, not scores.
    """
    from multirc_materials import _group_inputs
    from next_round_matrix import _digest
    eligible, stats = _group_inputs(remaining_rows, 'validation', return_stats=True)
    if (len(eligible) != 6 or stats['eligible_passages'] != 6 or
            stats['eligible_distinct_texts'] != 6):
        raise ValueError('exactly six previously unused eligible source passages required')
    groups = {sha256(f'validation:passage:{pid}:{_digest(text)}'.encode()).hexdigest()[:32]
              for pid, text, _ in eligible}
    if len(groups) != 6:
        raise ValueError('ambiguous or duplicated original eligible source identity')
    return groups, stats


def build(original_archive, train_rows, val_rows):
    """Calls original frozen source-selection and candidate-slate algorithms.

    Label metadata may exist in these raw source rows ONLY within material
    owner. Neither selection/pruning nor fitted Reader access may use held truth.
    """
    from multirc_materials import prepare_panels
    from multirc_candidate_slate import prepare_candidate_slate
    historical = set(old_source_groups(original_archive))
    train4,old_eval,old_labels = prepare_panels(
        train_rows,val_rows,dataset_sha256_train=TRAIN_SHA,dataset_sha256_val=VAL_SHA,
        seed=SEED,train_passages=8,val_passages=4)
    if set(row['source_group'] for row in old_eval['rows']) != historical:
        raise ValueError('previous source cannot be reconstructed from exact parquet')
    remaining = exclude_previous_source_passages(val_rows,historical)
    remaining_ids, remaining_admission = exhaustive_unused_source_census(remaining)
    train6,eval6,owner6 = prepare_panels(
        train_rows,remaining,dataset_sha256_train=TRAIN_SHA,dataset_sha256_val=VAL_SHA,
        seed=SEED,train_passages=8,val_passages=6)
    if train4['rows'] != train6['rows'] or set(row['source_group'] for row in eval6['rows']) & historical:
        raise ValueError('training source changed or original held group leaked')
    if (len(eval6['rows']) != 6 or
            {r['source_group'] for r in eval6['rows']} != remaining_ids):
        raise ValueError('actual selected six passages do not exhaust source-admitted identities')
    slate,labels = prepare_candidate_slate(train6,eval6,remaining,original_label_receipt=owner6)
    n = sum(len(q['candidates']) for p in slate['rows'] for q in p['questions'])
    if not 24 <= n <= 96 or len(labels['labels']) != n:
        raise ValueError('complete six-passage original answer source inventory missing')
    metadata = {
        'schema':'hepta.e25.unused-original-multirc-passages.v1','authority':'DENY_ALL',
        'original_source_head':ORIGINAL_SOURCE_HEAD,'original_archive_sha256':ARCHIVE_SHA,
        'train_parquet_sha256':TRAIN_SHA,'validation_parquet_sha256':VAL_SHA,
        'old_source_groups':sorted(historical),
        'new_source_groups':[r['source_group'] for r in eval6['rows']],
        'new_question_count':12,'new_candidate_count':n,
        'seed':SEED,'exhausts_remaining_eligible_passages':True,
        'selection_uses_labels_or_predictions':False,'same_original_data_family':True,
        'eligible_unused_passage_count_verified':6,
        'original_unused_validation_admission':remaining_admission,
        'eligible_unused_distinct_text_count_verified':6,
        'eligible_unused_group_set_sha256':sha256(
            json.dumps(sorted(remaining_ids),separators=(',',':')).encode()).hexdigest(),
        'full_unused_source_census_before_model':True,
        'source_issuer_independently_authenticated':False,
        'future_time_or_independent_family':False,'new_models_yet_executed':False,
        'production_accepted':False,
    }
    return {'train':train6,'blind_eval':eval6,'blind_slate':slate,'source':metadata}, labels


def write_once(path, value):
    data = (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    with Path(path).open('xb') as out:out.write(data)
    return sha256(data).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('original-archive','train-parquet','validation-parquet','public-output','owner-output'):
        ap.add_argument('--'+k,required=True)
    args=ap.parse_args()
    from multirc_materials import load_parquet
    train=load_parquet(args.train_parquet,expected_sha256=TRAIN_SHA)
    val=load_parquet(args.validation_parquet,expected_sha256=VAL_SHA)
    public,labels=build(args.original_archive,train,val)
    pub=Path(args.public_output);owner=Path(args.owner_output)
    pub.mkdir(parents=True,exist_ok=False);owner.mkdir(parents=True,exist_ok=False)
    for k,v in public.items():
        write_once(pub/f'{k}.json',v)
    write_once(owner/'human-labels.json',labels)
    print(json.dumps({'authority':'DENY_ALL','new_passages':6,
        'new_candidates':public['source']['new_candidate_count'],'owner_human_labels_not_in_public_artifact':True}))

if __name__=='__main__':main()
