"""Paired token-level Cell Head training on pinned *retrospective* AG News data.

No model download, no time-fabricated future window, no external effects,
final-use grants, selection, NDU or production. A self-hash is not a signature.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Callable
from zipfile import ZipFile

import torch
from torch import Tensor
from torch.nn import functional as F

from .physical_pooled_replay_v1 import MODEL, read_public_physical_features
from .token_reader_offline import INPUT_ENCODING, NORMALIZATION, _joint_text, _tokenize_and_capture
from .token_reader_cost_v1 import cached_pooled_logits, prepared_token_query_logits
from .token_reader_v1 import CellHead, snapshot_sha256
from .trained_head_artifacts_v1 import (
    PinnedHeadArtifactV1, _canonical, load_pinned_trained_bank_v1, seal_head_v1,
)

SCHEMA = 'hepta.neuron.real-token-paired-retrospective.v1'
PURPOSE = 'ag-news-retrospective-token-pair'
CATEGORIES = ('World', 'Sports', 'Business', 'Science and Technology')
QUESTION = 'Which AG News category best describes this article?'
SPLITS = ('train', 'calibration', 'holdout')
HEAD_KINDS = ('pooled_cached', 'token_query_prepared')


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _public_rows(source: list[dict]) -> dict[int, list[dict]]:
    """Do not convert retrospective holdout into a made-up future or OOD split."""
    if not isinstance(source, list) or len(source) != 128:
        raise ValueError('complete physical retrospective cohort required')
    by_cell = {0: [], 1: []}
    unique_cases: set[str] = set()
    unique_sources: set[str] = set()
    for row in source:
        if (not isinstance(row, dict) or set(row) != {
                'case_id', 'cell', 'group', 'label', 'observed_at', 'scope', 'split', 'text'}
                or row['cell'] not in by_cell or type(row['cell']) is not int
                or row['split'] not in SPLITS or row['scope'] != 'public-ag-news-research'
                or row['observed_at'] is not None or type(row['label']) is not int
                or not 0 <= row['label'] < 4 or type(row['text']) is not str
                or not 1 <= len(row['text']) <= 8192
                or not isinstance(row['case_id'], str) or not isinstance(row['group'], str)
                or row['case_id'] in unique_cases or row['group'] in unique_sources):
            raise ValueError('noncanonical public source, scope, duplicate or fake timestamps')
        unique_cases.add(row['case_id'])
        unique_sources.add(row['group'])
        enriched = {**row, 'question': QUESTION, 'options': list(CATEGORIES), 'state': row['text']}
        text, input_sha = _joint_text(enriched)
        enriched['joint_text'] = text
        enriched['input_sha256'] = input_sha
        by_cell[row['cell']].append(enriched)
    for cell, records in by_cell.items():
        if ({s: sum(x['split'] == s for x in records) for s in SPLITS}
                != {'train': 32, 'calibration': 16, 'holdout': 16}
                or {r['label'] for r in records if r['split'] == 'train'} != set(range(4))):
            raise ValueError(f'incomplete training/calibration/holdout of Cell {cell}')
    return by_cell


def _feature_identity(tokens: Tensor, mask: Tensor, records: list[dict], pins: dict) -> str:
    # Hide labels of unobserved calibration/holdout from the training snapshot.
    # Input digest binds full question + ordered options + state, not the answer.
    metadata = [dict(case_id=r['case_id'], group=r['group'], scope=r['scope'],
                     cell=r['cell'], split=r['split'], input_sha256=r['input_sha256'])
                for r in records]
    return snapshot_sha256(tokens, mask, metadata, pins)


def _normalize_cell(tokens: Tensor, mask: Tensor, records: list[dict]) -> Tensor:
    train = torch.tensor([i for i, r in enumerate(records) if r['split'] == 'train'], dtype=torch.long)
    values = tokens[train][mask[train]]
    mean = values.mean(0)
    sigma = values.std(0, unbiased=False).clamp_min(1e-4)
    return ((tokens - mean) / sigma).clamp(-8, 8).masked_fill(~mask.unsqueeze(-1), 0).contiguous()


def _metrics(logits: Tensor, labels: Tensor) -> dict:
    prob = logits.softmax(-1)
    onehot = F.one_hot(labels, num_classes=4).float()
    return {'accuracy': float((logits.argmax(-1) == labels).float().mean()),
            'brier': float((prob - onehot).square().sum(-1).mean()),
            'nll': float(F.cross_entropy(logits, labels))}


def _save_report_once(path: Path, report: dict) -> None:
    raw = _canonical(report)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_CLOEXEC', 0), 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def fit_sealed_token_pair_v1(*, features: dict[int, tuple[Tensor, Tensor]],
                              by_cell: dict[int, list[dict]], output: Path,
                              pins: dict, real_model_called: bool,
                              source_zip_sha256: str, model_id: str, model_revision: str,
                              encoder_observation: dict, rank: int = 8,
                              steps: int = 20, batch: int = 16,
                              seeds: tuple[int, ...] = (11, 23, 47)) -> dict:
    """Offline trainer with frozen same-input observations. No model invocation here.

    Both arms have exactly matching initial tensors and training samples.
    Neither validation nor holdout labels are read before all artifacts seal.
    """
    if (not 1 <= rank <= 32 or not 1 <= steps <= 128 or not 1 <= batch <= 32
            or not isinstance(seeds, tuple) or not 1 <= len(seeds) <= 3
            or len(set(seeds)) != len(seeds)
            or any(type(seed) is not int or not 0 <= seed < 2**31 for seed in seeds)
            or set(features) != {0, 1} or set(by_cell) != {0, 1}):
        raise ValueError('complete bounded two-Cell paired experiment required')
    if not isinstance(pins, dict) or set(pins) != {
            'encoder_sha256', 'tokenizer_sha256', 'preprocessor_sha256',
            'normalizer_sha256', 'dataset_sha256', 'generation', 'authority_epoch'}:
        raise ValueError('complete frozen model/input pins required')
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('fresh create-only research output directory required')
    prepared = {}
    for cell in (0, 1):
        tokens, mask = features[cell]
        records = by_cell[cell]
        if (not isinstance(tokens, Tensor) or tokens.dtype != torch.float32
                or tokens.device.type != 'cpu' or tokens.ndim != 3 or tokens.requires_grad
                or not isinstance(mask, Tensor) or mask.dtype != torch.bool
                or mask.device.type != 'cpu' or mask.shape != tokens.shape[:2]
                or tokens.shape[0] != len(records) or not mask.any(1).all()
                or not torch.isfinite(tokens).all() or not tokens.is_contiguous()
                or not mask.is_contiguous()):
            raise ValueError('real CPU token feature/mask geometry, finiteness or bounds violated')
        width = tokens.shape[2]
        if not 1 <= width <= 768 or not 1 <= tokens.shape[1] <= 256 or tokens.numel() > 8_388_608:
            raise ValueError('bounded token feature dimensions required')
        if len(records) != 64 or {r['split'] for r in records} != set(SPLITS):
            raise ValueError('complete retrospective Cell partition required')
        if len(set(r['input_sha256'] for r in records)) != len(records):
            raise ValueError('duplicate or incomplete question/options/state input binding')
        snapshot = _feature_identity(tokens, mask, records, pins)
        prepared[cell] = (tokens, mask, _normalize_cell(tokens, mask, records), snapshot)
    output.mkdir(mode=0o700, parents=False)
    runs=[]
    for seed in seeds:
        refs: dict[str, list[PinnedHeadArtifactV1]] = {k: [] for k in HEAD_KINDS}
        candidates={}
        for cell in (0,1):
            tokens, mask, normalized, snapshot = prepared[cell]
            prepared_masked = normalized.masked_fill(~mask.unsqueeze(-1), 0)
            pooled_cache = prepared_masked.sum(1) / mask.sum(1, keepdim=True)
            records = by_cell[cell]
            train_ids = torch.tensor([i for i,r in enumerate(records) if r['split']=='train'], dtype=torch.long)
            train_labels = torch.tensor([r['label'] for r in records if r['split']=='train'],dtype=torch.long)
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(seed + cell * 104729)
                reference = CellHead(tokens.shape[-1], rank, 4)
            params = sum(p.numel() for p in reference.parameters())
            if params > 16384:
                raise ValueError('actual per-Cell Head budget exceeded')
            init={k:v.detach().clone() for k,v in reference.state_dict().items()}
            gen=torch.Generator(device='cpu').manual_seed(seed + cell * 997 + 9127)
            batches=[torch.randint(len(train_ids),(min(batch,len(train_ids)),),generator=gen)
                     for _ in range(steps)]
            samples_sha=_sha(_canonical([b.tolist() for b in batches]))
            train_labels_sha=_sha(_canonical(train_labels.tolist()))
            # Freeze training identity without future labels or even held-out
            # statistics. Source archive identity remains an immutable reference.
            train_snapshot_sha=_sha(_canonical([snapshot,train_labels_sha,samples_sha]))
            for kind in HEAD_KINDS:
                head=CellHead(tokens.shape[-1],rank,4)
                head.load_state_dict(init, strict=True)
                head.train()
                optimizer=torch.optim.AdamW(head.parameters(),lr=0.001,weight_decay=0.01)
                start=time.perf_counter_ns()
                for indices in batches:
                    rows=train_ids[indices]
                    logits=(cached_pooled_logits(head, pooled_cache[rows])
                        if kind=='pooled_cached' else
                        prepared_token_query_logits(head, prepared_masked[rows],mask[rows]))
                    loss=F.cross_entropy(logits,train_labels[indices])
                    optimizer.zero_grad(set_to_none=True)
                    loss.backward()
                    optimizer.step()
                elapsed_ns=time.perf_counter_ns()-start
                head.eval()
                scope={'principal':'public-ag-news-research','purpose':PURPOSE,
                       'organ_id':'ag-news','cell_id':f'cell-{cell}'}
                artifact=seal_head_v1(output/f'seed-{seed}-cell-{cell}-{kind}',head,
                                      kind=kind,scope=scope,pins=pins,
                                      training_snapshot_sha256=train_snapshot_sha,
                                      training={'seed':seed + cell * 104729,'steps':steps,'batch':batch,
                                                'sample_sha256':samples_sha,
                                                'learning_rate':0.001,'optimizer':'AdamW',
                                                'weight_decay':0.01,'torch_version':str(torch.__version__)})
                refs[kind].append(artifact)
                candidates[cell,kind]={'parameter_count':params,'training_wall_ns':elapsed_ns,
                                       'head_manifest_sha256':artifact.manifest_sha256,
                                       'training_sample_sha256':samples_sha,
                                       'train_label_sha256':train_labels_sha}
            if _feature_identity(tokens,mask,records,pins)!=snapshot:
                raise ValueError('immutable token source modified during optimizer')
        banks={kind:load_pinned_trained_bank_v1(refs[kind],
                   expected_principal='public-ag-news-research',expected_purpose=PURPOSE,
                   expected_organ='ag-news',expected_pins=pins,kind=kind)
               for kind in HEAD_KINDS}
        # No evaluation labels were consulted until the two arms of BOTH Cells
        # finished training, saved weights, and passed exact-readback loading.
        observations=[]
        max_parity=0.0
        for cell in (0,1):
            tokens,mask,normalized,_=prepared[cell]
            records=by_cell[cell]
            for split in ('calibration','holdout'):
                ids=[i for i,r in enumerate(records) if r['split']==split]
                y=torch.tensor([records[i]['label'] for i in ids],dtype=torch.long)
                run={'cell':cell,'split':split,'unique_cases':len(ids)}
                with torch.inference_mode():
                    for kind in HEAD_KINDS:
                        state=banks[kind]._heads[cell][1]
                        original=state(normalized[ids],mask[ids],
                                      'pooled_feature_gate' if kind=='pooled_cached' else 'token_query_gate')
                        pred=[]
                        for idx in ids:
                            packed=banks[kind]._bank.execute(normalized[idx],mask[idx],kind=kind)[cell]
                            delta=float((original[len(pred)]-packed).abs().max())
                            max_parity=max(delta,max_parity)
                            if delta>1e-5:
                                raise ValueError('saved trained Head packed-vs-scalar parity failed')
                            pred.append(packed)
                        logits=torch.stack(pred)
                        run[kind]=_metrics(logits,y)
                        run[kind]['head_manifest_sha256']=candidates[cell,kind]['head_manifest_sha256']
                        run[kind]['newly_correct_v_pooled']=0
                    queried=run['token_query_prepared']
                    # Paired correctness counts use the SAME cases, not seeds
                    # treated as independent future task observations.
                    pooled_labels=torch.stack([
                        banks['pooled_cached']._bank.execute(normalized[i],mask[i],kind='pooled_cached')[cell]
                        for i in ids]).argmax(-1)
                    query_labels=torch.stack([
                        banks['token_query_prepared']._bank.execute(normalized[i],mask[i],kind='token_query_prepared')[cell]
                        for i in ids]).argmax(-1)
                    p_ok=pooled_labels.eq(y); q_ok=query_labels.eq(y)
                    queried['newly_correct_v_pooled']=int((~p_ok & q_ok).sum())
                    queried['newly_incorrect_v_pooled']=int((p_ok & ~q_ok).sum())
                observations.append(run)
        runs.append({'seed':seed,'candidate_heads':[
                     {'cell':cell,'kind':kind,**candidates[cell,kind]}
                     for cell in (0,1) for kind in HEAD_KINDS],
                     'observations':observations,
                     'all_32_holdout_rows_for_both_arms_verified':sum(
                         x['unique_cases'] for x in observations if x['split']=='holdout')==32,
                     'max_packed_delta':max_parity,
                     'same_optimizer_sample_stream_between_arms':True})
    for cell in (0,1):
        tokens,mask,_normal,snapshot=prepared[cell]
        if _feature_identity(tokens,mask,by_cell[cell],pins)!=snapshot:
            raise ValueError('post-experiment immutable token snapshot changed')
    report={'schema':SCHEMA,'source_zip_sha256':source_zip_sha256,
            'model_id':model_id,'model_revision':model_revision,
            'full_joint_question_options_state_bound':True,
            'evidence_class':('LOCALLY_PINNED_PRETRAINED_TOKEN_MATRIX'
                              if real_model_called else 'SYNTHETIC_INTERFACE_TEST_ONLY'),
            'real_model_encoder_forward_observed':real_model_called,
            'encoder_observation':encoder_observation,
            'head_train_steps_per_candidate':steps,'train_samples_per_Cell':32,
            'calibration_samples_per_Cell':16,'holdout_samples_per_Cell':16,
            'distinct_holdout_cases':32,'three_seeds_are_repeated_not_independent_cases':True,
            'head_params_exactly_equal_within_encoder':True,
            'pooled_cache_computed_once_per_Cell_input_during_training':True,
        'pooled_cache_reused_across_different_Cell_scopes_verified':False,
            'full_token_state_discarded_after_shadow':True,
            'retrospective_only_no_certified_observation_timestamps':True,
            'real_deployed_no_change_baseline_verified':False,
            'no_future_labels_used_to_choose_model':True,
            'no_independent_future_or_ood_window_verified':True,
            'negative_transfer_and_NDU_verified':False,
            'external_signatures_verified':False,
            'source_use_authorized':False,
            'q24_native_worker_verified':False,
            'selection_authorized':False,
            'production_admission':'BLOCKED',
            'runs':runs}
    _save_report_once(output/'report.json',report)
    return report


def run_pinned_historical_token_pair(*, archive_path: Path, archive_sha256: str,
                                     checkpoint_dir: Path, bundle_sha256: str,
                                     steps: int = 20, seeds: tuple[int,...]=(11,23,47),
                                     max_length: int = 128, encoder_batch: int = 8,
                                     output: Path, allow_synthetic: bool = False,
                                     synthetic_capture: Callable | None = None) -> dict:
    """Fail closed if original publisher source or local real model is missing.

    `synthetic_capture` may be used ONLY against a non-physical synthetic
    archive when allow_synthetic=True. The CLI never accepts either bypass.
    """
    if not 8<=max_length<=256 or not 1<=encoder_batch<=32:
        raise ValueError('bounded real model input/profile required')
    if synthetic_capture is not None and not allow_synthetic:
        raise ValueError('synthetic model callbacks forbidden in physical study')
    _old_pooled,source,identity=read_public_physical_features(
        archive_path, archive_sha256, arm='modernbert',allow_synthetic=allow_synthetic)
    by_cell=_public_rows(source)
    real = bool(identity['physical_source_verified_locally'] and synthetic_capture is None)
    if not real and not allow_synthetic:
        raise ValueError('independent pretrained source execution required')
    with ZipFile(archive_path) as z:
        from .physical_pooled_replay_v1 import _member, _parsed
        manifest=_parsed(_member(z,'hepta-modernbert-pair/manifest.json',65536))
    model=manifest['model']
    if real:
        if (model.get('model_id')!=MODEL['modernbert'][1]
                or model.get('revision')!=MODEL['modernbert'][2]
                or model.get('conversion') is not None
                or not isinstance(model.get('files'),dict)):
            raise ValueError('unqualified original pretrained source revision/conversion')
        checkpoint_dir=Path(checkpoint_dir)
        if not checkpoint_dir.is_dir() or checkpoint_dir.is_symlink():
            raise ValueError('regular pinned pretrained checkpoint directory required')
        from .contracts import sha256_file
        from .models import OfflineEncoder
        from .bundle import verify_checkpoint_bundle
        expected=model['files']
        if any(not (checkpoint_dir/name).is_file() or (checkpoint_dir/name).is_symlink()
               or sha256_file(checkpoint_dir/name)!=digest for name,digest in expected.items()):
            raise ValueError('physical staged model file identity differs from original publisher')
        verify_checkpoint_bundle(checkpoint_dir,'modernbert-joint',bundle_sha256)
        backend=OfflineEncoder('modernbert-joint',str(checkpoint_dir),
                               expected['model.safetensors'],device='cpu',max_length=max_length,
                               expected_bundle_sha256=bundle_sha256)
    else:
        backend=None
    features={}; observed=[]
    for cell in (0,1):
        texts=[row['joint_text'] for row in by_cell[cell]]
        if real:
            tokens,mask,measurement=_tokenize_and_capture(backend,texts,
                                           max_length=max_length,batch=encoder_batch)
        else:
            if synthetic_capture is None:
                raise ValueError('synthetic archive requires explicitly passed test capture')
            tokens,mask,measurement=synthetic_capture(cell,texts,max_length)
        if tokens.shape[0]!=64 or mask.shape!=tokens.shape[:2]:
            raise ValueError('incomplete Cell token matrix')
        features[cell]=(tokens,mask)
        observed.append({'cell':cell,**measurement})
    if real:
        backend._check_bundle_unchanged()
        for name,digest in model['files'].items():
            if sha256_file(checkpoint_dir/name)!=digest:
                raise ValueError('staged model changed during real Encoder forward')
    pins={'encoder_sha256':bundle_sha256,
          'tokenizer_sha256':model.get('files',{}).get('tokenizer.json','0'*64),
          'preprocessor_sha256':_sha(INPUT_ENCODING),
          'normalizer_sha256':_sha(NORMALIZATION),
          'dataset_sha256':identity['dataset_sha256'],
          'generation':1,'authority_epoch':1}  # simulation namespace only
    report=fit_sealed_token_pair_v1(features=features,by_cell=by_cell,
         output=output,pins=pins,real_model_called=real,
         source_zip_sha256=archive_sha256,model_id=MODEL['modernbert'][1],
         model_revision=MODEL['modernbert'][2],
         encoder_observation={'cells':observed,
                              'capture_profile':{'max_length':max_length,
                                                 'batch':encoder_batch}},
         rank=8,steps=steps,seeds=seeds)
    return report


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-zip',type=Path,required=True)
    parser.add_argument('--source-sha256',required=True)
    parser.add_argument('--checkpoint-dir',type=Path,required=True)
    parser.add_argument('--bundle-sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-length',type=int,default=128)
    parser.add_argument('--encoder-batch',type=int,default=8)
    parser.add_argument('--steps',type=int,default=20)
    parser.add_argument('--seeds',nargs='+',type=int,default=[11,23,47])
    args=parser.parse_args()
    run_pinned_historical_token_pair(archive_path=args.source_zip,
         archive_sha256=args.source_sha256,checkpoint_dir=args.checkpoint_dir,
         bundle_sha256=args.bundle_sha256,output=args.output,
         max_length=args.max_length,encoder_batch=args.encoder_batch,
         steps=args.steps,seeds=tuple(args.seeds))


if __name__=='__main__':
    main()
