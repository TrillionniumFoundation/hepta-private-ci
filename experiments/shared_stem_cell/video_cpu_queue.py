"""Source-disjoint arrival-aware CPU batching with physical PNG/Conv2d/GRU work.

Single-process FIFO arrival replay, NOT a concurrent HTTP server. A request is
considered released at its fixed relative-arrival timestamp, independent of how
long earlier batches take. All waiting, preprocessing, hidden-state updates and
file bytes belong to the measured execution; input files are staged beforehand.
Frozen RANDOM Conv2d proxy is NOT pretrained CLIP; no production authority.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import statistics
import time

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import video_cpu_proxy as cpu
from experiments.shared_stem_cell import video_cpu_tune as tune
from experiments.shared_stem_cell import video_temporal as temporal
from experiments.shared_stem_cell import video_batch as batch

# Max group size, admission-wait budget (nanoseconds). Fixed BEFORE evidence.
POLICIES = ((1, 0), (2, 0), (4, 0), (4, 2_000_000), (4, 8_000_000))
WORKLOADS = (("paired", 8, 2, 0), ("paired", 8, 8, 0),
             ("paired", 8, 2, 4_000_000), ("paired", 8, 8, 4_000_000),
             ("paired", 16, 2, 12_000_000), ("paired", 16, 8, 12_000_000))
FIRST_RESPONSE_FACTOR = 1.5
MIN_P95_IMPROVEMENT = .05

def key(workload):
    return ':'.join(str(x) for x in workload)


def policy_key(policy):
    return f"{policy[0]}:{policy[1]}"


def percentile(values, percentage):
    if not isinstance(values, list) or not values or not 0 < percentage <= 100:
        raise e.InputError("bounded nonempty latency sample required")
    if any(type(x) is not int or x < 0 for x in values):
        raise e.InputError("nonnegative exact latency required")
    values = sorted(values)
    return values[(percentage * len(values) + 99) // 100 - 1]


def summary(records):
    if not records:
        raise e.InputError("completed measurements required")
    vals = [int(x) for x in records]
    return {"median_ns": int(statistics.median(vals)),
            "p95_ns": percentile(vals, 95), "p99_ns": percentile(vals, 99),
            "samples_ns": vals, "not_population_certified": True}


def choose(data):
    """Calibration-only p95 improvement, guard first response and batch tail.

    No improvement meeting BOTH guards returns the scalar FIFO policy.
    """
    options = [policy_key(p) for p in POLICIES]
    if set(data) != set(options):
        raise e.InputError("fixed five-policy complete calibration grid required")
    for item in data.values():
        if not isinstance(item, list) or not 2 <= len(item) <= 9:
            raise e.InputError("two or more calibration rounds required")
        if any(not isinstance(x, dict) or set(x) != {"first_response_ns", "latency_p95_ns", "end_to_end_wall_ns"}
               or any(type(x[y]) is not int or x[y] <= 0 for y in x) for x in item):
            raise e.InputError("valid calibration time measurements required")
    metrics = {option: {k: int(statistics.median([run[k] for run in data[option]]))
                        for k in data[option][0]} for option in options}
    base = metrics[options[0]]
    qualified=[]
    for option in options[1:]:
        candidate=metrics[option]
        if (candidate["latency_p95_ns"] <= (1-MIN_P95_IMPROVEMENT)*base["latency_p95_ns"]
                and candidate["first_response_ns"] <= FIRST_RESPONSE_FACTOR*base["first_response_ns"]
                and candidate["end_to_end_wall_ns"] <= 1.1*base["end_to_end_wall_ns"]):
            qualified.append(option)
    selected = min(qualified, key=lambda option: (metrics[option]["latency_p95_ns"],
                              metrics[option]["first_response_ns"], options.index(option))) if qualified else options[0]
    return {"policy_key": selected, "batch_size": int(selected.split(':')[0]),
            "max_wait_ns": int(selected.split(':')[1]), "calibration_metrics": metrics,
            "qualified_non_scalar": qualified,"first_response_guard_factor":FIRST_RESPONSE_FACTOR,
            "minimum_p95_improvement":MIN_P95_IMPROVEMENT,
            "fallback_scalar_if_no_guarded_improvement": True,
            "holdout_labels_used": False, "pretrained_clip_success": False,
            "production_accepted": False}


@torch.no_grad()
def compute_group(model, towers, cases, root, depth):
    """Shared physical frame cache across dispatch groups; independent Reader states."""
    if not isinstance(cases, list) or not 1 <= len(cases) <= 4 or depth not in (2, 8):
        raise e.InputError("bounded exact-depth group required")
    state=torch.zeros(len(cases),model.core.hidden_size,dtype=torch.float32)
    calls=[]
    for frame_end in range(2,depth+1,2):
        requested=[f for c in cases for f in c.inputs['video'][frame_end-2:frame_end]]
        unique_before=len(towers.cache)
        physical_before=towers.physical_video_calls
        features,stamps=towers.encode('video',requested,root)
        expected=torch.tensor([f['timestamp_us'] for f in requested],dtype=torch.long)
        if (not isinstance(features,torch.Tensor) or features.dtype!=torch.float32
                or features.device.type!='cpu' or features.shape!=(len(cases)*2,model.project.in_features)
                or not bool(torch.isfinite(features).all())
                or not isinstance(stamps,torch.Tensor) or stamps.dtype!=torch.long
                or not torch.equal(stamps,expected)):
            raise e.InputError('physical frame tensor/time identity drift')
        for j in (0,1):
            z=torch.tanh(model.project(features[j::2].detach()))
            state=model.core(z,state)
        calls.append({"frame_end":frame_end,"requested_sha256":[f['sha256'] for f in requested],
            "unique_new_frames":len(towers.cache)-unique_before,
            "physical_forward_calls":towers.physical_video_calls-physical_before})
    probs=model.readout(state).softmax(-1).float()
    temporal.score(probs,torch.zeros(len(cases),dtype=torch.long))
    return probs.tolist(),calls


def _sleep_until(instant_ns):
    delta = instant_ns-time.perf_counter_ns()
    if delta>0:
        time.sleep(delta/1e9)


def execute_once(root, network, reader, cases, depth, gap_ns, policy):
    """Actually wait for scheduled releases, then dispatch ready FIFO requests.

    Nonpreemptive service. A release occurring during another group's compute is
    queued, not lost. Cache/Reader are shared for the WHOLE run, not reset per group.
    """
    if (not isinstance(cases,list) or not 1<=len(cases)<=16 or depth not in (2,8)
            or type(gap_ns) is not int or gap_ns not in (0,4_000_000,12_000_000)
            or policy not in POLICIES):
        raise e.InputError('fixed bounded arrival workload/policy required')
    batch.validate_cases(cases)
    if (reader.training or network.training or any(p.requires_grad for p in reader.parameters())
            or any(p.requires_grad for p in network.parameters())):
        raise e.InputError('frozen Reader and proxy required')
    base=cpu.PixelTower(network)
    towers=temporal.FrameCacheTowers(base)
    cap,wait_ns=policy
    started=time.perf_counter_ns()
    positions=[i*gap_ns for i in range(len(cases))]
    groups, records, completed = [], [], {}
    next_index=0
    while next_index<len(cases):
        _sleep_until(started+positions[next_index])
        first_release_ns=started+positions[next_index]
        # First pending Cell's deadline cannot be reset by late service.
        latest=min(len(cases)-1,next_index+cap-1)
        deadline_ns=first_release_ns+wait_ns
        if latest>next_index and started+positions[latest] <= deadline_ns:
            _sleep_until(started+positions[latest])
        elif latest>next_index:
            _sleep_until(deadline_ns)
        dispatch=time.perf_counter_ns()
        remaining=len(cases)-next_index
        ready=sum(started+positions[i] <= dispatch for i in range(next_index,len(cases)))
        count=min(cap,ready,remaining)
        if count<1:
            raise e.InputError('scheduler dispatched before first release')
        members=cases[next_index:next_index+count]
        with e.measured() as timing:
            probabilities,frame_events=compute_group(reader,towers,members,root,depth)
        done=time.perf_counter_ns()
        if done < dispatch:
            raise e.InputError('invalid completion clock')
        ids=[c.case_id for c in members]
        group={"group_id":len(groups),"case_ids":ids,"policy_key":policy_key(policy),
            "dispatch_offset_ns":dispatch-started,"completion_offset_ns":done-started,
            "service_wall_ns":timing['wall_ns'],"first_release_offset_ns":positions[next_index],
            "admission_deadline_offset_ns":positions[next_index]+wait_ns,
            "frame_events":frame_events}
        groups.append(group)
        for c,p,index in zip(members,probabilities,range(next_index,next_index+count)):
            if c.case_id in completed:
                raise e.InputError('duplicate scheduled Cell completion')
            latency=done-(started+positions[index])
            if latency<0:
                raise e.InputError('completed before arrival')
            completed[c.case_id]=done-started
            records.append({"case_id":c.case_id,"source_id":c.group,"depth":depth,
                "input_digest":c.input_digest,"scheduled_arrival_offset_ns":positions[index],
                "dispatch_offset_ns":dispatch-started,"completion_offset_ns":done-started,
                "response_latency_ns":latency,"group_id":len(groups)-1,
                "prediction":int(p[1]>p[0]),"probabilities":p})
        next_index+=count
    end=time.perf_counter_ns()
    arrival_lag=[r['dispatch_offset_ns']-r['scheduled_arrival_offset_ns'] for r in records]
    latencies=[r['response_latency_ns'] for r in records]
    if (len(records)!=len(cases) or towers.physical_video_calls!=base.calls['clip']
            or len(towers.cache)!=base.encoded_frames
            or sum(base.forward_batch_sizes)!=base.encoded_frames):
        raise e.InputError('request/physical-tower accounting mismatch')
    return {"case_ids":[c.case_id for c in cases],"arrival_offsets_ns":positions,
        "policy_key":policy_key(policy),"depth":depth,"gap_ns":gap_ns,
        "groups":groups,"records":records,"whole_run_wall_ns":end-started,
        "first_response_ns":min(r['completion_offset_ns'] for r in records),
        "latency_p50_ns":percentile(latencies,50),
        "latency_p95_ns":percentile(latencies,95),
        "latency_p99_ns":percentile(latencies,99),
        "max_dispatch_lag_ns":max(arrival_lag),
        "conv_forward_ns":base.conv_forward_ns,"preprocess_ns":base.preprocess_ns,
        "source_bytes":base.loaded_bytes,"physical_forward_calls":base.calls['clip'],
        "unique_frames":base.encoded_frames,"requested_frame_rows":len(cases)*depth,
        "conv_batch_sizes":base.forward_batch_sizes,
        "rss_endpoints_only":True,"energy_joules":None,"pretrained_clip_executed":False}


def _comparable(original,candidate):
    if [r['case_id'] for r in original['records']] != [r['case_id'] for r in candidate['records']]:
        raise e.InputError('different scheduled Cell identities')
    if original['arrival_offsets_ns']!=candidate['arrival_offsets_ns']:
        raise e.InputError('unequal request arrivals')
    for a,b in zip(original['records'],candidate['records']):
        if a['prediction']!=b['prediction'] or max(abs(x-y) for x,y in zip(a['probabilities'],b['probabilities']))>2e-5:
            raise e.InputError('batch capacity changed fixed Reader prediction')


def run(root,output,*,workloads=WORKLOADS,calibration_rounds=3,evaluation_rounds=5,warmups=0):
    root,output=Path(root),Path(output)
    if (type(workloads) is not tuple or not 1<=len(workloads)<=len(WORKLOADS)
            or len(set(workloads))!=len(workloads) or any(x not in WORKLOADS for x in workloads)
            or type(calibration_rounds) is not int or not 2<=calibration_rounds<=7
            or type(evaluation_rounds) is not int or not 2<=evaluation_rounds<=7
            or type(warmups) is not int or warmups!=0):
        raise e.InputError('declared source-separated queue experiment required')
    if torch.get_num_threads()!=1:
        raise e.InputError('single CPU thread required')
    output.mkdir(parents=True,exist_ok=False)
    experiment_started=time.perf_counter_ns()
    manifest_raw=(root/'manifest.json').read_bytes()
    manifest=e.decode(manifest_raw)
    network=cpu.FrozenPixelConv()
    frozen=e.parameters(network)
    proto_sha=e.write_once(output/'protocol.json',{
        "schema":"hepta.video-arrival-aware-cpu-protocol.v1",
        "source_sha256":e.sha(Path(__file__).read_bytes()),
        "manifest_sha256":e.sha(manifest_raw),"frozen_network_sha256":frozen['sha256'],
        "workloads":workloads,"policies":POLICIES,
        "calibration_rounds":calibration_rounds,"evaluation_rounds":evaluation_rounds,
        "warmups":warmups,"first_response_guard_factor":FIRST_RESPONSE_FACTOR,
        "minimum_p95_improvement":MIN_P95_IMPROVEMENT,
        "zero_or_explicit_arrivals_not_live_network_traffic":True,
        "single_process_serial_worker":True,"random_frozen_conv_not_clip":True,
        "allow_external_actions":False,"production_accepted":False})
    try:
        all_cases,folds,labels,sources=tune.split_sources(root,manifest)
        with e.measured() as training_elapsed:
            reader, training=cpu.train_reader(root,manifest,network,all_cases)
        before=e.parameters(reader)
        e.write_once(output/'training.json',{
            "training_reader":before,"frozen_network":frozen,
            "source_groups":sources,"training_wall_ns":training_elapsed['wall_ns'],
            "training_work":training,"reader_training_only_from_train_sources":True})
        cal_runs,evaluations,selected,prediction_records={}, {}, {}, {}
        all_arm_calls=0;all_arm_frames=0;all_arm_conv_ns=0;all_arm_preprocess_ns=0
        all_arm_source_bytes=0;all_arm_wall_ns=0;all_arm_runs=0
        warmup_wall=0;warmup_calls=0;warmup_frames=0
        orders=(POLICIES,tuple(reversed(POLICIES)),POLICIES[2:]+POLICIES[:2])
        def test_fold(fold,rows,rounds,work):
            nonlocal all_arm_calls,all_arm_frames,all_arm_conv_ns,all_arm_preprocess_ns
            nonlocal all_arm_source_bytes,all_arm_wall_ns,all_arm_runs
            nonlocal warmup_wall,warmup_calls,warmup_frames
            r={policy_key(p):[] for p in POLICIES}
            reference=None
            profile,n,depth,gap=work
            for it in range(-warmups,rounds):
                for position,policy in enumerate(orders[it%len(orders)]):
                    x=execute_once(root,network,reader,rows,depth,gap,policy)
                    all_arm_runs+=1
                    if (e.parameters(network)!=frozen or e.parameters(reader)!=before):
                        raise e.InputError('model weights changed while calibrating batch wait')
                    if reference is None:reference=x
                    else:_comparable(reference,x)
                    x.update({'fold':fold,'workload':key(work),'iteration':it,
                              'order_position':position,'batch_size':policy[0],
                              'max_wait_ns':policy[1]})
                    if it<0:
                        warmup_wall+=x['whole_run_wall_ns'];warmup_calls+=x['physical_forward_calls'];warmup_frames+=x['unique_frames']
                    else:
                        all_arm_wall_ns+=x['whole_run_wall_ns']
                        all_arm_calls+=x['physical_forward_calls']
                        all_arm_frames+=x['unique_frames']
                        all_arm_conv_ns+=x['conv_forward_ns'];all_arm_preprocess_ns+=x['preprocess_ns']
                        all_arm_source_bytes+=x['source_bytes']
                        r[policy_key(policy)].append(x)
            return r,reference
        for profile,n,depth,gap in workloads:
            name=key((profile,n,depth,gap))
            cal=folds['calibration'][profile][:n]
            if len(cal)!=n:raise e.InputError('incomplete source-disjoint calibration requests')
            cal_runs[name],_=test_fold('calibration',cal,calibration_rounds,(profile,n,depth,gap))
            selected[name]=choose({p:[{'first_response_ns':x['first_response_ns'],
                'latency_p95_ns':x['latency_p95_ns'],'end_to_end_wall_ns':x['whole_run_wall_ns']}
                              for x in runs] for p,runs in cal_runs[name].items()})
        cal_sha=e.write_once(output/'calibration.json',{
            'source_groups':sources['calibration'],'measurements':cal_runs,'workloads':workloads})
        selection_sha=e.write_once(output/'selection.json',{
            'schema':'hepta.video-arrival-aware-batch-choice.v1',
            'protocol_sha256':proto_sha,'calibration_sha256':cal_sha,
            'reader_sha256':before['sha256'],'by_workload':selected,
            'source_groups':sources,'holdout_labels_used':False,
            'production_accepted':False})
        read_selection=e.decode(e.bound_file(output/'selection.json',selection_sha))['by_workload']
        for profile,n,depth,gap in workloads:
            name=key((profile,n,depth,gap))
            holdout=folds['holdout'][profile][:n]
            if len(holdout)!=n:raise e.InputError('incomplete source-disjoint holdout requests')
            evaluations[name],reference=test_fold('holdout',holdout,evaluation_rounds,(profile,n,depth,gap))
            prediction_records[name]={'case_ids':[x.case_id for x in holdout],
                'predictions':[r['probabilities'] for r in reference['records']],
                'selected_policy_key':read_selection[name]['policy_key']}
        pred_sha=e.write_once(output/'holdout-predictions.json',{
            'selection_sha256':selection_sha,'records':prediction_records,
            'before_holdout_label_score':True})
        eval_sha=e.write_once(output/'evaluation.json',{
            'selection_sha256':selection_sha,'holdout_prediction_sha256':pred_sha,
            'source_groups':sources['holdout'],'measurements':evaluations,
            'workloads':workloads})
        scoring={};summaries={}
        for profile,n,depth,gap in workloads:
            name=key((profile,n,depth,gap));cases=folds['holdout'][profile][:n]
            probs=prediction_records[name]['predictions']
            correct=sum(int(max(range(2),key=lambda j:row[j])==labels[c.case_id]) for row,c in zip(probs,cases))
            nll=sum(-math.log(max(1e-12,row[labels[c.case_id]])) for row,c in zip(probs,cases))/len(cases)
            scoring[name]={'correct':correct,'total':len(cases),'nll':nll,'not_semantic_CLIP':True}
            options={pk:{'p95_response_median_ns':int(statistics.median([x['latency_p95_ns'] for x in runs])),
                'first_response_median_ns':int(statistics.median([x['first_response_ns'] for x in runs])),
                'whole_run_wall_median_ns':int(statistics.median([x['whole_run_wall_ns'] for x in runs])),
                'physical_calls_per_run':[x['physical_forward_calls'] for x in runs]}
                     for pk,runs in evaluations[name].items()}
            s=read_selection[name]['policy_key']
            summaries[name]={'selected_policy_key':s,'scalars':options['1:0'],'by_policy':options,
                'selected_vs_scalar_p95_ratio':options['1:0']['p95_response_median_ns']/options[s]['p95_response_median_ns'],
                'selected_vs_scalar_full_wall_ratio':options['1:0']['whole_run_wall_median_ns']/options[s]['whole_run_wall_median_ns'],
                'selected_is_faster_p95':options[s]['p95_response_median_ns']<options['1:0']['p95_response_median_ns']}
        report={'schema':'hepta.video-arrival-aware-cpu-executed.v1',
            'protocol_sha256':proto_sha,'manifest_sha256':e.sha(manifest_raw),
            'calibration_sha256':cal_sha,'selection_sha256':selection_sha,
            'evaluation_sha256':eval_sha,'holdout_predictions_sha256':pred_sha,
            'reader_sha256':before['sha256'],'frozen_network_sha256':frozen['sha256'],
            'source_groups':sources,'holdout_scores':scoring,'summaries':summaries,
            'all_measured_arm_calls':all_arm_calls,'all_measured_arm_unique_frames':all_arm_frames,
            'all_measured_arm_conv_ns':all_arm_conv_ns,'all_measured_arm_preprocess_ns':all_arm_preprocess_ns,
            'all_measured_arm_source_bytes':all_arm_source_bytes,
            'all_measured_arm_wall_ns':all_arm_wall_ns,
            'warmup_wall_ns':warmup_wall,'warmup_calls':warmup_calls,'warmup_frames':warmup_frames,
            'all_arm_execution_count_including_warmups':all_arm_runs,
            'all_arm_calls_plus_training_and_warmups':all_arm_calls+warmup_calls+training['training_physical_tower_calls'],
            'whole_study_wall_ns':time.perf_counter_ns()-experiment_started,
            'all_reference_policies_physically_executed_and_charged':True,
            'virtual_release_times_wall_clock_replayed_not_real_concurrency':True,
            'queue_wait_and_idle_time_included_in_wall':True,
            'staged_media_preparation_not_included_in_inference':True,
            'pretrained_clip_executed':False,'independent_future_population_quality':False,
            'energy_joules':None,'production_accepted':False}
        e.write_once(output/'report.json',report)
        return report
    except Exception as exc:
        e.write_once(output/'failure.json',{'error':type(exc).__name__,
                                            'message':str(exc),'production_accepted':False})
        raise

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--calibration-rounds',type=int,default=3)
    parser.add_argument('--evaluation-rounds',type=int,default=5)
    parser.add_argument('--warmups',type=int,default=0)
    args=parser.parse_args()
    torch.set_num_threads(1)
    run(args.root,args.output,calibration_rounds=args.calibration_rounds,
        evaluation_rounds=args.evaluation_rounds,warmups=args.warmups)
