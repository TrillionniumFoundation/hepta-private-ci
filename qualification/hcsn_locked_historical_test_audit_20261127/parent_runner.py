"""Final historical test only. Fixed sealed checkpoints, no fit or test-driven choice."""
import time
COLD_START=time.monotonic()

import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
from audit_support import CAPS, SEEDS, checked, sha, source_check, write

HERE=Path(__file__).resolve().parent


def prepared_check(prepared,binding_raw):
    raw=(prepared/'PREPARED.json').read_bytes()
    value=json.loads(raw)
    if value['binding_sha256']!=sha(binding_raw) or value['model_calls']!=0 or value['fits']!=0 or value['roots']!=0:
        raise ValueError('prepared input authority differs')
    for name,item in value['files'].items():
        checked((prepared/name).read_bytes(),item)
    return value


def main():
    if len(sys.argv)!=8:
        raise SystemExit('parent_runner.py BINDING HELPER TRANSFER PREPARED SEED NEW_OUTPUT EXPECTED_PREPARED_SHA')
    binding_path,helper,transfer,prepared=(Path(v).resolve() for v in sys.argv[1:5])
    seed=int(sys.argv[5])
    output=Path(sys.argv[6]).resolve()
    expected_prepared=sys.argv[7]
    output.mkdir(parents=True,exist_ok=False)
    result=dict(schema='hepta.locked-historical-test-parent.v1',name='LOCKED_HISTORICAL_TEST_AUDIT',
        seed=seed,status='STARTED',fresh_holdout=False,production=False,native_owner=False,
        new_fits=0,new_roots=0,new_backwards=0,prior_cpu_qualification_reused=True,
        selected_checkpoints_changed_after_test=False,test_used_for_parameter_selection=False,
        cases=[],forwards_returned=0,original_failure_and_unavailable_slots_retained=True)
    ledger,adapter,failure,phase=None,None,None,'SOURCE_ADMISSION'
    binding_raw=binding_path.read_bytes()
    binding=json.loads(binding_raw)
    write(output/'ENTRY.json',dict(binding_sha256=sha(binding_raw),**result))
    try:
        if (binding['status']!='FROZEN_FOR_EXECUTION_AFTER_ROOT_REVIEW' or seed not in SEEDS or
                binding['new_limits']!=CAPS or len(binding['root_review_sha256'])!=64):
            raise ValueError('unreviewed final test binding')
        source_check(binding,HERE,helper,transfer)
        receipt=prepared_check(prepared,binding_raw)
        if sha((prepared/'PREPARED.json').read_bytes())!=expected_prepared:
            raise ValueError('supervisor-prepared identity mismatch')
        frozen=checked((HERE/'SELECTED_MODELS.json').read_bytes(),binding['selection_lock'])
        if (prepared/'SELECTED_MODELS.json').read_bytes()!=frozen:
            raise ValueError('pre-test selections changed')
        selection=json.loads(frozen)
        selected=next(row for row in selection['parents'] if row['seed']==seed)
        result.update(family=selected['family'],selected_methods=selected['methods'],
            original_source_slots=selected['slot_results'],original_source_status=selected['original_status'],
            selected_before_test_sha256=sha(frozen),planned_unique_cases=selected['unique_evaluations'])
        manifest=json.loads(checked((HERE/f'public_inputs_seed{seed}.json').read_bytes(),
            binding['parent_manifests'][str(seed)]))
        if sys.version_info[:3]!=(3,12,3) or sys.byteorder!='little' or platform.machine()!='x86_64':
            raise ValueError('unqualified CPU interpreter/platform')
        versions={key:importlib.metadata.version(key) for key in ('torch','numpy','scipy')}
        if versions!={'torch':'2.10.0+cpu','numpy':'2.3.5','scipy':'1.17.0'}:
            raise ValueError('exact qualified CPU package versions differ')
        if any(os.environ.get(k)!='1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')):
            raise ValueError('single-thread numerical contract absent')
        sys.path.insert(0,str(helper))
        support=importlib.import_module('static_support')
        model_module=importlib.import_module('model_adapter')
        if (Path(support.__file__).resolve()!=helper/'static_support.py' or
                Path(model_module.__file__).resolve()!=helper/'model_adapter.py'):
            raise ValueError('actual helper module path differs')
        import numpy as np
        import torch
        from test_data import load_locked_test,per_query_metrics
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        caps=dict(CAPS)
        caps.update(forwards=len(selected['unique_evaluations']),body_ticks=6*len(selected['unique_evaluations']),
                    paired_queries=48*len(selected['unique_evaluations']))

        class Ledger(support.Ledger):
            def __init__(self):
                self.path=output/'calls.jsonl'
                self.path.touch(exist_ok=False)
                self.start=COLD_START
                self.counts={key:0 for key in CAPS}
                self.event('opened',caps=caps,seed=seed)
            def charge(self,name,amount=1):
                if name not in caps or type(amount)is not int or amount<0 or self.counts[name]+amount>caps[name]:
                    raise RuntimeError('fixed final-audit call cap exceeded: '+str(name))
                self.counts[name]+=amount
            def check_time(self):
                if time.process_time()>30 or time.monotonic()-COLD_START>60:
                    raise RuntimeError('fixed final parent CPU/wall cap exhausted')

        ledger=Ledger()
        phase='TEST_INPUT_DECODING'
        data=load_locked_test((prepared/'test.npz').read_bytes(),manifest)
        write(output/'TEST_INPUT_IDENTITY.json',dict(raw_sha256=sha((prepared/'test.npz').read_bytes()),
            train_normalizer_sha256=manifest['normalizer_sha256'],normalized_input_sha256=sha(data['x'].tobytes()),
            normalized_baseline_sha256=sha(data['baseline'].tobytes()),actors=[5,6,11,12,21,22],queries=48,
            no_replacements=True,no_test_normalizer_fit=True,selection_lock_sha256=sha(frozen)))
        phase='ORIGINAL_MODEL_INITIALIZATION'
        adapter=model_module.Adapter(prepared/f'parent{seed}',manifest,ledger)
        result['initialization_and_input_cost']=dict(cpu_seconds=time.process_time(),
            wall_seconds=time.monotonic()-COLD_START,initialization_qvi_included=True,complete_model_calls=0)
        write(output/'RUN_IDENTITY.json',dict(versions=versions,python=sys.version,seed=seed,
            original_parent_sha256=manifest['checkpoint']['sha256'],profile=adapter.profile,
            loaded_sources=adapter.loaded_sources,selection_sha256=sha(frozen),device='cpu',numerical_threads=1))
        for item in selected['unique_evaluations']:
            phase='EVALUATE_'+item['name']
            start,cpu=time.monotonic(),time.process_time()
            if item['name']=='KEEP':
                adapter.set_theta(adapter.parent)
                if sha((prepared/f'parent{seed}/parent.pt').read_bytes())!=item['checkpoint_sha256']:
                    raise ValueError('exact KEEP bytes changed')
                norm2=support.exact_norm2(adapter.parent,adapter.parent)
            else:
                values=(prepared/f'parent{seed}'/(item['name']+'.f32le')).read_bytes()
                if len(values)!=160 or sha(values)!=item['parameter_sha256']:
                    raise ValueError('selected40 actual F32 bytes differ')
                theta=np.frombuffer(values,dtype='<f4').copy()
                norm2=support.exact_norm2(theta,adapter.parent)
                if norm2>1:
                    raise ValueError('original radius gate violated')
                adapter.load_candidate(prepared/f'parent{seed}'/(item['name']+'.pt'),item['checkpoint_sha256'],theta)
            actual_theta=adapter.theta().copy()
            scores,_,diagnostics=adapter.run(data,f'{item["name"]}_LOCKED_HISTORICAL_TEST48',
                                            gradient=False,compile_trace=False)
            values=scores.detach().numpy().copy()
            result['forwards_returned']+=1
            aggregate=support.metrics(values,data['y'])
            per_query=per_query_metrics(values,data['y'])
            if any(float(per_query[key].mean())!=aggregate[key] for key in ('accuracy','brier','ce')):
                raise ValueError('per-query and original aggregate metric recipe disagree')
            archive=output/(item['name']+'.test.npz')
            np.savez_compressed(archive,scores=values,y=data['y'],groups=data['groups'],
                query_id=data['query_id'],gallery_id=data['gallery_id'],
                accuracy=per_query['accuracy'],brier=per_query['brier'],ce=per_query['ce'])
            adapter.set_theta(adapter.parent)
            row=dict(name=item['name'],status='EVALUATED',checkpoint_sha256=item['checkpoint_sha256'],
                actual_sender_f32_sha256=sha(actual_theta.tobytes()),raw_output_sha256=sha(archive.read_bytes()),
                raw_output_bytes=archive.stat().st_size,metrics=aggregate,
                norm2_numerator=str(norm2.numerator),norm2_denominator=str(norm2.denominator),
                complete_physical_diagnostics=diagnostics,
                cost=dict(cpu_seconds=time.process_time()-cpu,wall_seconds=time.monotonic()-start,
                          forwards=1,body_ticks=6,paired_queries=48,checkpoint_reload_and_serialization_included=True))
            write(output/(item['name']+'.test.json'),row)
            result['cases'].append(row)
            ledger.event('case_persisted',name=item['name'],raw_output_sha256=row['raw_output_sha256'])
        ledger.check_time()
        if ledger.counts!=caps or result['forwards_returned']!=caps['forwards']:
            raise ValueError('actual final case ledger differs from sealed unique-checkpoint plan')
        result['status']='PARENT_TEST_AUDIT_COMPLETED'
    except BaseException as error:
        failure=error
        result.update(status='PARENT_TEST_AUDIT_ABORTED',failed_phase=phase,error=repr(error),
            retry_permitted=False,remaining_cases_not_evaluated=True,no_test_based_fallback=True)
        if ledger is not None:
            ledger.event('audit_failed',phase=phase,failure_type=type(error).__name__)
    finally:
        errors=[]
        if adapter is not None:
            try:
                adapter.set_theta(adapter.parent)
                result['in_memory_parent_restored']=adapter.theta().tobytes()==adapter.parent.tobytes()
            except BaseException as error:
                errors.append('parent restoration '+repr(error))
        try:
            source_check(binding,HERE,helper,transfer)
            prepared_check(prepared,binding_raw)
        except BaseException as error:
            errors.append('source/input readback '+repr(error))
        if errors:
            result.update(status='PARENT_TEST_AUDIT_ABORTED',integrity_errors=errors)
            failure=failure or ValueError('post-evaluation source/input integrity failed')
        result.update(counts=None if ledger is None else dict(ledger.counts),
            cpu_seconds=time.process_time(),active_wall_seconds=time.monotonic()-COLD_START,
            counter_semantics='Started complete-rollout operations; returned valid forwards separately. Interrupted work is not zero.',
            no_new_epoch_dose_parent_selection=True)
        write(output/'RESULT.json',result)
    if failure is not None:
        raise failure


if __name__=='__main__':
    main()
