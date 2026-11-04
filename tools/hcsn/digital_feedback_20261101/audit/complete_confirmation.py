"""Reconstruct the frozen confirmation without training, generation or selection.

Collection requires NumPy; final fit inference also requires SciPy. The record
checker uses unchanged AST function bodies from pinned audit/independent.py.
Only its unused statistical functions/imports are excluded during collection.
"""
import argparse, ast, base64, gzip, hashlib, importlib.util, io, json, math, tarfile, time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
import numpy as np
SOURCE = '903946f15dd79bc53a39a479230e366df04a371f'
ARMS = ('fpt_base_multi', 'fpt_neutral_drift', 'fpt_neutral_bank', 'fpt_neutral_both', 'fpt_pooled_sign', 'fpt_common_reset', 'fpt_pooled_common', 'fpt_base_single', 'fpt_base_off', 'ordinary_multi', 'ordinary_single', 'acc_free_off', 'acc_free_multi', 'acc_structured_off', 'acc_structured_multi', 'bayes')
PHASES = ('development_001', 'development_002', 'training_001', 'training_002', 'confirmation_001')
HELPERS = {'Review', 'legal', 'initial_state', 'advance', 'latent_contract', 'retained_label', 'decision_values', 'episode_values'}

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def read(path):
    path = Path(path)
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)

