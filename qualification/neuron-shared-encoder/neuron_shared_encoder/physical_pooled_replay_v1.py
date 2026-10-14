"""Re-train small pooled Heads on prior *physical* pretrained feature artifacts.

The physical source is an exact, already-observed public research ZIP. This is
NOT a new pretrained Encoder forward, Token Query trial, causal future NDU, or
production authorized model. A synthetic ZIP is accepted ONLY in smoke mode.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
import time
from zipfile import ZipFile, BadZipFile

import torch
from torch.nn import functional as F
from safetensors.torch import load as safe_load

from .token_reader_v1 import CellHead
from .trained_head_artifacts_v1 import (seal_head_v1, load_pinned_trained_bank_v1,
                                         _canonical)

# Observed source: 2026-10-14 GitHub Actions 38534349397, successful
# public-pretrained-smoke job. Its hashes are self-consistency evidence, NOT
# independent model/source attestation or data-use authorization.
PUBLIC_ZIP_SHA256 = '1f1a463eebd130288445f5b7bf39377c0775c7cfc00a9cca4da87637a19eeff2'
MODEL = {
    'mmbert': ('hepta-public-study', 'jhu-clsp/mmBERT-small',
               'abc32620dd4f6ab06f5fbe905dc25f310618e09f', 384, 16),
    'modernbert': ('hepta-modernbert-pair', 'answerdotai/ModernBERT-base',
                   'fa3113d09d6dacfe5528708803dd92a62240237a', 768, 8),
}
MAX_ZIP_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 512 * 1024


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _member(archive: ZipFile, name: str, limit: int = MAX_MEMBER_BYTES) -> bytes:
    info = archive.getinfo(name)
    if info.is_dir() or not 0 < info.file_size <= limit:
        raise ValueError('invalid bounded archive member')
    with archive.open(info) as stream:
        raw = stream.read(limit + 1)
    if len(raw) != info.file_size:
        raise ValueError('archive member length drift')
    return raw


def _parsed(raw: bytes) -> dict:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate JSON key refused')
            value[key] = item
        return value
    data = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(data, dict):
        raise ValueError('mapping source manifest required')
    return data


def read_public_physical_features(archive_path: Path, zip_sha256: str, *,
                                  arm: str, allow_synthetic: bool = False):
    """Only pinned complete archive + source manifests may introduce features."""
    if arm not in MODEL or not isinstance(zip_sha256, str) or len(zip_sha256) != 64:
        raise ValueError('registered physical arm and exact ZIP pin required')
    path = Path(archive_path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_ZIP_BYTES:
        raise ValueError('bounded regular ZIP required')
    with path.open('rb') as source:
        if _sha(source.read()) != zip_sha256:
            raise ValueError('historical public artifact ZIP SHA256 mismatch')
    physical = zip_sha256 == PUBLIC_ZIP_SHA256
    if not physical and not allow_synthetic:
        raise ValueError('real public feature mode requires exactly observed physical ZIP')
    prefix, model_id, revision, width, rank = MODEL[arm]
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) > 2048 or len(names) != len(set(names)):
            raise ValueError('oversized or duplicate archive members')
        manifest_raw = _member(archive, f'{prefix}/manifest.json', 65536)
        manifest = _parsed(manifest_raw)
        source_model = manifest.get('model', {})
        if source_model.get('model_id') != model_id or source_model.get('revision') != revision:
            raise ValueError('frozen real Encoder model revision mismatch')
        dataset = _member(archive, f'{prefix}/dataset.jsonl', 256 * 1024)
        if manifest.get('dataset', {}).get('sha256') != _sha(dataset):
            raise ValueError('frozen public dataset content mismatch')
        rows = [_parsed(row) for row in dataset.splitlines()]
        feature_manifest_raw = _member(archive, f'{prefix}/execution/frozen-features/manifest.json', 65536)
        fm = _parsed(feature_manifest_raw)
        report = _parsed(_member(archive, f'{prefix}/execution/report.json', 65536))
        fr = report.get('frozen_features', {})
        if (fr.get('manifest_sha256') != _sha(feature_manifest_raw)
                or fr.get('shape') != [128, width]
                or (fr.get('simulated_encoder') is not (not physical))
                or fm.get('schema') != 'hepta.offline-frozen-features.v1'
                or fm.get('binding', {}).get('dataset_sha256') != _sha(dataset)
                or fm.get('binding', {}).get('manifest_sha256') != _sha(manifest_raw)
                or fm.get('shape') != [128, width] or fm.get('contains_labels') is not False
                or (fm.get('simulated_encoder') is not (not physical))):
            raise ValueError('unbound or synthetic feature provenance')
        raw = _member(archive, f'{prefix}/execution/frozen-features/features.safetensors',
                      512 * 1024)
        if fm.get('file_sha256') != _sha(raw) or fm.get('file_bytes') != len(raw):
            raise ValueError('physical pretrained tensor bytes mismatch')
        features = safe_load(raw)
        if set(features) != {'features'}:
            raise ValueError('unexpected physical feature tensors')
        tensor = features['features']
        if (tensor.dtype != torch.float32 or tensor.shape != (128, width)
                or not bool(torch.isfinite(tensor).all())):
            raise ValueError('malformed original pretrained feature tensor')
        # Verify original producer's independent canonical tensor witness.
        descriptor = _canonical(['torch.float32', [128, width]])
        tensor_digest = _sha(descriptor + bytes(tensor.contiguous().untyped_storage()))
        if fm.get('tensor_sha256') != tensor_digest:
            raise ValueError('physical feature numeric tensor witness mismatch')
        listed = fm.get('rows')
        if not isinstance(listed, list) or len(listed) != 128 or len(rows) != 128:
            raise ValueError('complete source row roster required')
        seen = set()
        for row, bound in zip(rows, listed):
            if (row.get('case_id') in seen or row.get('split') not in ('train','calibration','holdout')
                    or row.get('cell') not in (0,1) or not isinstance(row.get('label'), int)
                    or not 0 <= row['label'] < 4 or row.get('observed_at') is not None
                    or bound.get('case_id') != row.get('case_id')
                    or bound.get('scope') != row.get('scope')
                    or bound.get('split') != row.get('split')
                    or bound.get('cell') != row.get('cell')
                    or bound.get('group') != row.get('group')
                    or bound.get('input_sha256') != _sha(_canonical([row['scope'],row['text']]))):
                raise ValueError('complete bound retrospective source row required')
            seen.add(row['case_id'])
        if {split: sum(row['split'] == split for row in rows)
                for split in ('train','calibration','holdout')} != {
                   'train':64, 'calibration':32, 'holdout':32}:
            raise ValueError('original public cohort partition drift')
    return tensor.clone(), rows, {'physical_source_verified_locally': physical,
        'feature_manifest_sha256':_sha(feature_manifest_raw),
        'model_manifest_sha256':_sha(manifest_raw),
        'dataset_sha256':_sha(dataset), 'archive_sha256':zip_sha256,
        'model_id':model_id, 'model_revision':revision, 'rank':rank,
        'width':width, 'arm':arm}


def run_pooled_trained_readback(archive_path: Path, zip_sha256: str, output: Path,
                                *, arm: str, steps: int = 20,
                                seeds: tuple[int, ...] = (11,23,47),
                                allow_synthetic: bool = False) -> dict:
    """Train on original 64 train rows; observe *retrospective* holdout later."""
    if not 1 <= steps <= 128 or not isinstance(seeds, tuple) or not 1 <= len(seeds) <= 3 \
            or len(set(seeds)) != len(seeds) or any(type(s) is not int or not 0 <= s < 2**31 for s in seeds):
        raise ValueError('bounded fixed training schedule required')
    tensor, rows, identity = read_public_physical_features(
        archive_path, zip_sha256, arm=arm, allow_synthetic=allow_synthetic)
    root=Path(output)
    if root.exists() or root.is_symlink():
        raise ValueError('results must use fresh create-only directory')
    root.mkdir(mode=0o700, parents=False)
    pins={'encoder_sha256':identity['feature_manifest_sha256'],
          'tokenizer_sha256':_sha(identity['model_revision'].encode()),
          'preprocessor_sha256':_sha(b'hepta.shared-stem.public-pooled.v1'),
          'normalizer_sha256':_sha(b'preencoded-single-token-no-extra-normalization'),
          'dataset_sha256':identity['dataset_sha256'],
          'generation':1,'authority_epoch':1}  # research simulation, NOT production generations
    results=[]
    full_features = tensor.unsqueeze(1)
    mask = torch.ones((len(rows),1),dtype=torch.bool)
    for seed in seeds:
        artifacts=[]; observed=[]
        for cell in (0,1):
            train = [i for i,row in enumerate(rows) if row['split']=='train' and row['cell']==cell]
            calibration = [i for i,row in enumerate(rows) if row['split']=='calibration' and row['cell']==cell]
            holdout = [i for i,row in enumerate(rows) if row['split']=='holdout' and row['cell']==cell]
            if len(train)!=32 or len(calibration)!=16 or len(holdout)!=16:
                raise ValueError('original per-Cell training/evaluation roster incomplete')
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(seed)
                head=CellHead(identity['width'],identity['rank'],4)
            if sum(p.numel() for p in head.parameters()) > 16384:
                raise ValueError('per Cell actual parameter budget exceeded')
            generator=torch.Generator(device='cpu').manual_seed(seed+9127+cell)
            draws=[torch.tensor(train)[torch.randint(len(train),(16,),generator=generator)]
                   for _ in range(steps)]
            training_sha = _sha(_canonical({'cell':cell,'seed':seed,'sample_ids':[d.tolist() for d in draws]}))
            initialized=CellHead(identity['width'],identity['rank'],4)
            initialized.load_state_dict({k:v.detach().clone() for k,v in head.state_dict().items()})
            initialized.eval()
            optim=torch.optim.AdamW(head.parameters(),lr=1e-3,weight_decay=0.01)
            started=time.perf_counter_ns()
            for ids in draws:
                logits=head(full_features[ids],mask[ids],'pooled_feature_gate')
                labels=torch.tensor([rows[int(i)]['label'] for i in ids],dtype=torch.long)
                loss=F.cross_entropy(logits,labels)
                optim.zero_grad(set_to_none=True)
                loss.backward()
                optim.step()
            train_elapsed=time.perf_counter_ns()-started
            head.eval()
            scope={'principal':'public-ag-news-research','purpose':'physical-pooled-retrospective',
                   'organ_id':'ag-news','cell_id':f'cell-{cell}'}
            training_snapshot_sha256=_sha(_canonical([identity['feature_manifest_sha256'],
                                     identity['dataset_sha256'],cell,seed,training_sha]))
            artifact=seal_head_v1(root/f'seed-{seed}-cell-{cell}',head,
                        kind='pooled_cached',scope=scope,pins=pins,
                        training_snapshot_sha256=training_snapshot_sha256,
                        training={'seed':seed,'steps':steps,'batch':16,
                                  'sample_sha256':training_sha,'learning_rate':0.001,
                                  'optimizer':'AdamW','weight_decay':0.01,
                                  'torch_version':str(torch.__version__)})
            artifacts.append(artifact)
            observed_control=initialized
            observed.append({'cell':cell,'parameters':sum(p.numel() for p in head.parameters()),
                             'training_wall_ns':train_elapsed,
                             'trained_steps':steps,'train_count':len(train),
                             'calibration_count':len(calibration), 'holdout_count':len(holdout),
                             '_initialization_head': observed_control})
        bank=load_pinned_trained_bank_v1(artifacts,
                expected_principal='public-ag-news-research',
                expected_purpose='physical-pooled-retrospective',
                expected_organ='ag-news',expected_pins=pins,kind='pooled_cached')
        # Seal both trained artifacts BEFORE consulting any held-out labels.
        with torch.inference_mode():
            for obs,cell in zip(observed,(0,1)):
                for split in ('calibration','holdout'):
                    ids=[i for i,row in enumerate(rows) if row['split']==split and row['cell']==cell]
                    model=bank._heads[cell][1]
                    logits=model(full_features[ids],mask[ids],'pooled_feature_gate')
                    labels=torch.tensor([rows[i]['label'] for i in ids],dtype=torch.long)
                    init_logits=obs['_initialization_head'](full_features[ids],mask[ids],
                                                              'pooled_feature_gate')
                    orig=init_logits.argmax(1)==labels
                    trained=logits.argmax(1)==labels
                    obs[split]={'accuracy':float(trained.float().mean()),
                                'brier':float((logits.softmax(1)-F.one_hot(labels,4)).square().sum(1).mean()),
                                'random_initialization_control_accuracy':float(orig.float().mean()),
                                'newly_correct_cases':int((~orig & trained).sum()),
                                'newly_incorrect_cases':int((orig & ~trained).sum())}
                del obs['_initialization_head']
        witness=bank.verify_parity(full_features[0],mask[0])
        maximum_holdout_delta=0.0
        # Check every real held-out sample after immutable trained-model readback.
        with torch.inference_mode():
            for idx,row in enumerate(rows):
                if row['split'] != 'holdout':
                    continue
                choice=row['cell']
                expected=bank._heads[choice][1](full_features[idx:idx+1],
                                  mask[idx:idx+1],'pooled_feature_gate')[0]
                packed=bank._bank.execute(full_features[idx],mask[idx],
                                          kind='pooled_cached')[choice]
                maximum_holdout_delta=max(maximum_holdout_delta,
                                          float((expected-packed).abs().amax()))
        if maximum_holdout_delta > 1e-5 or not math.isfinite(maximum_holdout_delta):
            raise ValueError('physical held-out Head packed readback parity mismatch')
        results.append({'seed':seed,'cells':observed,
                        'trained_head_manifest_sha256s':[a.manifest_sha256 for a in artifacts],
                        'packed_scalar_max_difference':witness['maximum_prediction_difference'],
                        'all_32_retrospective_holdout_packed_parity_verified':True,
                        'heldout_maximum_packed_difference':maximum_holdout_delta,
                        'packed_bank_sha256':witness['bank_sha256'],
                        'production_admission':'BLOCKED'})
    report={'schema':'hepta.public-physical-pooled-head-replay.shadow.v1',
            'source':identity,'seeds':list(seeds),'results':results,
            'input_representation':'real-pretrained-pooled-vector-as-one-token',
            'token_query_efficacy_tested':False,'original_laya_control_tested':False,
            'genuine_prospective_future_window':False,
            'retrospective_holdout_only':True,'production_no_change_baseline_verified':False,
            'control_kind':'random_initialization_not_deployed_no_change',
            'independent_pretrained_issuer_signature_verified':False,
            'licensed_source_use_independently_verified':False,
            'NDU_evaluated':False,'selection_authorized':False,'production_admission':'BLOCKED'}
    with (root/'report.json').open('xb') as stream:
        stream.write(_canonical(report))
        stream.flush()
    return report
