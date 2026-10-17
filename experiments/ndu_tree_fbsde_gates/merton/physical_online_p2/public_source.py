"""Pin AG News publisher parquet and stage TRAIN vs HELD without label leakage.

Real public publisher data, historically visible: NOT a prospective source family.
Runs only in an isolated source-owner job. Source gold never enters model worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

REPO = 'szhuggingface/ag_news'
REV = '98c532231d96ae10e176a909192ecac548949288'
FILES = {
    'data/train_1_1.5k-00000-of-00001.parquet': 'cc35afe9d5e7ff01878c9aeba08bb0bdfa16947702789530b216a580a1bc09d5',
    'data/test-00000-of-00001.parquet': '2237e86474314bae6c611718e5bd16a42b4e8dfae53bb4a84abdae1bc1c5d3ee',
}
SCHEMA = 'hepta.ndu-merton.p5.class-balanced-agnews-source.v1'
LABELS = ('World', 'Sports', 'Business', 'Sci/Tech')


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def encoded(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def sync_dir(path: Path) -> None:
    # A synced file alone does not persist a newly created directory entry.
    # Original evidence requires the named Linux filesystem durability step.
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def new_json(path: Path, payload) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(encoded(payload) + b'\n')
        f.flush()
        os.fsync(f.fileno())
    sync_dir(path.parent)


def validate_rows(records, split: str):
    if type(records) is not list or len(records) < 20:
        raise ValueError('original dataset too small')
    out = []
    for i, raw in enumerate(records):
        if type(raw) is not dict or set(raw) != {'text', 'label'}:
            raise ValueError('incorrect publisher schema')
        text, label = raw['text'], raw['label']
        if type(text) is not str or not 16 <= len(text) <= 2500 or '\x00' in text:
            raise ValueError('original publisher text invalid')
        if type(label) is not int or label not in range(4):
            raise ValueError('original publisher label invalid')
        bucket = 'short' if len(text) <= 180 else 'long'
        group = f'{split}-row-parity-{i%2}'
        out.append({'task_id': f'{split}-{i:05}', 'text': text,
                    'bucket': bucket, 'group': group, 'label': label,
                    'text_sha256': sha(text.encode())})
    return out


def original_manifest():
    return {'repo': REPO, 'revision': REV, 'source_files_sha256': FILES,
            'split_rule': 'first-per-original-publisher-class-bucket-index-parity',
            'publisher_label_for_source_stratification_only': True,
            'bucket_rule': 'short_if_unicode_length_le_180',
            'publisher_future_window': False, 'independent_source_families': False}

def split_original(train, held):
    train = validate_rows(train, 'train')
    held = validate_rows(held, 'held')
    def pick(records):
        # Predeclared BEFORE obtaining model outputs: first original row for each
        # of the 4 publisher labels x 2 text lengths x 2 source row parities.
        # Held labels are used by the source owner solely for selection and are
        # stripped before publishing PUBLIC inputs to the Reader job.
        selected = {}
        for row in records:
            task_index = int(row['task_id'].rsplit('-', 1)[1])
            key = (row['label'], row['bucket'], task_index % 2)
            selected.setdefault(key, row)
            if len(selected) == 16:
                break
        expected = {(label, bucket, parity)
                    for label in range(4)
                    for bucket in ('short', 'long')
                    for parity in (0, 1)}
        if set(selected) != expected:
            raise ValueError('unavailable: original publisher lacks balanced label/bucket/parity support')
        return sorted(selected.values(), key=lambda row: row['task_id'])
    training = pick(train)
    eval_rows = pick(held)
    if len({row['text_sha256'] for row in training + eval_rows}) != 32:
        raise ValueError('source text duplicates across train/held')
    dataset = original_manifest()
    train_packet = {'schema': SCHEMA+'.train', 'source': dataset,
                    'rows': [{k:r[k] for k in ('task_id','text','bucket','group','label','text_sha256')} for r in training]}
    held_public = {'schema': SCHEMA+'.held-public', 'source': dataset,
                   'rows': [{k:r[k] for k in ('task_id','text','bucket','group','text_sha256')} for r in eval_rows]}
    held_truth = {'schema': SCHEMA+'.held-private-labels', 'source': dataset,
                  'rows': [{k:r[k] for k in ('task_id','label','text_sha256')} for r in eval_rows]}
    return train_packet, held_public, held_truth


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as pq
    records=[]
    for relative, expected in FILES.items():
        local=Path(hf_hub_download(repo_id=REPO, repo_type='dataset',
                                  revision=REV, filename=relative))
        if sha(local.read_bytes()) != expected:
            raise ValueError('original dataset byte digest mismatch: '+relative)
        table=pq.read_table(local,columns=['text','label'])
        records.append(table.to_pylist())
    packets=split_original(*records)
    for name,packet in zip(('train-public.json','held-public.json','held-private-labels.json'), packets):
        new_json(out/name,packet)
    new_json(out/'source-claim.json',{'schema':SCHEMA+'.stage-status',
                                    'public_train_cases':16,'public_held_cases':16,
                                    'original_model_forwards':0,
                                    'prospective_generalization':False,
                                    'authority':'DENY_ALL'})
    print(json.dumps({'source':REPO,'revision':REV,'output':str(out),
                      'train':16,'held':16,'labels_separated':True},sort_keys=True))

if __name__ == '__main__':
    main()
