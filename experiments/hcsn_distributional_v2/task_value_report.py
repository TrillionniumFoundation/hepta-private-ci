"""Independent outcome/accounting audit and prespecified descriptive reporting."""

import math
from pathlib import Path
import time

import numpy as np

from .task_value_common import read_json, write_json, sha, verify_selection
from .task_value_heads import FAMILIES
from .task_value_native import comparable_trajectory


def report(output):
    output = Path(output)
    started = time.process_time()
    verify_selection(output)
    protocol = read_json(output / 'PROTOCOL.json')
    training = read_json(output / 'TRAINING_SUMMARY.json')
    evaluation = read_json(output / 'EVALUATION_SUMMARY.json')
    complete = read_json(output / 'COMPLETE.json')
    metadata = read_json(output / 'data/fresh_mnist.json')
    with np.load(output / 'data/fresh_mnist.npz', allow_pickle=False) as source:
        labels = np.array(source['labels'], copy=True)
    with np.load(output / 'traces/test.npz', allow_pickle=False) as source:
        prediction = np.array(source['prediction'], copy=True)
        if not np.array_equal(labels, source['labels']):
            raise AssertionError('Fresh labels differ from the inference trace')
    queues = np.random.default_rng(73013).permutation(len(labels)).reshape(-1, 3)
    counterfactual_checks, native_checks, source_hashes = [], [], {}
    first_actions = {family: {} for family in FAMILIES}
    native_utility, native_cpu, counterfactual_utility = {}, {}, {}
    for family in FAMILIES:
        nu, nc, cu = [], [], []
        for price in protocol['prices']:
            root = output / 'evaluation' / ('price_' + str(price))
            cached_path = root / (family + '_counterfactual.npz')
            source_hashes[str(cached_path.relative_to(output))] = sha(cached_path)
            with np.load(cached_path, allow_pickle=False) as raw:
                if not np.array_equal(raw['queues'], queues):
                    raise AssertionError('Counterfactual queue assignment changed')
                reads = np.array(raw['task_reads'], copy=True)
                scores = np.zeros_like(reads)
                for stream in range(len(queues)):
                    for task in range(3):
                        count = reads[stream, task]
                        if count:
                            predicted = prediction[queues[stream, task], count - 1]
                            if predicted != raw['task_predictions'][stream, task]:
                                raise AssertionError('Counterfactual reported prediction differs')
                            scores[stream, task] = predicted == labels[queues[stream, task]]
                utility = scores.sum(-1) - price * reads.sum(-1)
                if not np.array_equal(scores, raw['task_correct']) or not np.allclose(
                        utility, raw['utility'], atol=1e-14, rtol=0):
                    raise AssertionError('Counterfactual reward does not reproduce from labels')
                if np.any(reads.sum(-1) + 2 * np.maximum((reads > 0).sum(-1) - 1, 0) > 48):
                    raise AssertionError('Counterfactual reads/refractory exceed deadline')
                cu.append(float(utility.mean()))
                counterfactual_checks.append({'family': family, 'price': price,
                                              'streams': len(utility), 'reward_recomputed': True})
            records = []
            first_actions[family][str(price)] = []
            for stream in range(protocol['native_streams']):
                path = root / family / ('stream_' + str(stream)) / 'RESULT.json'
                source_hashes[str(path.relative_to(output))] = sha(path)
                row = read_json(path)
                read_events = [event for event in row['events'] if event['kind'] == 'read_and_decide']
                first_actions[family][str(price)].append(read_events[0]['action'])
                if len(read_events) != row['actual_reads']:
                    raise AssertionError('Actual read-event ledger differs')
                recomputed_correct, recomputed_reads = 0, 0
                for task in row['task_results']:
                    index = task['task_index']
                    if task['source_id'] != metadata['image_source_ids'][queues[stream, index]]:
                        raise AssertionError('Native stream source identity differs')
                    correct = int(task['prediction'] == labels[queues[stream, index]])
                    if correct != task['correct'] or int(labels[queues[stream, index]]) != task['label']:
                        raise AssertionError('Native task reward does not match actual heldout label')
                    recomputed_correct += correct
                    recomputed_reads += task['actual_reads']
                for event in read_events:
                    q = round(math.tanh(event['score']) * (1 << 24))
                    if q != event['score_q24'] or ('keep' if q > 0 else 'stop') != event['action']:
                        raise AssertionError('Native quantized action evidence differs')
                    if event['native']['effective_action'] != event['action']:
                        raise AssertionError('Native receipt disagrees with recorded action')
                if (recomputed_reads != row['actual_reads'] or recomputed_correct != row['correct']
                        or abs(recomputed_correct - price * recomputed_reads - row['utility']) > 1e-13):
                    raise AssertionError('Native total utility does not reproduce')
                if recomputed_reads + row['quiet_ticks'] > 48:
                    raise AssertionError('Native deadline exceeded')
                records.append(row)
                native_checks.append({'family': family, 'price': price, 'stream': stream,
                                      'reward_and_action_recomputed': True})
            observed = float(np.mean([row['utility'] for row in records]))
            if abs(observed - evaluation['actual_native'][str(price)][family]['mean_utility']) > 1e-14:
                raise AssertionError('Native summary mean does not reproduce')
            nu.append(observed)
            nc.append(evaluation['actual_native'][str(price)][family]['complete_execution_cpu_per_stream'])
        native_utility[family], native_cpu[family] = float(np.mean(nu)), float(np.mean(nc))
        counterfactual_utility[family] = float(np.mean(cu))
    recovery = read_json(output / 'RECOVERY_AUDIT.json')
    reference = read_json(output / 'recovery/reference/RESULT.json')
    for kind in ('active', 'quiet'):
        if comparable_trajectory(read_json(output / 'recovery' / kind / 'RESULT.json')) != comparable_trajectory(reference):
            raise AssertionError('Recovery semantic trajectory changed after prior audit')
    switches = {family: {'low_to_high_price_changed_first_actions': sum(a != b for a, b in zip(
                    first_actions[family][str(protocol['prices'][0])], first_actions[family][str(protocol['prices'][-1])])),
                 'paired_streams': protocol['native_streams'], 'actions_by_price': first_actions[family]}
                for family in FAMILIES}

    phase = complete['phases']
    phase_measured = sum(row['complete_child_cpu_seconds'] for row in phase.values())
    if abs(phase_measured - complete['complete_measured_child_cpu_seconds']) > 1e-10:
        raise AssertionError('Complete phase CPU sum changed')
    campaign = read_json(output / 'CAMPAIGN_EXECUTION.json')
    measured = campaign['complete_child_cpu_seconds']
    coordinator_complete = measured - phase_measured
    if coordinator_complete < -1e-6 or campaign['exit_code'] != 0:
        raise AssertionError('Outer campaign measurement does not contain its completed workers')
    prior_cpu = 0.
    for prior in protocol.get('prior_attempts', []):
        from .task_value_common import REPOSITORY
        if sha(REPOSITORY / prior['receipt']) != prior['sha256']:
            raise AssertionError('Prior failed-attempt cost receipt changed')
        prior_cpu += prior['complete_child_cpu_seconds']
    train_trace = training['trace_receipts']['train']['cpu_seconds']
    val_trace = training['trace_receipts']['val']['cpu_seconds']
    fit_model = training['observation_model_fit_parent_cpu_seconds']
    teacher_solve = training['teacher_solve_and_save_parent_cpu_seconds']
    head_total = training['head_training_parent_cpu_seconds']
    ordinary_total = training['ordinary_selection_parent_cpu_seconds']
    fit_residual = phase['fit']['complete_child_cpu_seconds'] - (
        train_trace + val_trace + fit_model + teacher_solve + head_total + ordinary_total)
    if fit_residual < -1e-6:
        raise AssertionError('Nested fit costs exceed the complete fit receipt')
    candidate = {family: sum(row['complete_candidate_parent_cpu_seconds'] for row in
                              training['head_study']['candidates'][family]) for family in FAMILIES[:2]}
    bank = training['head_study']['teacher_bank_parent_cpu_seconds']
    head_shared = head_total - sum(candidate.values()) - bank
    ordinary_specific = training['ordinary_study']['family_parent_cpu_seconds']
    ordinary_shared = ordinary_total - sum(ordinary_specific.values())
    native_all = sum(row['parent_cpu_seconds'] + row['native_child_cpu_seconds']
                     for price in evaluation['actual_native'].values() for row in price.values())
    cache_by_family = {family: sum(price[family]['counterfactual_parent_cpu_seconds']
                                   for price in evaluation['counterfactual'].values()) for family in FAMILIES}
    fresh_trace = evaluation['fresh_trace_generation']['cpu_seconds']
    eval_residual = phase['evaluate']['complete_child_cpu_seconds'] - native_all - sum(cache_by_family.values()) - fresh_trace
    if eval_residual < -1e-6:
        raise AssertionError('Nested evaluation costs exceed complete evaluator cost')
    recovery_cpu = sum(row['complete_child_cpu_seconds'] for key, row in phase.items()
                       if key.startswith('recovery_') or key.startswith('resume_'))
    historical = training['backbone_historical_complete_cpu_seconds']
    common = historical + phase['prepare']['complete_child_cpu_seconds'] + phase['preflight']['complete_child_cpu_seconds']
    common += prior_cpu + coordinator_complete + fit_residual + eval_residual + fresh_trace + recovery_cpu
    setup = {}
    for family in FAMILIES:
        value = common + cache_by_family[family]
        if family in FAMILIES[:2]:
            value += train_trace + val_trace + fit_model + teacher_solve + bank + head_shared + candidate[family]
        elif family == 'tabular_bellman':
            value += train_trace + fit_model + teacher_solve
        elif family == 'validation_schedule':
            value += val_trace + ordinary_specific[family] + ordinary_shared
        elif family == 'validation_risk':
            value += train_trace + fit_model + val_trace + ordinary_specific[family] + ordinary_shared
        setup[family] = value
    ordinary = training['best_ordinary_family']
    scenarios = []
    for allocation in ('measured_method_components', 'all_new_campaign_vs_free_ordinary_setup_bound'):
        for lifetime in protocol['cost']['lifetimes_streams']:
            for rate in protocol['cost']['utility_per_cpu_second']:
                if allocation == 'measured_method_components':
                    candidate_setup, reference_setup = setup['bellman_value_head'], setup[ordinary]
                else:
                    candidate_setup, reference_setup = historical + measured + prior_cpu, historical
                candidate_cost = native_cpu['bellman_value_head'] + candidate_setup / lifetime
                reference_cost = native_cpu[ordinary] + reference_setup / lifetime
                candidate_net = native_utility['bellman_value_head'] - rate * candidate_cost
                reference_net = native_utility[ordinary] - rate * reference_cost
                scenarios.append({'allocation': allocation, 'future_stream_lifetime': lifetime,
                    'utility_units_per_cpu_second': rate, 'value_net_utility': candidate_net,
                    'ordinary_net_utility': reference_net, 'difference': candidate_net - reference_net,
                    'value_higher': candidate_net > reference_net})
    cost = {'measured_complete_campaign_cpu_seconds': measured,
            'preserved_prior_attempt_cpu_seconds': prior_cpu,
            'total_new_campaign_and_prior_attempt_cpu_seconds': measured + prior_cpu,
            'measured_disjoint_phase_cpu_seconds_nested': phase_measured,
            'coordinator_imports_and_self_cpu_seconds': coordinator_complete,
            'historical_backbone_search_cpu_seconds': historical,
            'native_runtime_cpu_per_stream': native_cpu,
            'scenario_one_time_setup_by_family': setup,
            'fit_unassigned_shared_cpu_seconds': fit_residual,
            'evaluation_unassigned_shared_cpu_seconds': eval_residual,
            'recovery_verification_complete_cpu_seconds': recovery_cpu,
            'scope': 'All measured phase processes are disjoint. Runtime/model/native details are nested. Setup allocations describe alternative future deployments, not additive totals.',
            'baseline_cost_bound': 'Second allocation charges every new campaign CPU second to value-head research and gives the ordinary reference free new setup, retaining its historical backbone and measured runtime. This is an intentionally favorable cost lower bound for the ordinary alternative, not its observed setup cost.',
            'method_allocation': 'Shared measured data, exact-oracle verification, imports, heldout-cache verification and complete recovery fixture costs charged to each alternative once; method-specific traces/solver/teacher/candidate search charged only where used. Native actual runtime charged per future stream. Schedule excludes train-trace/teacher/head fitting.',
            'recovery_limit': 'Complete verification fixture (reference/suspend/resume) is charged, not claimed as an isolated production restart latency.',
            'no_energy_or_dollar_price_measurement': True,
            'ordinary_reference_selected_on_validation': ordinary, 'scenarios': scenarios}
    write_json(output / 'COST_SCENARIOS.json', cost)
    audit = {'status': 'passed', 'counterfactual_checks': counterfactual_checks,
             'native_checks': native_checks, 'source_sha256': source_hashes,
             'fresh_images': len(labels), 'counterfactual_streams_per_price_policy': len(queues),
             'native_streams_per_price_policy': protocol['native_streams'],
             'price_causal_comparisons': switches, 'both_fresh_process_recoveries_identical': True,
             'report_parent_cpu_seconds_through_audit': time.process_time() - started,
             'analysis_scope': 'Recomputed actual rewards/actions from labels, predictions, paid reads and native receipts; not an independent retraining of the neural backbone'}
    write_json(output / 'AUDIT.json', audit)
    lines = ['# Regenerative task-value and actual owner study', '',
        '**Completed scoped experiment.** Exact binary observation Bellman checks and real-data task-control evidence are separate. The MNIST controller uses a train-fitted coarsened Markov approximation; neither its table nor its distilled values are certified as the exact neural belief-state optimum.', '',
        '## Contract and identities', '',
        'Each stream has three distinct shuffled MNIST images and 48 model-clock ticks. Every READ consumes one tick and pays the public price. FIRE scores actual classification correctness and terminates that owner/iterator. Two quiet ticks then consume deadline with no observation/model/owner step before a reset next task. These are task-layer actions, not claims that every internal pressure-neuron firing optimizes this reward.', '',
        'The new 384 source images reproduce and exclude the previous 640 test prefixes, and have zero source-ID overlap with original TRAIN/VAL/TEST or native003. Original validation data and one previously trained backbone are reused. Controllers are selected on actual VAL stream reward, then locked before fresh inference. The task queue is shuffled without replacement; its independent-restart observation model remains an approximation.', '',
        'The two learned heads have identical five inputs, 66 active parameters, initialization, minibatch sequences, updates, LR searches and checkpoint opportunities. One regresses task Q values (with advantage loss), the other distills ordinary actions from the same teacher. This isolates the training target/objective within a matched MLP, not a novel two-channel architecture. All selected parameters changed and received finite/nonzero gradients.', '',
        '## Quality, actual execution and complete measured runtime', '',
        'Scores are means over the three registered prices. The 128-stream counterfactual panel pays for every full-prefix cache computation; its logical skipped reads do not establish compute savings. The separate 16-stream native panel actually stops tensor iteration and resets real owners. Statistical resampling uses one complete three-task stream, averaged over prices.', '',
        '| Policy | Counterfactual utility, 128 streams | Actual native utility, 16 streams | Actual native CPU / stream |',
        '| --- | ---: | ---: | ---: |']
    for family in FAMILIES:
        lines.append(f'| {family} | {counterfactual_utility[family]:.8f} | {native_utility[family]:.8f} | {native_cpu[family]:.6f} s |')
    interval = evaluation['counterfactual_macro_paired_comparisons']['bellman_value_head']
    lines += ['', f'The ordinary reference selected before fresh testing is **{ordinary}**. Value-head minus this reference on the full counterfactual panel is **{interval["mean_paired_difference"]:.8f}**, with nominal descriptive stream-bootstrap interval **{interval["nominal_descriptive_bootstrap_interval"]}**. This is not a new significance or architecture-superiority gate.', '',
        f'Counterfactual/native paid-read and correctness parity mismatches: **{evaluation["cache_native_parity"]["mismatches"]}/{evaluation["cache_native_parity"]["cases"]}**. Detailed records are retained; their two evidence scopes are never pooled.', '',
        '## Future reward, causality and reset', '',
        'The exact binary fixture holds the observed prefix, noise law, price, current deadline and native profile fixed. Increasing the remaining task queue from one to three adds a genuine subsequent-task value and changes the actual owner from KEEP to STOP. Its receipts are in preflight/FUTURE_VALUE_CAUSALITY.json. Independent actual-label rollouts verify the later tasks produce their own rewards; the future term is not a constant bonus.', '',
        'Actual MNIST stream ledgers separately record later-task correctness and later net reward. Complete-price response records in AUDIT.json compare first actions at the same observed prefix; these are causal execution checks, not new quality comparisons.', '',
        'Fresh Python processes restore both a nonempty active neural state and a mid-refractory driver checkpoint. The saved state includes current task, queue identity, remaining deadline, remaining quiet ticks, accumulated ledger and generic nested neural tensors. The complete semantic trajectories, native checkpoints, final neural state and actual utility equal the uninterrupted engineering fixture. This fixture uses a declared fixed8 schedule and is separate from selected-policy quality.', '',
        '## Cost scopes', '',
        f'New complete campaign CPU: **{measured:.6f} s**, including the coordinator startup/imports, data preparation, preflight, both learned-head searches, teacher fitting/solving, counterfactual and actual native evaluation, and complete recovery verification. Its **{phase_measured:.6f} s** of measured phase processes and all waited native descendants are already included and must not be added again. Preserved earlier failed-attempt campaign CPU is **{prior_cpu:.6f} s**, also charged in the scenarios. Historical fixed-backbone search cost **{historical:.6f} s** is disclosed separately; it was not retrained here. The outer supervisor/final audit/report self CPU is recorded separately in ANALYSIS_PARENT_EXECUTION.json.', '',
        f'The value head exceeds the validation-chosen ordinary reference in **{sum(row["value_higher"] for row in scenarios)}/{len(scenarios)}** registered cost scenarios. Those are sensitivity calculations with explicit utility-per-CPU rates and future stream lifetimes, not measured money or energy. COST_SCENARIOS.json retains both measured-component allocation and a deliberately favorable ordinary-setup cost lower bound.', '',
        '## Limits and next use', '',
        'The noisy-binary oracle is exact for its discrete observation law. MNIST confidence bins discard information and do not become sufficient statistics by running Bellman recursion; predicted future value calibration and task quality must be judged against actual later rewards. The fixed backbone remains the previous v1 network. Any separately attached v2 distributional-model owner smoke/recovery result must keep its own identity and cannot inherit this controller quality result.', '',
        'Reproduction: invoke task_value_run with a new output directory and the verified raw MNIST source root. PROTOCOL.json, REGISTRATION.json, SELECTION_LOCK.json, all candidate updates/checkpoints, traces, actual native journals, phase receipts, counterfactual arrays, recovery artifacts and this audit are retained. No failed or prior evidence was overwritten.', '']
    with (output / 'REPORT.md').open('x') as stream:
        stream.write('\n'.join(lines))
    write_json(output / 'REPORT_EXECUTION.json', {'parent_cpu_seconds': time.process_time() - started,
        'scope': 'In-process final audit/report function; excludes Python imports and enclosing coordinator startup',
        'report_sha256': sha(output / 'REPORT.md'), 'audit_sha256': sha(output / 'AUDIT.json'),
        'cost_scenarios_sha256': sha(output / 'COST_SCENARIOS.json')})
    print({'report': str(output / 'REPORT.md'), 'native_value_utility': native_utility['bellman_value_head'],
           'ordinary': ordinary, 'native_ordinary_utility': native_utility[ordinary],
           'cost_wins': sum(row['value_higher'] for row in scenarios), 'scenarios': len(scenarios)}, flush=True)
