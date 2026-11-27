"""Revalidate the frozen selections before extracting the historical test once.

No history-test metrics, no Torch, model evaluation, fitting or root solving.
Only the root-approved final workflow may execute this test extraction step.
"""
import ast
import base64
import io
import json
from pathlib import Path
import sys
import time
import zipfile
from audit_support import (SEEDS, admit_archive, bounded_zip, checked, encoded,
    load_module, save, selection_from_archives, sha, source_check, write)

HERE=Path(__file__).resolve().parent


def main():
    if len(sys.argv)!=7:
        raise SystemExit('prepare_public.py BINDING HELPER TRANSFER ARTIFACT_DIRECTORY NEW_PREPARED NEW_RECEIPT')
    binding_path,helper,transfer,artifacts,destination,receipt=(Path(v).resolve() for v in sys.argv[1:])
    started,cpu=time.monotonic(),time.process_time()
    decoded_test=False
    test_extracted=False
    try:
        binding_raw=binding_path.read_bytes()
        binding=json.loads(binding_raw)
        if (binding['status']!='FROZEN_FOR_EXECUTION_AFTER_ROOT_REVIEW' or
                binding['parent_order']!=list(SEEDS) or len(binding['root_review_sha256'])!=64):
            raise ValueError('unreviewed final audit')
        source_check(binding,HERE,helper,transfer)
        independent=json.loads(checked((HERE/'SOURCE137_INDEPENDENT_AUDIT.json').read_bytes(),
            binding['independent137_audit']))
        correction=json.loads(checked((HERE/'SOURCE137_SELECTOR_CORRECTION.json').read_bytes(),
            binding['independent137_selector_correction']))
        if (independent['status']!='ACTUAL_BYTES_METRICS_SCOPE_AND_COUNTS_VERIFIED' or
                independent['artifact_sha256']!=binding['predecessor_artifacts']['repair137']['sha256'] or
                correction['original_audit_sha256']!=binding['independent137_audit']['sha256'] or
                correction['status']!='PASS_EXACT_ORIGINAL_BRIER_KEEP_PRIORITY_RULE' or
                correction['selection_changed'] is not False):
            raise ValueError('original137 raw audit/supplementary selector correction differs')
        manifests={seed:json.loads(checked((HERE/f'public_inputs_seed{seed}.json').read_bytes(),
            binding['parent_manifests'][str(seed)])) for seed in SEEDS}
        archives={key:admit_archive(artifacts/(key+'.zip'),item)
            for key,item in binding['predecessor_artifacts'].items()}
        frozen=checked((HERE/'SELECTED_MODELS.json').read_bytes(),binding['selection_lock'])
        support=load_module('frozen_original_selection_only',helper/'static_support.py')
        selection=selection_from_archives(binding,manifests,archives,support.choose)
        if encoded(selection)!=frozen:
            raise ValueError('selected checkpoint identities changed before test extraction')
        if (independent['result_sha256']!=selection['parents'][2]['source_result_sha256'] or
                correction['result_sha256']!=selection['parents'][2]['source_result_sha256']):
            raise ValueError('independent137 audit does not bind actual repair result')
        destination.mkdir(parents=True,exist_ok=False)
        save(destination/'SELECTED_MODELS.json',frozen)
        lock= dict(selection_sha256=sha(frozen),selection_recomputed_from_original_frozen_rule=True,
            selected_checkpoints=selection['unique_checkpoints'],all_original_slots_retained=True,
            test_array_extracted_yet=False,test_array_decoded_yet=False,model_calls=0)
        write(destination/'SELECTION_REVALIDATED_BEFORE_TEST.json',lock)
        if (destination/'SELECTED_MODELS.json').read_bytes()!=frozen:
            raise ValueError('persisted selection lock readback differs')
        # Only after the immutable pre-test selection has matched do we fetch
        # the source payload. Never fetch lowlevel_results.json or inspect its
        # historical test fields for this audit.
        old=load_module('frozen_public_byte_fetcher',transfer/'prepare_public.py')
        shared=manifests[47]
        common=('source_commit','data_contract','payload_script','inner_zip_sha256','payload_members',
                'normalizer_sha256','normalizer_f32_le_hex','aliases')
        if any(manifests[seed][key]!=shared[key] for seed in (83,137) for key in common):
            raise ValueError('three parents do not share exact public source/input identity')
        public,downloads={},[]
        for name in ('selected_checkpoints.zip','t4_payload.zip'):
            item=next(v for v in shared['inputs'] if Path(v['path']).name==name)
            raw=old.fetch(dict(item,commit=shared['source_commit']))
            public[name]=raw
            downloads.append(dict(path=item['path'],bytes=len(raw),sha256=sha(raw),git_blob=item['git_blob']))
        contract=old.fetch(shared['data_contract'])
        data_contract=json.loads(contract)
        if (data_contract['splits']['test']!=[5,6,11,12,21,22] or
                data_contract['source_integrity_erratum']['expected_queries']['test']!=48):
            raise ValueError('historical test contract differs')
        downloads.append(dict(path=shared['data_contract']['path'],bytes=len(contract),sha256=sha(contract)))
        outer=bounded_zip(public['t4_payload.zip'],{'t4_submitted.py'})
        submitted=checked(outer.read('t4_submitted.py'),shared['payload_script'])
        literals=[node.value for node in ast.walk(ast.parse(submitted)) if
            isinstance(node,ast.Constant) and isinstance(node.value,bytes)]
        if len(literals)!=1:
            raise ValueError('exact static payload literal differs')
        inner=base64.b64decode(literals[0],validate=True)
        if sha(inner)!=shared['inner_zip_sha256']:
            raise ValueError('static inner ZIP differs')
        listing={item['path']:item for item in shared['payload_members']}
        payload=bounded_zip(inner,listing)
        test=checked(payload.read('data/test.npz'),listing['data/test.npz'])
        save(destination/'test.npz',test)
        test_extracted=True
        checkpoints=zipfile.ZipFile(io.BytesIO(public['selected_checkpoints.zip']))
        if len(checkpoints.namelist())!=len(set(checkpoints.namelist())):
            raise ValueError('duplicate public checkpoint member')
        for seed,row in zip(SEEDS,selection['parents']):
            manifest=manifests[seed]
            parent=destination/f'parent{seed}'
            parent.mkdir(exist_ok=False)
            save(parent/'data_contract.json',contract)
            for name,item in listing.items():
                if name.startswith('data/'):
                    continue
                raw=checked(payload.read(name),item)
                target=parent/'source'/name
                target.parent.mkdir(parents=True,exist_ok=True)
                save(target,raw)
            cp=manifest['checkpoint']
            raw=checked(checkpoints.read(cp['archive_member']),cp)
            seal=checkpoints.read(cp['seal_member'])
            if sha(seal)!=cp['seal_sha256'] or json.loads(seal)[f'centered_{seed}']!=sha(raw):
                raise ValueError('public parent checkpoint seal differs')
            save(parent/'parent.pt',raw)
            archive=archives[row['source_artifact_key']]
            for selected in row['unique_evaluations']:
                if selected['source']=='PUBLIC_PARENT':
                    continue
                for suffix in ('.pt','.f32le'):
                    name=selected['name']+suffix
                    save(parent/name,archive.read(row['source_prefix']+'/'+name))
            qitem=row['qualification']
            save(parent/'REUSED_CPU_QUALIFICATION.json',archives[qitem['artifact_key']].read(qitem['member']))
        costs={}
        for key,paths in binding['prior_cost_files'].items():
            costs[key]={path:dict(sha256=sha(archives[key].read(path)),value=json.loads(archives[key].read(path)))
                        for path in paths}
        write(destination/'PRIOR_COSTS.json',dict(schema='hepta.historical-audit-prior-costs.v1',receipts=costs,
            old_failed_fit_included=True,old_unknown_count_flags_unchanged=True,
            source47_boundary_abstention_cost_included=True,shared_cost_not_duplicated=True,
            cost_scope='These three hidden-edit source lanes plus seed47 boundary abstention; not every earlier research action.',
            conversational_planning_cost='UNAVAILABLE_NOT_MEASURED_ZERO',quality_matched_speedup_claim=False))
        files={str(path.relative_to(destination)):dict(bytes=path.stat().st_size,sha256=sha(path.read_bytes()))
            for path in sorted(destination.rglob('*')) if path.is_file()}
        prepared=dict(schema='hepta.locked-historical-test-prepared.v1',binding_sha256=sha(binding_raw),
            selection_sha256=sha(frozen),files=files,downloads=downloads,model_calls=0,fits=0,roots=0,
            test_npz_extracted=True,test_npz_decoded=False,historical_test_scores_read=False,
            train_dev_retain_arrays_extracted=False,submitted_payload_executed=False,
            prior_qualification_reused_without_new_model_calls=True,cpu_seconds=time.process_time()-cpu,
            wall_seconds=time.monotonic()-started)
        write(destination/'PREPARED.json',prepared)
        write(receipt,dict(status='PREPARED_FINAL_HISTORICAL_AUDIT',prepared_sha256=sha((destination/'PREPARED.json').read_bytes()),
            selection_sha256=sha(frozen),test_npz_extracted=True,test_npz_decoded=False,model_calls=0,
            cpu_seconds=time.process_time()-cpu,wall_seconds=time.monotonic()-started))
    except BaseException as error:
        if not receipt.exists():
            write(receipt,dict(status='FAILED_BEFORE_MODEL',failure_type=type(error).__name__,
                test_npz_extracted=test_extracted,test_npz_decoded=decoded_test,model_calls=0,fits=0,roots=0,
                cpu_seconds=time.process_time()-cpu,wall_seconds=time.monotonic()-started,retries=0))
        raise RuntimeError('locked historical audit preparation failed; exact partial state retained') from None


if __name__=='__main__':
    main()
