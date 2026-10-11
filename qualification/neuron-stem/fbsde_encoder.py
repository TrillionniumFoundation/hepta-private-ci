"""Actual shared mmBERT: small Head/recurrent/stop/finite-BSDE/cheap exact controls.

The tree method is the registered f=0 finite-state BSDE on a factorized learned
belief model; it is NOT a trained fully coupled continuous FBSDE. The read-once
polynomial comparator receives the SAME predicted leaf probabilities, not gold.
A shared two-sentence decoder is evaluated after decoding, not open-ended NLG.
"""
import argparse
from collections import defaultdict
import math
from pathlib import Path
import random
import resource
import subprocess
import sys
import time

from four_gate_common import digest, require, sha, write_once
from four_gate_capture import tensor_digest
from fbsde_encoder_cases import (INTENTS, DEPTHS, partition_utterances, cases, formula_vector,
                                  decode_probability, score_decoded, checked_probability)
from fbsde_tree import belief_bsde, polynomial_probability
from fbsde_design import (LEGACY, INDEPENDENT, COMPOSITION, PROFILES, independent_cases, label_cases,
                         source_census, stratified_metrics)

from fbsde_composition import make_cell, compile_batch, evaluate as evaluate_composition


def models(torch):
    nn = torch.nn
    class Group(nn.Module):
        def __init__(self, recurrent):
            super().__init__()
            self.feature = nn.Linear(389, 16)
            self.gate = nn.Linear(389, 16)
            self.recurrent = recurrent
            width = 4*16+105+4
            self.cell = nn.GRUCell(width, 32) if recurrent else nn.Linear(width, 32)
            self.out = nn.Linear(32, 1)
        def forward(self, x, syntax, depth=1):
            f = self.feature(x).tanh()*self.gate(x).sigmoid()
            inputs = torch.cat((f.flatten(1), syntax), -1)
            h = inputs.new_zeros((len(inputs), 32))
            for _ in range(depth if self.recurrent else 1):
                h = self.cell(inputs, h) if self.recurrent else self.cell(inputs).tanh()
            return self.out(h).squeeze(-1)
    return nn.Linear(384, 4), Group(False), Group(True)


def tensors(torch, public, features):
    # Public inputs only: no labels, scores, utility, oracle intent or future outcomes.
    xs, syntax = [], []
    for row in public:
        require(set(row) == {'case_id','utterance_ids','target_intents','formula'}, 'unregistered model input')
        x = torch.zeros(4, 389)
        mask = [0.]*4
        for i, (uid, target) in enumerate(zip(row['utterance_ids'], row['target_intents'])):
            x[i, :384] = features[uid]
            x[i, 384+target] = 1.
            mask[i] = 1.
        xs.append(x); syntax.append(formula_vector(row['formula'])+mask)
    return torch.stack(xs), torch.tensor(syntax)


def state_digest(model):
    return digest({name: tensor_digest(t) for name,t in model.state_dict().items()})


