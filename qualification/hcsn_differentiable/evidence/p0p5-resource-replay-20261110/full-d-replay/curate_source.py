"""Curate exact frozen replay originals and publication evidence; never rerun a model."""
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

BASE = Path('/workspace/scratch/c385a7439f8e')
WORK = BASE / 'hcsn-best-full-d-replay-v1'
OUT = BASE / 'hcsn-best-full-d-handoff-v1'


def identity(path):
    raw = Path(path).read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def save(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def main():
    OUT.mkdir(exist_ok=False)
    shutil.copytree(WORK/'small-originals', OUT/'originals')
    shutil.copy2(WORK/'hcsn-best-full-D-small-originals-20261110-v1.zip', OUT/'small-originals.zip')
    manifest = json.loads((OUT/'originals/MEMBER-MANIFEST.json').read_bytes())
    for name, item in manifest.items():
        assert identity(OUT/'originals'/name) == {'bytes':item['bytes'], 'sha256':item['sha256']}
    prefixes = {
        '/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/best-full-D-archive-upload-v1/': 'attempt-v1',
        '/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/best-full-D-archive-launch-v1/': 'launch-v1',
        '/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/best-full-D-asset-upload-v2/': 'attempt-v2',
        '/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/best-full-D-asset-launch-v2/': 'launch-v2',
    }
    provenance = {}
    for filename in ['PUBLICATION-FAILURE-READBACK.json','PUBLICATION-CAUSE-READBACK.json','PUBLICATION-FINAL-READBACK.json']:
        response = json.loads((WORK/filename).read_bytes())
        for block in response['content']:
            if block['type'] != 'text':
                continue
            for item in json.loads(block['text']).get('files',[]):
                raw = item['text'].encode()
                assert len(raw) == item['size'] and hashlib.sha256(raw).hexdigest() == item['sha256']
                found = [(prefix, label) for prefix, label in prefixes.items() if item['path'].startswith(prefix)]
                assert len(found) == 1
                prefix, label = found[0]
                rel = Path('publication')/label/item['path'][len(prefix):]
                assert not rel.is_absolute() and '..' not in rel.parts
                target = OUT/rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    assert target.read_bytes() == raw
                else:
                    target.write_bytes(raw)
                provenance[str(rel)] = dict(native_path=item['path'], bytes=len(raw), sha256=item['sha256'],
                                            read_version=item['version'], transport_receipt=filename)
    for source, dest in [('archive_upload_native.py','attempt-v1/driver.py'),
                         ('publication_starter.py','launch-v1/starter.py'),
                         ('upload_native_v2.py','attempt-v2/driver.py'),
                         ('publication_starter_v2.py','launch-v2/starter.py')]:
        shutil.copy2(WORK/source, OUT/'publication'/dest)
    save(OUT/'publication/READBACK-PROVENANCE.json',provenance)
    before = json.loads((OUT/'publication/attempt-v1/RESULT.json').read_bytes())
    after = json.loads((OUT/'publication/attempt-v2/RESULT.json').read_bytes())
    assert not before['assets'] and not any(row['label']=='upload-once' for row in before['commands'])
    assert after['status']=='full_replay_asset_verified_draft_unchanged' and len(after['assets'])==1
    asset = after['assets'][0]
    assert asset['asset_id']==732788592 and asset['authenticated_full_readback_verified'] and asset['all_members_and_CRC_verified']
    assert asset['sha256']=='ff41e5ef909708a5c2472f6786d0e82b6d69a80d968047de2746bcaf84daaac5'
    assert after['final_draft_identity_verified']['draft'] is True
    summary = json.loads((OUT/'originals/replay/SUMMARY.json').read_bytes())
    names = [f'hcsn-s{s}-lr{lr}' for s in [101,211,307] for lr in ['0.001','0.003']]
    assert [entry['name'] for entry in summary['entries']] == names
    rows = []
    for entry in summary['entries']:
        name = entry['name']
        result_path = OUT/'originals/replay'/name/'RESULT.json'
        result = json.loads(result_path.read_bytes())
        assert result == entry['result'] and result['quality_reproducibility']=='passed'
        assert result['fresh_development']['events']==31952
        assert result['fresh_development']['confusion_matrix']==result['expected_development']['confusion_matrix']
        assert result['original_training_adequacy'] is False and result['scientific_admission']=='HOLD'
        assert result['original_status']=='budget_exhausted'
        assert result['inputs_unchanged'] and result['frozen_shared_and_physics_equal_initial']
        assert result['tensor_digest_before']==result['tensor_digest_after']
        assert result['training_updates']==result['backward_calls']==result['optimizer_operations']==0
        assert not result['confirmation_E_access']
        differences=result['metric_absolute_differences']
        assert all(value <= 2e-12 for value in differences.values())
        rows.append(dict(name=name,best_epoch=result['best_epoch'],original_complete_epochs=result['original_complete_epochs'],
            metrics=result['fresh_development'],max_metric_absolute_difference=max(differences.values()),
            original_training_status=result['original_status'],training_adequacy=False,
            best_checkpoint_sha256=result['best_checkpoint_sha256'],result=identity(result_path),
            fresh_logits=result['fresh_logits'],whole_child_wall_seconds=entry['outer']['whole_child_wall_seconds'],
            waited_child_CPU_seconds=entry['outer']['waited_child_CPU_seconds'],
            self_peak_rss_bytes=result['self_peak_rss_bytes'],sampled_peak_rss_bytes=entry['outer']['sampled_peak_rss_bytes']))
    cost=json.loads((OUT/'originals/archive-context/COSTS.json').read_bytes())
    v1=json.loads((OUT/'publication/launch-v1/receipt.json').read_bytes())
    v2=json.loads((OUT/'publication/launch-v2/receipt.json').read_bytes())
    costs=dict(schema='six-best-D-full-lifecycle-scopes-v1',replay_and_validation=cost,
        publication_attempt_v1=v1,publication_attempt_v2=v2,
        archive_build_nested_in_attempt_v1=before['archive'],
        additive_rule='Local synthetic validation, bootstrap/native validation+replay, v1 packaging/publication failure, and v2 asset-only publication are distinct. Native validation/controller/per-fit times are nested in bootstrap; package/gh times are nested in publication. Do not add nested terms. Network-tool transport and unmeasured preparation costs are not an exact experiment total.',
        original_training_costs='Separate existing campaign ledger; no original training cost is refunded or repeated here.',
        transport_CPU_seconds=None,energy_joules=None,scientific_admission='HOLD')
    save(OUT/'COSTS.json',costs)
    result=dict(schema='six-best-HCSN-full-D-independent-quality-replay-handoff-v1',
        status='six_fresh_full_D_replays_and_draft_archive_verified',fits=rows,
        all_confusion_matrices_equal=True,max_metric_absolute_difference=max(r['max_metric_absolute_difference'] for r in rows),
        confirmation_E_access=False,optimizer_operations=0,backward_calls=0,training_updates=0,
        original_training_adequacy=False,scientific_admission='HOLD',numerical_admission='not_assessed_here',
        source_capsule_sha256='288283cae2b2cf4e7b68432e040e643a5e1b00a7de961fc848dd5cf20eb46102',
        data_manifest_sha256='0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb',
        program_capsule_sha256='a748888f26409ff6f5fff8db8a9266cf67d0a5f5516dc88b566cd3c296fca206',
        full_archive_asset=asset,small_originals=identity(OUT/'small-originals.zip'),
        published_release=False,release_id=440410488,
        historical_publication_failure='v1 gh rejected unsupported --slurp before any upload; preserved. v2 used bounded explicit pagination and uploaded the existing sealed archive once.',
        scope='Reproducibility of original strict-best D development checkpoints for all six budget-censored fits. D is reused development data; no E confirmation, adequate-training credit, HCSN advantage, numerical qualification, or full-CI claim.')
    save(OUT/'SUMMARY.json',result)
    lines=['# Independent full-D replay of six original HCSN best checkpoints','',
        'All six fresh full-development forwards reproduced their original best-epoch confusion matrices exactly. The largest scalar metric difference was 2.220446049250313e-16, below the frozen 2e-12 gate. The original six fits remain `budget_exhausted`, with training adequacy false. This replay does not establish sufficient training, held-out E confirmation, numerical qualification, or an architectural benefit.','',
        '## Method and source identity','',
        'The plan and 13-file program were frozen before accessing the six real checkpoints. Both local and exact-native-runtime synthetic validations passed 16 tests. The replay used the actual v8 source, native Torch 2.8.0+cu128, immutable construction configuration, CPU FP64, one thread, and the original full batch-32 evaluation layout. Each of 128 D windows was consumed in manifest order, yielding 31,952 labelled events per fit. Best selection used the first strict maximum in the original epoch history; last checkpoints were not substituted. Budget reports legitimately omit selected-development logits, so comparison is against the bound original best-epoch metrics and confusion matrix.','',
        'The independent NumPy calculation recomputed accuracy, macro F1, balanced accuracy, NLL, both Brier conventions, and 15-bin ECE. Model, frozen common/physical tensors, source, and inputs were checked before and after. There were zero optimizer constructions/restores/steps, training updates, or backward calls. Reading existing optimizer/RNG fields inside a safely loaded checkpoint did not execute optimizer operations. Confirmation E data was not read.','',
        '| Fit | Best epoch | Macro F1 | Accuracy | NLL | Full child wall (s) | Exit child CPU (s) |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        m=row['metrics'];lines.append(f"| {row['name']} | {row['best_epoch']} | {m['macro_f1_11_classes']:.9f} | {m['accuracy']:.9f} | {m['nll']:.9f} | {row['whole_child_wall_seconds']:.6f} | {row['waited_child_CPU_seconds']:.6f} |")
    lines += ['', 'All six candidates are retained; these rows do not select a best seed or claim that seed variability measures unseen-subject uncertainty. Original D-based model selection remains development tuning.', '',
        '## Cost scope', '',
        'The complete controller process group took 730.308706774 s wall and 735.746561 s waited controller-plus-descendant CPU. The outer bootstrap interval, including native synthetic validation, extraction and replay, was 733.179974144 s after its standard-library imports; its waited children used 739.440259 s CPU, with 0.184126431 s bootstrap own CPU reported separately. These are overlapping measurements and must not be summed. Local synthetic validation was an additional 1.820557447 s full child wall and 1.685351 s CPU. An earlier exploratory validation has no complete process timer and remains explicitly unknown.', '',
        'Peak per-fit self ru_maxrss was 920,285,184 B; the largest sampled RSS was 921,694,208 B. Both were below the declared 2 GiB gate; these two measurements have different sampling semantics. The replay may overlap the separate numerical audit, so it is not a dedicated-host speed comparison. Energy was not measured.', '',
        'Publication attempt v1 took 8.536668790 s whole child wall and 3.818212 s waited child-plus-descendant CPU. It successfully sealed the archives but failed on the installed gh version rejecting --slurp; no upload branch was reached. The corrected v2 used the same sealed archive, one upload, and a complete authenticated readback. Its complete child wall was 37.780077072 s and child-plus-descendant CPU 4.05913 s. No model or numerical oracle was rerun for packaging or publication. Transport and unmeasured preparation costs remain outside an exact combined total.', '',
        '## Evidence and archival boundary', '',
        'The full archive hcsn-best-full-D-independent-replay-20261110-v1.zip is 19,144,412 B with 254 members, SHA256 ff41e5ef909708a5c2472f6786d0e82b6d69a80d968047de2746bcaf84daaac5. It is asset 732788592 on draft release 440410488. Authenticated full download, ZIP CRC and every member hash passed; anonymous asset API/browser and release requests returned 404, and final metadata still says draft. The release was not published.', '',
        'The full archive contains complete new logits, labels, episode/position/source-row order, all stage logs and receipts, frozen program and actual loaded source, and the D input bytes. Original model bytes are bound member-by-member to the previously authenticated original HCSN archive rather than duplicated. This handoff includes all 80 small-original members, the exact small ZIP, full-archive member manifest, model bindings, both publication attempts, and result/cost summaries. The separate source artifact itself was not altered.', '',
        'The original 16,811,170 B controller-only ZIP is preserved on the native host. It was not the uploaded container: all of its directory members are included byte-for-byte in the distinct combined archive. Published archive integrity is evidence of reproducibility, not scientific or CI admission.']
    (OUT/'REVIEW.md').write_text('\n'.join(lines)+'\n')
    shutil.copy2(Path(__file__),OUT/'curate_source.py')
    files={str(p.relative_to(OUT)):identity(p) for p in sorted(OUT.rglob('*')) if p.is_file()}
    save(OUT/'MANIFEST.json',dict(schema='screened-full-D-handoff-v1',files=files))
    entries={name:dict(source=str(OUT/name),**item) for name,item in files.items()}
    entries['MANIFEST.json']=dict(source=str(OUT/'MANIFEST.json'),**identity(OUT/'MANIFEST.json'))
    save(OUT/'COPY_LIST.json',dict(destination_prefix='review/hcsn-best-full-D-independent-v1',files=entries,
        only_frozen_files=True,scope='Copy these explicit files; transport base64 and changing work directories are excluded.'))
    archive=BASE/'hcsn-best-full-d-handoff-v1.zip'
    with ZipFile(archive,'x',compression=ZIP_DEFLATED) as zipped:
        for path in sorted(OUT.rglob('*')):
            if path.is_file(): zipped.write(path,str(path.relative_to(OUT)))
    with ZipFile(archive) as zipped:
        assert zipped.testzip() is None
    print(json.dumps(dict(directory=str(OUT),archive=dict(path=str(archive),**identity(archive)),
        summary=identity(OUT/'SUMMARY.json'),manifest=identity(OUT/'MANIFEST.json'),copy_list=identity(OUT/'COPY_LIST.json'))))


if __name__ == '__main__':
    main()
