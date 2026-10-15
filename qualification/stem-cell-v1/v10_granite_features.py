"""Pinned Granite97 actual-token acquisition and bounded, label-blind feature reuse.

The original group_encoder.FrozenTokenEncoder and token_features.TokenBank are
reused as owners.  This file neither generates model weights nor supplies answer
labels to the Encoder.  There is no fallback to hash embeddings in real mode.
"""
from hashlib import sha256
import argparse
import json
from pathlib import Path
import time

from v9_source_panels import dataset_design
from v9_typed_graph import digest

REVISION = '835ad14087e140460703cf0fae09f97d469d65c2'
MODEL = 'ibm-granite/granite-embedding-97m-multilingual-r2'


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf8') as file:
        json.dump(value, file, sort_keys=True, indent=2, allow_nan=False)
        file.write('\n')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def validate_public(public):
    if (type(public) is not list or len(public) != 1248
            or any(type(c) is not dict or set(c) != {
                'case_id', 'source_group', 'facts', 'question', 'candidate'} for c in public)
            or len({c['case_id'] for c in public}) != 1248):
        raise ValueError('complete V9 registered public-only corpus required')
    return public


def source_owner(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    _, public, labels = dataset_design()
    validate_public(public)
    train = {k: v for k, v in labels.items() if k.startswith('train/')}
    held = {k: v for k, v in labels.items() if k.startswith(('held_known/', 'held_novel/'))}
    if (len(train), len(held)) != (288, 960):
        raise ValueError('registered train/held source partition changed')
    # Separate artifacts: model worker reads public+train labels, NEVER held truth.
    save_new(output/'public.json', public)
    save_new(output/'train-labels.json', train)
    save_new(output/'held-labels-restricted.json', held)
    record = dict(schema='hepta.v10.real-granite-source.v1', role='source_owner',
        public_sha256=digest(public), train_label_sha256=digest(train),
        held_label_sha256=digest(held), train_rows=len(train), held_rows=len(held),
        source_groups=312, revision=REVISION, model_id=MODEL,
        label_owner_is_external_independent=False, source_is_synthetic=True,
        natural_language_generalization=False, future_time_holdout=False,
        authority='DENY_ALL', production_accepted=False)
    save_new(output/'source-seal.json', record)
    return record


def to_public_reader_case(row):
    """Actual V9 public text → original ReaderCase with a DUMMY label, never truth."""
    from multirc_data import ReaderCase
    case_id = row['case_id'].split('/')
    if (len(case_id) != 5 or case_id[0] not in ('train','held_known','held_novel')
            or case_id[3] not in ('world-0','world-1')
            or case_id[4] not in ('candidate-0','candidate-1')):
        raise ValueError('registered role / world / alternative required')
    facts = tuple(row['facts'])
    source_hash = sha256('\n'.join(facts).encode()).hexdigest()
    case = ReaderCase('/'.join(case_id[:4]), '0', case_id[4], row['question'],
        row['candidate'], facts, 0, 'train' if case_id[0] == 'train' else 'validation',
        source_hash)
    return case


def encode(public_path, model_snapshot, output):
    """DOES actual frozen model forward; no synthetic fallback is available."""
    import torch
    from group_encoder import FrozenTokenEncoder
    from token_features import TokenBank
    public = validate_public(load(public_path))
    output = Path(output)
    if output.exists():
        raise FileExistsError('create-only model-derived feature output required')
    started_cpu, started_wall = time.process_time_ns(), time.perf_counter_ns()
    encoder = FrozenTokenEncoder(Path(model_snapshot), max_tokens=64)
    if encoder.material.get('revision') != REVISION or encoder.material.get('model_id') != MODEL:
        raise ValueError('source-pinned immutable pretrained Granite material required')
    bank = TokenBank(encoder, batch_size=8, chunk_tokens=64,
                     max_fact_chunks=64, scope='v10-granite-real', generation=0)
    transformed = [to_public_reader_case(row) for row in public]
    # WARNING: the only label provided to this encoder is a literal public DUMMY 0.
    if any(c.label != 0 for c in transformed):
        raise RuntimeError('encoder must not receive real hidden labels')
    bank.register(transformed)
    bank.save_local(output)
    report = bank.report()
    record = dict(schema='hepta.v10.real-granite-encoding.v1',
        public_sha256=digest(public), model_revision=REVISION,
        model_id=MODEL, token_count=report['content_tokens'],
        distinct_public_texts=report['distinct_public_texts'],
        actually_executed_encoder_batches=report['forward_batches'],
        actually_executed_encoded_sequences=report['encoded_sequences'],
        bank_file_sha256=sha256((output/'tokens.pt').read_bytes()).hexdigest(),
        bank_metadata_sha256=sha256((output/'metadata.json').read_bytes()).hexdigest(),
        encoder_source_lock_sha256=digest(encoder.material),
        reported_encoder_cpu_ns=report['cpu_ns'],
        full_encode_cpu_ns=time.process_time_ns()-started_cpu,
        full_encode_wall_ns=time.perf_counter_ns()-started_wall,
        real_pretrained_forward_executed=report['forward_batches'] > 0,
        frozen_weight_verified=bool(report['exact_tensor_verification']),
        held_labels_accessed=False, all_public_roles_encoded=True,
        source_is_synthetic=True, model_selection_permitted=False,
        authority='DENY_ALL', production_accepted=False)
    if not record['real_pretrained_forward_executed'] or not record['frozen_weight_verified']:
        raise ValueError('no verified real frozen inference evidence')
    save_new(output/'real-encoder-receipt.json', record)
    return record


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest='action', required=True)
    s = sub.add_parser('source'); s.add_argument('--output', type=Path, required=True)
    e = sub.add_parser('encode'); e.add_argument('--public', type=Path, required=True)
    e.add_argument('--snapshot', type=Path, required=True)
    e.add_argument('--output', type=Path, required=True)
    args=cli.parse_args()
    result=source_owner(args.output) if args.action=='source' else encode(args.public,args.snapshot,args.output)
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__': main()