def train_and_compare(torch, partitions, features, output, seed=104729, *, profile=LEGACY):
    """Called with real frozen features by run(); synthetic callers are tests only."""
    study_start_cpu = time.process_time_ns()
    require(profile in PROFILES, "unknown question profile")
    nn = torch.nn
    counts = {'train': 640, 'validation': 128, 'calibration': 128, 'test': 192}
    public, truths = {}, {}
    for j, split in enumerate(counts):
        if profile == LEGACY:
            public[split], truths[split] = cases(partitions[split], split, counts[split], seed+j)
        else:
            public[split] = independent_cases([{'id':r['id']} for r in partitions[split]],
                                               split, counts[split], seed+j)
            truths[split] = label_cases(public[split], partitions[split])
    # This is a prospective-in-process design, not an independent preregistration.
    write_once(output/'design.json', {'schema':'hepta.fbsde.encoder-study.design.v1', 'seed':seed,
        'case_counts':counts, 'public_input_digests':{k:digest(v) for k,v in public.items()},
        'intents':INTENTS, 'depth_grid':DEPTHS, 'fit_steps':96, 'fit_cpu_ceiling_ns':15_000_000_000,
        'per_prediction_cpu_ceiling_ns':100_000_000, 'common_caps_not_equal_actual_work':True,
        'task_kind':'generated_read_once_formulas_over_human_labelled_utterances',
        'decoder':'fixed_shared_two_sentence_grammar', 'real_future_windows':False,
        'question_profile':profile, 'target_generation_reads_labels':profile == LEGACY,
        'composition_trainable_parameters':8 if profile == COMPOSITION else None,
        'truth_and_predictor_same_process_not_authenticated':True})
    write_once(output/'public-cases.json', public)
    xy = {k:tensors(torch,v,features) for k,v in public.items()}
    train_y = torch.tensor([float(truths['train'][r['case_id']]) for r in public['train']])
    torch.manual_seed(seed)
    semantic, head, recurrent = models(torch)
    leaf_x = torch.stack([features[r['id']] for r in partitions['train']])
    leaf_y = torch.tensor([r['intent'] for r in partitions['train']])
    jobs = []
    def fit(name, model, loss_fn, *, project=None):
        optimizer = torch.optim.AdamW(model.parameters(), lr=.003)
        cpu, wall = time.process_time_ns(), time.perf_counter_ns()
        for step in range(96):
            optimizer.zero_grad(); loss=loss_fn(step)
            require(torch.isfinite(loss).item(), 'nonfinite training loss')
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(),1.)
            optimizer.step()
            if project is not None: project()
            require(time.process_time_ns()-cpu <= 15_000_000_000, 'training CPU budget exhausted')
        model.eval().requires_grad_(False)
        jobs.append({'job_id':name, 'phase':'training', 'steps':96,
                     'cpu_ns':time.process_time_ns()-cpu, 'wall_ns':time.perf_counter_ns()-wall,
                     'parameters':sum(p.numel() for p in model.parameters()), 'weights_sha256':state_digest(model)})
    fit('common_semantic',semantic,lambda _:nn.functional.cross_entropy(semantic(leaf_x),leaf_y))
    # Give EVERY root model the same supervised semantic probability, not just
    # the BSDE/exact arms. No architecture gets an extra label-bearing teacher.
    before = time.process_time_ns()
    with torch.inference_mode():
        for split, (xx, _) in xy.items():
            q = semantic(xx[:, :, :384]).softmax(-1)
            xx[:, :, 388] = (q*xx[:, :, 384:388]).sum(-1)
    semantic_annotation_cpu = time.process_time_ns()-before
    fit('light_head',head,lambda _:nn.functional.binary_cross_entropy_with_logits(head(*xy['train']),train_y))
    fit('shared_recurrent',recurrent,lambda step:nn.functional.binary_cross_entropy_with_logits(
        recurrent(*xy['train'],DEPTHS[step%len(DEPTHS)]),train_y))
    composition = None
    if profile == COMPOSITION:
        composition = make_cell(torch)
        groups = compile_batch(torch, public['train'])
        before_fit = composition.corners.detach().tolist()
        initial_loss = float(nn.functional.binary_cross_entropy(
            composition(xy['train'][0][:, :, 388], groups), train_y).item())
        fit('composition_cell', composition, lambda _: nn.functional.binary_cross_entropy(
            composition(xy['train'][0][:, :, 388], groups), train_y), project=composition.project)
        fitted_corners = composition.corners.detach().tolist()
        write_once(output/'composition-corners.json', {'initial':before_fit, 'fitted':fitted_corners,
            'initial_training_bce':initial_loss, 'final_training_bce':float(
                nn.functional.binary_cross_entropy(composition(xy['train'][0][:, :, 388], groups), train_y).item()),
            'weights_sha256':state_digest(composition), 'parameters':8, 'steps':96,
            'corner_dtype':'torch.float32', 'corner_byte_order':sys.byteorder,
            'supervision':'same original training root labels only; no operator truth-table labels',
            'frozen_during_inference':True, 'production_promotion_permitted':False})
    common_semantic_id = state_digest(semantic)
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    validation = []
    with torch.inference_mode():
        for d in DEPTHS:
            ps = recurrent(*xy['validation'],d).sigmoid().tolist()
            brier = sum((p-float(truths['validation'][r['case_id']]))**2
                        for r,p in zip(public['validation'],ps))/len(ps)
            validation.append({'depth':d, 'brier':brier})
    best = min(validation,key=lambda v:(v['brier'],v['depth']))['depth']
    fixed_selection_cost = time.process_time_ns()-cpu
    fixed_selection_wall = time.perf_counter_ns()-wall
    stop_cpu,stop_wall = time.process_time_ns(),time.perf_counter_ns()
    # Simple router confidence thresholds selected on calibration ONLY.
    with torch.inference_mode():
        cache = {d:recurrent(*xy['calibration'],d).sigmoid().tolist() for d in DEPTHS}
    threshold_scores=[]
    for threshold in (.6,.75,.9,.99):
        cost=loss=0.
        for i,r in enumerate(public['calibration']):
            for d in DEPTHS:
                p=cache[d][i]
                if max(p,1-p)>=threshold or d==DEPTHS[-1]:break
            # Cumulative real work must include all earlier attempted depths.
            cost+=sum(t for t in DEPTHS if t<=d)
            loss+=(p-float(truths['calibration'][r['case_id']]))**2
        threshold_scores.append({'threshold':threshold,'objective':loss/len(public['calibration'])+.0005*cost/len(public['calibration'])})
    threshold=min(threshold_scores,key=lambda v:(v['objective'],v['threshold']))['threshold']
    jobs.append({'job_id':'shared_controller_selection','phase':'search','cpu_ns':time.process_time_ns()-cpu,
                 'wall_ns':time.perf_counter_ns()-wall,
                 'fixed_selection_cpu_ns':fixed_selection_cost, 'fixed_selection_wall_ns':fixed_selection_wall,
                 'stop_selection_cpu_ns':time.process_time_ns()-stop_cpu,
                 'stop_selection_wall_ns':time.perf_counter_ns()-stop_wall})
    write_once(output/'selection.json', {'validation':validation,'selected_depth':best,
        'calibration_thresholds':threshold_scores,'selected_threshold':threshold,
        'test_labels_used':False,'common_semantic_sha256':common_semantic_id,'jobs':jobs})
    arms=('light_head','recurrent_1','recurrent_4','recurrent_12','best_fixed','simple_stop','fbsde_tree','exact_formula')
    if profile != LEGACY:
        arms += ('syntax_prior',)
    if profile == COMPOSITION:
        arms += ('composition_frozen', 'composition_cell', 'composition_guarded')
    records={a:[] for a in arms}; actual_cost={a:0 for a in arms}
    belief_inputs = {}
    cpu_eval=time.process_time_ns()
    for i,row in enumerate(public['test']):
        # All controls observe the same fixed feature table and explicit syntax.
        x,s=xy['test'][0][i:i+1].clone(),xy['test'][1][i:i+1]
        order=list(arms);random.Random(seed+i).shuffle(order)
        for arm in order:
            cpu,wall=time.process_time_ns(),time.perf_counter_ns()
            residual=None; nodes=0; depth=1; executed=1; composition_record=None
            with torch.inference_mode():
                # Charge the same semantic forward for every arm; the root
                # consumes exactly these probabilities plus identical features.
                uids=row['utterance_ids'];targets=row['target_intents']
                if arm == 'syntax_prior':
                    # This intentionally cheaper null control ignores text and the semantic Head.
                    ps = [.25]*len(uids)
                else:
                    qs=semantic(torch.stack([features[u] for u in uids])).softmax(-1)
                    ps=[float(qs[j,t].item()) for j,t in enumerate(targets)]
                    x[0, :len(ps), 388] = torch.tensor(ps)
                if arm.startswith('composition_'):
                    composition_record=evaluate_composition(row['formula'],ps,
                        before_fit if arm=='composition_frozen' else fitted_corners,
                        correct=arm=='composition_guarded')
                    p=composition_record['probability'];depth=composition_record['learned_operator_depth'];executed=0
                elif arm=='light_head':p=float(head(x,s).sigmoid().item())
                elif arm.startswith('recurrent_') or arm=='best_fixed':
                    depth=best if arm=='best_fixed' else int(arm.split('_')[-1]);executed=depth
                    p=float(recurrent(x,s,depth).sigmoid().item())
                elif arm=='simple_stop':
                    executed=0
                    for depth in DEPTHS:
                        p=float(recurrent(x,s,depth).sigmoid().item());executed+=depth
                        if max(p,1-p)>=threshold or depth==DEPTHS[-1]:break
                else:
                    if arm=='fbsde_tree':p,residual,nodes=belief_bsde(row['formula'],ps)
                    else:p=polynomial_probability(row['formula'],ps)
                    depth=0;executed=0  # deterministic solver nodes are not learned depth
            p=checked_probability(p); text=decode_probability(p)
            elapsed=time.process_time_ns()-cpu
            require(elapsed<=100_000_000,'per-prediction CPU budget exhausted')
            actual_cost[arm]+=elapsed
            if arm == 'fbsde_tree':
                belief_inputs[row['case_id']] = {'public_input_sha256':digest(row),
                    'leaf_probabilities':ps, 'semantic_sha256':common_semantic_id}
            records[arm].append({'case_id':row['case_id'],'public_input_sha256':digest(row),
                'probability':p,'text':text,'selected_depth':depth,'actual_recurrent_steps':executed,
                'bsde_interface_residual':residual,'scenario_nodes':nodes,
                'cpu_ns':elapsed,'wall_ns':time.perf_counter_ns()-wall})
            if composition_record is not None: records[arm][-1]['composition'] = composition_record
    # Seal ALL predictions before this code reads test truths for evaluation.
    for arm in arms:write_once(output/(arm+'-predictions.json'),records[arm])
    write_once(output/'belief-inputs.json', belief_inputs)
    require(state_digest(semantic)==common_semantic_id,'shared semantic Head mutated at inference')
    if composition is not None:
        require(composition.corners.detach().tolist()==fitted_corners,'composition cell mutated at inference')
    metrics={arm:score_decoded(records[arm],truths['test']) for arm in arms}
    equality=max(abs(a['probability']-b['probability']) for a,b in zip(records['fbsde_tree'],records['exact_formula']))
    require(equality<1e-12,'finite BSDE diverged from algebraic control on identical beliefs')
    fits={j['job_id']:j['cpu_ns'] for j in jobs}
    root_cost={a:(fits['light_head'] if a=='light_head' else fits['shared_recurrent']
                  if a not in ('fbsde_tree','exact_formula','syntax_prior') and not a.startswith('composition_') else 0) for a in arms}
    if profile == COMPOSITION:
        root_cost.update({a:fits['composition_cell'] for a in ('composition_cell','composition_guarded')})
    # Standalone accounting: each arm includes the same available semantic fit.
    # Physical ledger counts each actual common job once, not eight times.
    lifecycle={a:actual_cost[a]+root_cost[a]+fits['common_semantic']+semantic_annotation_cpu+
               (fits['shared_controller_selection'] if a in ('best_fixed','simple_stop') else 0) for a in arms}
    if profile != LEGACY:
        lifecycle['syntax_prior'] = actual_cost['syntax_prior']
        lifecycle['best_fixed'] -= jobs[-1]['stop_selection_cpu_ns']
        # Simple stop actually consumes the calibration grid, not best-fixed validation.
        lifecycle['simple_stop'] -= jobs[-1]['fixed_selection_cpu_ns']
    evaluated_cost = time.process_time_ns()-cpu_eval-sum(actual_cost.values())
    strata={a:stratified_metrics(records[a],truths['test'],public['test']) for a in arms}
    sources={r['id']:r.get('source_sha256',digest(r['id'])) for rows in partitions.values() for r in rows}
    census=source_census(public['test'],sources)
    envelope=time.process_time_ns()-study_start_cpu
    classified=sum(j['cpu_ns'] for j in jobs)+semantic_annotation_cpu+sum(actual_cost.values())+evaluated_cost
    require(envelope >= classified, 'overlapping CPU accounting')
    report={'schema':('hepta.fbsde.encoder-study.results.v1' if profile == LEGACY else
                      'hepta.fbsde.encoder-study.results.v2' if profile == INDEPENDENT else
                      'hepta.fbsde.encoder-study.results.v3'),
            'question_profile':profile, 'strata':strata, 'source_census':census,
            'metrics':metrics,'inference_cpu_ns':actual_cost,
            'adaptation_plus_inference_cpu_ns':lifecycle,'jobs_once':jobs,'semantic_annotation_cpu_ns':semantic_annotation_cpu,
            'selection':{'best_fixed_depth':best,'simple_stop_threshold':threshold},
            'fbsde_vs_exact_max_probability_difference':equality,
            'equal_actual_lifecycle_within_5pct':max(lifecycle.values())<=1.05*min(lifecycle.values()),
            'same_budget_ceiling':True, 'equal_compute_superiority_claimed':False,
            'full_lifecycle_resource_gate_passed':False,'general_reasoning_claimed':False,
            'production_promotion_permitted':False,
            'limitations':['generated composite questions, not real future tasks',
                           'factorized learned belief is not authenticated conditional law',
                           'many tasks reuse utterances; task count is not independent source count',
                           'fixed two-sentence decoder, not open-ended generation',
                           'BSDE f=0 finite recursion, not fully coupled continuous NDU'],
            'evaluation_and_recording_cpu_ns':evaluated_cost,
            'study_cpu_envelope_ns':envelope, 'classified_jobs_once_cpu_ns':classified,
            'unattributed_preparation_and_reporting_cpu_ns':envelope-classified,
            'standalone_costs_are_lower_bounds':True,
            'all_physical_work_accounted_by_envelope_not_sum_of_standalone_arms':True}
    write_once(output/'private-test-truths.json',truths['test'])
    write_once(output/'comparison.json',report)
    return report