def save(path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

def raw_helpers(path):
    raw = path.read_bytes()
    assert digest(raw) == 'd30a2ebfe8743ccfefbd839d68e46e82a6682aa3b8bc3f61541c934eb559915e', 'raw checker source changed'
    tree = ast.parse(raw)
    kept = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in HELPERS:
            kept.append(n)
        elif isinstance(n, ast.Import) and all((x.name in {'copy', 'math', 'numpy'} for x in n.names)):
            kept.append(n)
        elif isinstance(n, ast.ImportFrom) and n.module == 'pathlib':
            kept.append(n)
    assert {n.name for n in kept if isinstance(n, (ast.FunctionDef, ast.ClassDef))} == HELPERS
    env = {'__name__': 'frozen_raw_helpers'}
    exec(compile(ast.Module(body=kept, type_ignores=[]), str(path), 'exec'), env)
    return (env, digest(raw))

def restore(cache, name):
    folder = cache / 'archives' / name
    manifest_raw = (folder / 'MANIFEST.json').read_bytes()
    m = json.loads(manifest_raw)
    chunks = []
    for p in m['parts']:
        encoded = (folder / p['path']).read_bytes()
        assert digest(encoded) == p['stored_sha256'], (name, p['path'], 'stored')
        data = base64.b64decode(encoded.strip(), validate=True)
        assert digest(data) == p['decoded_sha256'] and len(data) == p['decoded_bytes'], (name, p['path'], 'decoded')
        chunks.append(data)
    packed = b''.join(chunks)
    assert digest(packed) == m['archive_sha256'] and len(packed) == m['archive_bytes'], (name, 'archive')
    expected = {x['path']: x for x in m['files']}
    assert len(expected) == len(m['files'])
    dest = cache / 'restored' / name
    with tarfile.open(fileobj=io.BytesIO(packed), mode='r:gz') as archive:
        members = archive.getmembers()
        assert len(members) == len(expected) and {x.name for x in members} == set(expected)
        for item in members:
            path = PurePosixPath(item.name)
            assert item.isfile() and (not path.is_absolute()) and ('..' not in path.parts)
            raw = archive.extractfile(item).read()
            e = expected[item.name]
            assert digest(raw) == e['sha256'] and len(raw) == e['bytes'], (name, item.name)
            target = dest / item.name
            if not target.exists() or digest(target.read_bytes()) != e['sha256']:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
    return (dest, dict(name=name, manifest_sha256=digest(manifest_raw), archive_sha256=digest(packed), archive_bytes=len(packed), members=len(expected)))

def phase_cost(folder, phase, review):
    cp = folder / 'CONTROLLER_RECEIPT.json'
    c = read(cp) if cp.exists() else None
    receipts = [read(p) for p in sorted((folder / 'process_receipts').glob('*.json'))]
    ids = [r['fit'] for r in receipts]
    review.equal(phase + '/unique', len(ids), len(set(ids)))
    if c:
        review.equal(phase + '/inventory', sorted(ids), sorted(c['registered_fits']))
        review.equal(phase + '/active', c['active_pids'], [])
        review.equal(phase + '/pending', c['pending_fits'], [])
    child = sum((r['cpu_seconds'] for r in receipts))
    own = c['controller_self_cpu_seconds'] if c else None
    return dict(phase=phase, registered_workers=len(ids), workers_with_positive_cpu=sum((r['cpu_seconds'] > 0 for r in receipts)), returncode_counts=dict(Counter((str(r.get('returncode')) for r in receipts))), child_cpu_seconds=child, controller_self_cpu_seconds=own, known_measured_cpu_seconds=child + (own or 0), disjoint_stage_cpu_seconds=child + own if own is not None else None, controller_receipt_available=c is not None, controller_elapsed_wall_seconds=c['controller_wall_seconds'] if c else None, summed_child_wall_seconds=sum((r.get('wall_seconds', 0) for r in receipts)), maximum_worker_rss_kib=max((r.get('peak_rss_kib', 0) for r in receipts)), controller_status=c['status'] if c else 'not archived', receipts=receipts, scope='Child wait4 user+system plus archived controller self CPU. Missing controller CPU is unknown, not zero. Nested candidate/content/diagnostic/persistence/launch CPU is not added again.')

def collect(cache, output):
    begin_cpu, begin_wall = (time.process_time(), time.perf_counter())
    frozen = cache / 'frozen'
    protocol, seal, freeze = (read(frozen / 'protocol.json'), read(frozen / 'SEALED_MODELS.json'), read(frozen / 'SOURCE_FREEZE.json'))
    helper, checker_hash = raw_helpers(frozen / 'audit/independent.py')
    review = helper['Review']()
    quality = module(frozen / 'quality.py', 'frozen_quality')
    review.equal('protocol/hash', digest((frozen / 'protocol.json').read_bytes()), freeze['protocol_sha256'])
    review.equal('seal/protocol', seal['protocol'], protocol)
    review.equal('seal/fits', seal['fits'], protocol['fits'])
    review.equal('seal/source', seal['source_sha256'], freeze['source_sha256'])
    for n in ('statistics.py', 'quality.py'):
        review.equal('source/' + n, digest((frozen / n).read_bytes()), freeze['source_sha256']['tools/hcsn/digital_feedback_20261101/' + n])
    remote = read(frozen / 'evidence/MODELS_REMOTE.json')
    review.equal('remote/hash', digest((frozen / 'evidence/MODELS_REMOTE.json').read_bytes()), seal['remote_verification_sha256'])
    review.equal('remote/commit', remote['commit'], seal['published_models_commit'])
    review.equal('remote/manifest', remote['model_manifest_sha256'], seal['model_manifest_sha256'])
    review.equal('remote/verified', remote['all_blob_hashes_verified'], True)
    costs, archives = ([], [])
    for phase in PHASES:
        folder, receipt = restore(cache, phase + '_control')
        archives.append(receipt)
        costs.append(phase_cost(folder, phase, review))
    control = cache / 'restored/confirmation_001_control'
    trained = cache / 'restored/training_002_control'
    for fit in protocol['fits']:
        p = trained / 'process_receipts' / f'fit_{fit}.json'
        review.equal(f'training/{fit}/hash', digest(p.read_bytes()), seal['process_sha256'][str(fit)])
        review.equal(f'training/{fit}/returncode', read(p)['returncode'], 0)
    rows, qualities, decoders, starts = ([], [], [], [])
    counts = Counter()
    timing = defaultdict(float)
    worlds, payloads = (set(), set())
    overlap = Counter()
    for fit in protocol['fits']:
        folder, archive = restore(cache, f'confirmation_001_fit_{fit}')
        archives.append(archive)
        started, finished = (read(folder / 'STARTED.json'), read(folder / 'FINISHED.json'))
        receipt = read(control / 'process_receipts' / f'fit_{fit}.json')
        review.equal(f'{fit}/returncode', receipt['returncode'], 0)
        review.equal(f'{fit}/finished', finished['fit'], fit)
        review.equal(f'{fit}/started', started['fit'], fit)
        review.equal(f'{fit}/preexisting', started['confirmation_preexisting'], False)
        review.equal(f'{fit}/seal', started['seal_sha256'], digest((frozen / 'SEALED_MODELS.json').read_bytes()))
        review.equal(f'{fit}/models', started['published_models_commit'], seal['published_models_commit'])
        review.equal(f'{fit}/chronology', datetime.fromisoformat(started['utc']) >= datetime.fromisoformat(seal['sealed_utc']), True)
        starts.append(started['utc'])
        summary = read(folder / 'summary.json')
        index = {(r['fit'], r['split'], r['candidate']): r for r in summary}
        rows.extend(summary)
        review.equal(f'{fit}/summary_unique', len(index), len(summary))
        review.equal(f'{fit}/summary_inventory', sorted(index), sorted(((fit, s, a) for s in ('iid', 'ood') for a in ARMS)))
        for split in ('iid', 'ood'):
            prefix = f'{fit}/{split}'
            cohort = read(folder / f'{split}_cohort.json')
            ids = [r['id'] for r in cohort['records']]
            expected = [f'{split}_fit{fit}_{i:04d}' for i in range(protocol[f'{split}_worlds'])]
            review.equal(prefix + '/worlds', ids, expected)
            overlap['world_ids'] += len(worlds.intersection(ids))
            worlds.update(ids)
            ps = set(cohort['payload_sha256'])
            overlap['payloads_between_cohorts'] += len(payloads.intersection(ps))
            payloads.update(ps)
            for name, expected_hash in cohort['files'].items():
                review.equal(prefix + '/file/' + name, digest((folder / 'worlds' / name).read_bytes()), expected_hash)
            episodes, audits = (read(folder / f'{split}_episodes.json.gz'), read(folder / f'{split}_audits.json.gz'))
            q = quality.quality_audit(audits, protocol['quality_thresholds'])
            review.tree(prefix + '/quality', read(folder / f'{split}_quality.json'), q)
            qualities.append(dict(fit=fit, split=split, report=q))
            groups, diagnostics = (defaultdict(list), defaultdict(dict))
            seen = set()
            for episode in episodes:
                candidate, world = (episode['candidate'], episode['world'])
                identity = (candidate, world)
                review.equal(prefix + '/episode_identity', identity not in seen and candidate in ARMS and (world in ids), True)
                seen.add(identity)
                review.equal(prefix + '/episode_fit', episode['fit'], fit)
                review.equal(prefix + '/episode_split', episode['split'], split)
                seed = protocol['execution_seed_base'] + fit * 100000 + (20000 if split == 'ood' else 10000) + ids.index(world)
                review.equal(prefix + '/seed', episode['seed'], seed)
                wf = folder / 'worlds' / world
                public, evaluator = (read(wf / 'public.json'), read(wf / 'evaluator.json'))
                outcome, decision_rows = helper['episode_values'](review, episode, public, prefix + '/' + candidate + '/' + world, evaluator_label=evaluator['label'], world_folder=wf)
                groups[candidate].append(outcome)
                diagnostics[candidate].update({(world, j): v for j, v in enumerate(decision_rows)})
                counts['episodes'] += 1
                counts['decisions'] += len(decision_rows)
                counts['events'] += int(outcome['events'])
                counts['recoveries'] += int(outcome['recoveries'])
                for key in ('execution_cpu_seconds', 'content_cpu_seconds', 'diagnostic_cpu_seconds', 'episode_wall_seconds'):
                    timing[key] += episode['metrics'][key]
            for candidate in ARMS:
                row = index[fit, split, candidate]
                review.equal(prefix + '/' + candidate + '/paired_worlds', sorted((w for a, w in seen if a == candidate)), sorted(ids))
                review.equal(prefix + '/' + candidate + '/world_count', row['worlds'], protocol[f'{split}_worlds'])
                review.equal(prefix + '/' + candidate + '/valid', row['valid'], True)
                for key in groups[candidate][0]:
                    review.number(prefix + '/' + candidate + '/mean/' + key, row['metrics'][key], float(np.mean([v[key] for v in groups[candidate]])))
                ar = audits[candidate]['decisions']
                review.equal(prefix + '/' + candidate + '/audit_count', len(ar), len(diagnostics[candidate]))
                audited = set()
                for item in ar:
                    identity = (item['world'], item['decision'])
                    review.equal(prefix + '/unique_audit', identity not in audited, True)
                    audited.add(identity)
                    for key, value in diagnostics[candidate][identity].items():
                        if value is None:
                            review.equal(prefix + '/diagnostic/' + key, item['metrics'][key], None)
                        else:
                            review.number(prefix + '/diagnostic/' + key, item['metrics'][key], value)
            decoder, probe = (read(folder / f'{split}_decoder.json'), read(folder / f'{split}_probe.json.gz'))
            review.equal(prefix + '/decoder_not_refit', decoder['fitted_during_evaluation'], False)
            dg = {}
            for name, value in decoder['groups'].items():
                predictions = value['predictions']
                if predictions:
                    mse = {m: float(np.mean([(r['predicted'][m] - r['target']) ** 2 for r in predictions])) for m in ('before_cell', 'after_cell', 'before_full', 'after_full')}
                    for m, v in mse.items():
                        review.number(prefix + '/decoder/' + name + '/' + m, value['mse'][m], v)
                    delta = {m: mse['after_' + m] - mse['before_' + m] for m in ('cell', 'full')}
                    for m, v in delta.items():
                        review.number(prefix + '/decoder/' + name + '/delta_' + m, value['paired_mse_difference_after_minus_before'][m], v)
                    dg[name] = dict(pairs=len(predictions), mse=mse, after_minus_before=delta)
                else:
                    dg[name] = dict(pairs=0, mse=None, after_minus_before=None)
            decoders.append(dict(fit=fit, split=split, groups=dg))
            counts['probe_episodes'] += len(probe['episodes'])
            counts['cohort_worlds'] += len(ids)
        counts['fits'] += 1
        print(json.dumps(dict(fit=fit, completed=counts['fits'], violations=review.violations_count)), flush=True)
    review.equal('holdout/repeated_world_ids', overlap['world_ids'], 0)
    review.equal('holdout/repeated_payloads_between_cohorts', overlap['payloads_between_cohorts'], 0)
    record = dict(schema='digital-feedback-confirmation-completion-v1', source_commit=SOURCE, protocol_sha256=digest((frozen / 'protocol.json').read_bytes()), seal_sha256=digest((frozen / 'SEALED_MODELS.json').read_bytes()), raw_checker_sha256=checker_hash, raw_checker_exact_ast_functions=sorted(HELPERS), verification=review.report(), counts=dict(counts), archives=archives, phase_costs=costs, known_measured_stage_cpu_seconds=sum((r['known_measured_cpu_seconds'] for r in costs)), all_stage_controller_costs_complete=all((r['controller_receipt_available'] for r in costs)), nested_confirmation_timing_totals=dict(timing), holdout_custody=dict(published_source_commit=seal['published_source_commit'], published_models_commit=seal['published_models_commit'], sealed_utc=seal['sealed_utc'], earliest_confirmation_start_utc=min(starts), latest_confirmation_start_utc=max(starts), within_confirmation_overlap=dict(overlap), historical_namespace_audit=read(frozen / 'evidence/FINAL_PROTOCOL_SOURCE_AUDIT_V2.json'), scope='Frozen registered IID/OOD namespaces and declared historical audit inventory only; no universal unseen-data claim.'), inherited_training_qualification=seal['cpu_matching'], inherited_training_audit=read(frozen / 'evidence/TRAINING_RECORDS_AUDIT.json'), failure_ledger=read(frozen / 'evidence/DEVELOPMENT_FAILURE_LEDGER.json'), collector_cpu_seconds=time.process_time() - begin_cpu, collector_wall_seconds=time.perf_counter() - begin_wall, scope='Byte reconstruction and raw-record task-state, decision, charge and outcome replay; eight quality criteria recomputed from linked raw audits; retained decoder MSE checked. Teacher oracle, model logits, latent random draws and decoder coefficients are not refitted/replayed. Training qualification carries the published 480-receipt audit and sealed matrix, with current training process hashes verified. No new worlds or training.')
    result = dict(schema='digital-feedback-completion-inputs-v1', protocol=protocol, summary_rows=rows, quality=qualities, decoder=decoders, record=record)
    save(output / 'CONFIRMATION_COMPLETION_INPUTS.json.gz', result)
    if not record['verification']['passed']:
        raise ValueError('Record audit failed; do not publish inference')
    return result

def finalize(data, frozen, output):
    assert data['record']['verification']['passed'] is True
    protocol, record = (data['protocol'], data['record'])
    for phase in record['phase_costs']:
        phase.pop('started_workers', None)
        phase.pop('cancelled_before_start', None)
        phase['workers_with_positive_cpu'] = sum((r['cpu_seconds'] > 0 for r in phase['receipts']))
        phase['returncode_counts'] = dict(Counter((str(r.get('returncode')) for r in phase['receipts'])))
    assert record['source_commit'] == SOURCE, 'input source commit mismatch'
    assert protocol == read(frozen / 'protocol.json'), 'input protocol mismatch'
    assert digest((frozen / 'protocol.json').read_bytes()) == record['protocol_sha256'], 'protocol byte hash mismatch'
    freeze = read(frozen / 'SOURCE_FREEZE.json')
    assert digest((frozen / 'statistics.py').read_bytes()) == freeze['source_sha256']['tools/hcsn/digital_feedback_20261101/statistics.py'], 'frozen inference source changed'
    statistics = module(frozen / 'statistics.py', 'frozen_statistics')
    analysis = statistics.analyze(data['summary_rows'], protocol)
    rollup = []
    for candidate in ARMS:
        for split in ('iid', 'ood'):
            values = [r['report']['candidates'][candidate] for r in data['quality'] if r['split'] == split]
            gate_counts = {g: sum((v['gates'][g] is True for v in values)) for g in values[0]['gates']}
            metrics = {m: float(np.mean([v['metrics'][m] for v in values])) for m in values[0]['metrics'] if all((v['metrics'][m] is not None for v in values))}
            rollup.append(dict(candidate=candidate, split=split, fits=len(values), complete=sum((v['status'] == 'complete' for v in values)), overall_pass=sum((v['overall'] is True for v in values)), gate_pass_counts=gate_counts, metric_fit_means=metrics))
    required = protocol['quality_thresholds']['required_candidates']
    all_quality = all((r['report']['all_required_pass'] is True for r in data['quality']))
    arm_means = []
    for split in ('iid', 'ood'):
        for candidate in ARMS:
            rows = [r for r in data['summary_rows'] if r['split'] == split and r['candidate'] == candidate]
            arm_means.append(dict(split=split, candidate=candidate, n_fits=len(rows), metrics={m: float(np.mean([r['metrics'][m] for r in rows])) for m in rows[0]['metrics']}))
    decoders = []
    for split in ('iid', 'ood'):
        for group in ('event', 'recovery', 'combined'):
            rows = [r['groups'][group] for r in data['decoder'] if r['split'] == split]
            valid = [r for r in rows if r['pairs']]
            decoders.append(dict(split=split, group=group, fit_count=len(rows), nonempty_fit_count=len(valid), total_pairs=sum((r['pairs'] for r in rows)), fit_mean_after_minus_before={m: float(np.mean([r['after_minus_before'][m] for r in valid])) for m in ('cell', 'full')} if valid else None, interpretation='Descriptive paired linear-recovery MSE; equal fit weighting; no causal reset or irreversibility claim.'))
    analysis.update(source_commit=SOURCE, protocol_sha256=record['protocol_sha256'], seal_sha256=record['seal_sha256'], raw_record_audit_passed=True, quality_all_required_pass=all_quality, quality_fit_domain_pairs=len(data['quality']), quality_fit_domain_pairs_passing_all_required=sum((r['report']['all_required_pass'] is True for r in data['quality'])), required_candidate_fit_domain_checks=len(data['quality']) * len(required), required_candidate_fit_domain_passes=sum((r['report']['candidates'][c]['overall'] is True for r in data['quality'] for c in required)), quality_rollup=rollup, decoder_rollup=decoders, arm_means=arm_means, acceptance=bool(analysis['all_four_benefit_gates'] and all_quality and record['inherited_training_qualification']['all_actual_cpu_matching'] and record['inherited_training_qualification']['all_training_valid']), conclusion_scope='Frozen finite-interval readout/feedback experiment. Analytic increment is a descriptive secondary, not a passed pure-kernel D-minus-B or open-domain superiority gate.')
    save(output / 'ANALYSIS.json', analysis)
    save(output / 'CONFIRMATION_COMPLETION_AUDIT.json', record)
    print(json.dumps(dict(accepted=analysis['acceptance'], raw_audit=record['verification']['passed'], quality_passes=analysis['required_candidate_fit_domain_passes'], primary=[dict(split=r['split'], contrast=r['contrast'], mean=r['inference']['mean'], interval=r['inference']['confidence_interval'], benefit=r['benefit_gate']) for r in analysis['primary']]), indent=2))
    return analysis

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--inputs', type=Path)
    p.add_argument('--collect-only', action='store_true')
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    values = read(a.inputs) if a.inputs else collect(a.cache, a.output)
    if not a.collect_only:
        finalize(values, a.cache / 'frozen', a.output)
if __name__ == '__main__':
    main()
