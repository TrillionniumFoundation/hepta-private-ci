"""One fixed descriptive audit of returned scores; never select or call a model."""
import json
from pathlib import Path
import numpy as np
from actor_intervals import summarize_contrasts
from audit_support import ACTORS, SEEDS, checked, sha, write
from test_data import per_query_metrics


def collect(output,prepared,selection,parent_status):
    cases={}
    reference=None
    rows=[]
    for selected in selection['parents']:
        seed=selected['seed']
        final=output/f'parent{seed}/RESULT.json'
        if not final.is_file():
            rows.append(dict(seed=seed,status='NO_FINAL_RESULT',methods=selected['methods']))
            continue
        result=json.loads(final.read_text())
        if result.get('integrity_errors'):
            rows.append(dict(seed=seed,status='SOURCE_OR_INPUT_INTEGRITY_FAILED',methods=selected['methods']))
            continue
        admitted={item['name']:item for item in selected['unique_evaluations']}
        for item in result['cases']:
            if item['name'] not in admitted or item['checkpoint_sha256']!=admitted[item['name']]['checkpoint_sha256']:
                raise ValueError('unexpected final case outside locked selected identities')
            path=final.parent/(item['name']+'.test.npz')
            raw=checked(path.read_bytes(),dict(bytes=item['raw_output_bytes'],sha256=item['raw_output_sha256']))
            with np.load(path,allow_pickle=False) as archive:
                arrays={key:archive[key].copy() for key in archive.files}
            if set(arrays)!={'scores','y','groups','query_id','gallery_id','accuracy','brier','ce'}:
                raise ValueError('raw historical audit score fields differ')
            identity={key:arrays[key] for key in ('y','groups','query_id','gallery_id')}
            if reference is None:
                reference={key:value.copy() for key,value in identity.items()}
            elif any(not np.array_equal(reference[key],value) for key,value in identity.items()):
                raise ValueError('same actor/query set is not paired identically across parents')
            actual=per_query_metrics(arrays['scores'],arrays['y'])
            if any(not np.array_equal(actual[key],arrays[key]) or
                   float(actual[key].mean())!=item['metrics'][key] for key in actual):
                raise ValueError('stored raw-score metrics disagree with original F64 recipe')
            if (int(actual['accuracy'].sum())!=item['metrics']['correct'] or item['metrics']['n']!=48 or
                    any(int((arrays['groups']==f'ravdess-actor-{actor:02d}').sum())!=8 for actor in ACTORS)):
                raise ValueError('actual final query/group/count coverage differs')
            cases[(seed,item['name'])]=arrays
        role_rows={}
        for role in ('KEEP','METHOD','BP'):
            choice={'selected':'KEEP','status':'SELECTED_BEFORE_TEST'} if role=='KEEP' else selected['methods'][role]
            name=choice.get('reused_evaluation_name',choice.get('selected'))
            found=next((item for item in result['cases'] if item['name']==name),None)
            role_rows[role]=dict(original_selection=choice,status='EVALUATED' if (seed,name) in cases else 'UNAVAILABLE',
                reused_case=name,metrics=None if found is None else found['metrics'],
                extra_model_calls_for_reuse=0)
        rows.append(dict(seed=seed,family=selected['family'],status=result['status'],roles=role_rows,
            original_source_slots=selected['slot_results'],current_test_output_not_used_for_reselection=True))

    selected_by_seed={row['seed']:row for row in selection['parents']}
    specifications=[]
    for seed in SEEDS:
        family='sender_role' if seed==47 else 'boundary'
        for lhs,rhs in (('METHOD','KEEP'),('BP','KEEP'),('METHOD','BP')):
            specifications.append((f'seed{seed}_{lhs}_minus_{rhs}',family,[seed],lhs,rhs))
    for lhs,rhs in (('METHOD','KEEP'),('BP','KEEP'),('METHOD','BP')):
        specifications.append((f'boundary83_137_{lhs}_minus_{rhs}','boundary',[83,137],lhs,rhs))
    specifications.append(('bp47_83_137_BP_minus_KEEP','bp',[47,83,137],'BP','KEEP'))
    if len(specifications)!=13:
        raise ValueError('fixed comparison inventory differs')

    def name_for(seed,role):
        if role=='KEEP':
            return 'KEEP'
        choice=selected_by_seed[seed]['methods'][role]
        if choice['status']!='SELECTED_BEFORE_TEST':
            return None
        return choice.get('reused_evaluation_name',choice['selected'])

    contrasts=[]
    for identifier,family,seeds,lhs,rhs in specifications:
        missing=[]
        pairs={}
        for seed in seeds:
            left,right=name_for(seed,lhs),name_for(seed,rhs)
            if (seed,left) not in cases or (seed,right) not in cases:
                missing.append(dict(seed=seed,lhs=left,rhs=right))
            else:
                pairs[seed]=(cases[(seed,left)],cases[(seed,right)])
        row=dict(id=identifier,family=family,parent_seeds=seeds,status='UNAVAILABLE' if missing else 'COMPLETE',
                 actor_rows=[])
        if missing:
            row['unavailable_reason']='Fixed selected score cases unavailable: '+json.dumps(missing,sort_keys=True)
        else:
            for actor in ACTORS:
                per_parent=[]
                for seed in seeds:
                    left,right=pairs[seed]
                    mask=left['groups']==f'ravdess-actor-{actor:02d}'
                    if int(mask.sum())!=8:
                        raise ValueError('actor comparison lacks original8 queries')
                    per_parent.append(dict(seed=seed,n=8,**{metric+'_delta':float((left[metric][mask]-right[metric][mask]).mean())
                        for metric in ('accuracy','brier','ce')}))
                row['actor_rows'].append(dict(actor=actor,per_parent=per_parent))
        contrasts.append(row)
    write(output/'PAIRED_ACTOR_INPUTS.json',dict(contrasts=contrasts,parent_role_rows=rows,
        selection_sha256=sha((prepared/'SELECTED_MODELS.json').read_bytes()),
        method_labels_are_frozen_policies_with_keep_fallback=True,successful_direct_edits_not_implied=True))
    result=summarize_contrasts(contrasts)
    result.update(selection_sha256=sha((prepared/'SELECTED_MODELS.json').read_bytes()),
        paired_actor_input_sha256=sha((output/'PAIRED_ACTOR_INPUTS.json').read_bytes()),
        method_labels_are_frozen_policies_with_keep_fallback=True,
        source47_sender_role_not_pooled_with_boundary_family=True,
        new_test_based_selections=0,model_calls=0,source_parent_sequence_status=parent_status)
    write(output/'EXPLORATORY_STATISTICS.json',result)
    return dict(statistics_sha256=sha((output/'EXPLORATORY_STATISTICS.json').read_bytes()),
        contrasts=13,complete_contrasts=sum(row['status']=='COMPLETE' for row in contrasts),
        raw_unique_case_count=len(cases),new_model_calls=0,raw_parent_role_rows=rows)