def run(args):
    process_start_cpu=time.process_time_ns()
    import torch
    from four_gate_pretrained import load_pinned, MODEL, REVISION
    from four_gate_public_replay import read_public_data, DATA_REV, DATA_PINS
    torch.set_num_threads(2);torch.manual_seed(args.seed)
    args.output.mkdir(parents=True,exist_ok=False)
    source=subprocess.check_output(['git','-C',str(args.source_root),'rev-parse','HEAD'],text=True).strip();sha(source,40)
    cpu,wall=time.process_time_ns(),time.perf_counter_ns()
    data,_=read_public_data(args.output/'publisher')
    partitions=partition_utterances(data)
    model,tokenizer,inventory,loading=load_pinned(args.model_dir)
    load={'cpu_ns':time.process_time_ns()-cpu,'wall_ns':time.perf_counter_ns()-wall}
    write_once(args.output/'load.json',{'source_sha':source,'model':MODEL,'revision':REVISION,
        'physical_files':inventory,'loading_info':loading,'publisher_revision':DATA_REV,'publisher_pins':DATA_PINS,
        'input_inventory':partitions,'load':load,'model_is_frozen':True})
    cpu,wall=time.process_time_ns(),time.perf_counter_ns()
    with torch.inference_mode():model(**tokenizer(['What is the time?'],return_tensors='pt'))
    warmup={'cpu_ns':time.process_time_ns()-cpu,'wall_ns':time.perf_counter_ns()-wall}
    rows=[r for v in partitions.values() for r in v];features={};events=[]
    for start in range(0,len(rows),32):
        batch=rows[start:start+32];cpu,wall=time.process_time_ns(),time.perf_counter_ns()
        tokens=tokenizer([r['text'] for r in batch],padding=True,truncation=False,return_tensors='pt')
        require(tokens['input_ids'].shape[1]<=256,'utterance token ceiling; no silent truncation')
        with torch.inference_mode():
            hidden=model(**tokens).last_hidden_state.float();mask=tokens['attention_mask'].unsqueeze(-1).float()
            vectors=(hidden*mask).sum(1)/mask.sum(1)
        require(torch.isfinite(vectors).all().item(),'nonfinite real Encoder output')
        events.append({'job_id':'encoder-'+str(start),'ids':[r['id'] for r in batch],
            'input_ids_sha256':tensor_digest(tokens['input_ids']), 'vectors_sha256':tensor_digest(vectors),
            'actual_tokens':int(mask.sum().item()),'cpu_ns':time.process_time_ns()-cpu,
            'wall_ns':time.perf_counter_ns()-wall})
        features.update({r['id']:vectors[i].clone() for i,r in enumerate(batch)})
    train=torch.stack([features[r['id']] for r in partitions['train']])
    mean,scale=train.mean(0),train.std(0).clamp_min(.1)
    raw_vectors=torch.stack(list(features.values()))
    features={k:((v-mean)/scale).clamp(-8,8) for k,v in features.items()}
    write_once(args.output/'forward-events.json',{'events':events,'warmup':warmup,
        'normalizer_training_inputs':[r['id'] for r in partitions['train']],
        'normalizer_sha256':digest([tensor_digest(mean),tensor_digest(scale)])})
    # Public-data vectors only, no pretrained weights or private task content.
    vector_path=args.output/'frozen-features.pt'
    torch.save({'ids':list(features), 'vectors':torch.stack(list(features.values())),
                'raw_vectors':raw_vectors, 'normalizer_mean':mean, 'normalizer_scale':scale},vector_path)
    comparison=train_and_compare(torch,partitions,features,args.output,args.seed,profile=args.question_profile)
    common=load['cpu_ns']+warmup['cpu_ns']+sum(e['cpu_ns'] for e in events)
    from four_gate_pretrained import file_hash
    write_once(args.output/'physical-summary.json',{'source_sha':source,'model':MODEL,'revision':REVISION,
        'question_profile':args.question_profile,
        'feature_artifact_sha256':file_hash(vector_path),
        'feature_semantics':'frozen_pretrained_vectors_with_train_only_normalization',
        'measured_cpu_envelope_before_final_report_ns':time.process_time_ns()-process_start_cpu,
        'standalone_totals_are_lower_bounds':True,
        'real_weights_executed':True,'encoder_forwards':len(events),'encoder_rows':len(rows),
        'common_load_warmup_encoder_cpu_ns':common,
        'standalone_total_cpu_ns':{a:(c if a=='syntax_prior' else common+c)
                                   for a,c in comparison['adaptation_plus_inference_cpu_ns'].items()},
        'physical_shared_jobs_counted_once':True,
        'whole_process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        'gpu_measured':False,'energy_measured':False,'not_executed_phases':['migration'],
        'full_lifecycle_resource_gate_passed':False,'production_promotion_permitted':False})
    from fbsde_audit import recompute_comparison
    write_once(args.output/'arithmetic-audit.json',recompute_comparison(args.output,partitions))
    print('real frozen Encoder comparison completed; no scientific superiority or production gate inferred',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',type=Path,required=True);p.add_argument('--model-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--seed',type=int,default=104729)
    p.add_argument('--question-profile',choices=PROFILES,default=LEGACY)
    run(p.parse_args())
