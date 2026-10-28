"""Post-freeze independent review: read existing artifacts, never fit or regenerate."""

from collections import Counter
import gzip
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import struct
import tarfile
import time

import numpy as np
from PIL import Image
from scipy.special import expit, ndtr

from experiments.analytic_event_neuron.round2 import run


ROOT = Path('/tmp/aen-round2-20261027')
PROJECT = Path('/workspace/scratch/d831a963ef2f/hepta-analytic')
SOURCE = PROJECT / 'experiments/analytic_event_neuron/round2'
OUT = ROOT / 'reviews/FEEDBACK_INDEPENDENT_REVIEW.json'
COUNTS, ERRORS = Counter(), {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def require(condition, category, detail):
    COUNTS[category] += 1
    if not bool(condition):
        raise AssertionError(f'{category}: {detail}')


def close(a, b, category, detail, tolerance=1e-10):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    require(a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all(), category, detail + ' domain')
    error = float(np.max(np.abs(a - b))) if a.size else 0.0
    ERRORS[category] = max(ERRORS.get(category, 0.0), error)
    require(error <= tolerance, category, detail)


def load_npz(path):
    with np.load(path, allow_pickle=False) as data:
        return {k: data[k].item() if data[k].ndim == 0 else data[k] for k in data.files}


def dataset_digest(data):
    return digest({k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in data.items()})


def image_value(payload):
    with Image.open(io.BytesIO(payload)) as im:
        require(im.format == 'PNG' and im.mode == 'L' and im.size == (256, 32), 'sample_png', 'format')
        p = np.array(im)
    bits = 0
    for i in range(64):
        top, bottom = p[:16, i*4:(i+1)*4], p[16:, i*4:(i+1)*4]
        bit = int(top[0, 0])
        require(bit in (0, 255) and np.all(top == bit) and np.all(bottom == 255-bit), 'sample_png', 'bit blocks')
        bits = (bits << 1) | (bit // 255)
    return struct.unpack('>d', bits.to_bytes(8, 'big'))[0]


def archive_read(directory, metadata, sample_cases):
    path = directory / Path(metadata['archive_path']).name
    require(sha(path) == metadata['archive_sha256'] and path.stat().st_size == metadata['archive_bytes'], 'archive', 'archive digest/size')
    content = {}
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            parts = PurePosixPath(member.name)
            require(not parts.is_absolute() and '..' not in parts.parts, 'archive', 'safe member path')
            if member.isdir():
                continue
            require(member.isfile() and member.name not in content, 'archive', 'regular unique member')
            payload = archive.extractfile(member).read()
            require(len(payload) == member.size, 'archive', 'member size')
            content[member.name] = payload
    prefix = str(PurePosixPath(metadata['manifest_member']).parent) + '/'
    manifest_bytes = content[metadata['manifest_member']]
    require(hashlib.sha256(manifest_bytes).hexdigest() == metadata['manifest_sha256'], 'archive', 'manifest digest')
    manifest = json.loads(manifest_bytes)
    require(set(content) == {prefix + x for x in manifest['files']} | {metadata['manifest_member']}, 'archive', 'full inventory')
    for relative_name, expected in manifest['files'].items():
        payload = content[prefix+relative_name]
        require(len(payload) == expected['bytes'] and hashlib.sha256(payload).hexdigest() == expected['sha256'], 'artifact_hash', relative_name)
    raw = content[metadata['receipt_member']]
    require(hashlib.sha256(raw).hexdigest() == metadata['receipt_sha256'], 'archive', 'receipt digest')
    receipts, referenced = {}, {metadata['manifest_member'], metadata['receipt_member']}
    png_count, deliveries, observations = 0, 0, 0
    for line in raw.splitlines():
        receipt = json.loads(line)
        key = (receipt['case'], receipt['arm'], receipt['kind'], receipt['stage'])
        require(key not in receipts and receipt['private_target_supplied'] is False, 'receipt', 'identity and public declaration')
        require(0 < receipt['began_ns'] <= receipt['written_ns'] <= receipt['readback_ns'], 'chronology', 'individual operation order')
        if receipt['kind'] == 'observation':
            observations += 1
            payload = content[prefix+receipt['path']]
            referenced.add(prefix+receipt['path'])
            require(hashlib.sha256(payload).hexdigest() == receipt['sha256'], 'receipt_hash', 'observation')
            obj = json.loads(payload)
            require(set(obj) == {'schema', 'value'} and obj['schema'] == 'hepta.analytic-event.public-observation.v1', 'public_information', 'observation schema')
            value = float(obj['value'])
        else:
            deliveries += 1
            require(receipt['kind'] == 'delivery', 'receipt', 'delivery type')
            text, png = content[prefix+receipt['text_path']], content[prefix+receipt['image_path']]
            referenced.update((prefix+receipt['text_path'], prefix+receipt['image_path']))
            require(hashlib.sha256(text).hexdigest() == receipt['text_sha256'] and hashlib.sha256(png).hexdigest() == receipt['image_sha256'], 'receipt_hash', 'text/PNG')
            value = float(text)
            require(struct.pack('>d', value) == struct.pack('>d', receipt['prediction']), 'text_readback', 'delivery bits')
            if receipt['case'] in sample_cases:
                require(struct.pack('>d', image_value(png)) == struct.pack('>d', value), 'sample_png', 'decoded value')
                png_count += 1
        receipts[key] = (receipt, value)
    require(referenced == set(content), 'coverage', 'every archive member referenced')
    require(observations == metadata['observations'] and deliveries == metadata['deliveries'] and observations + 2*deliveries == metadata['files'], 'coverage', 'transport totals')
    require(len(content) == metadata['verified_archive_files'], 'coverage', 'producer archive count')
    return receipts, {'archive_sha256': sha(path), 'files_hashed': len(content), 'observations_redecoded': observations,
                      'delivery_texts_redecoded': deliveries, 'png_images_independently_decoded': png_count,
                      'sample_case_ids': sorted(sample_cases)}


def independent_interval(delta, settings, index):
    rng = np.random.default_rng(settings['bootstrap_seed'] + index)
    seeds, cases = delta.shape
    draws = []
    for start in range(0, settings['bootstrap_replicates'], 200):
        count = min(200, settings['bootstrap_replicates']-start)
        s = rng.integers(0, seeds, (count, seeds))
        rows = rng.integers(0, cases, (count, seeds, cases))
        selected = delta[s[:, :, None], rows]
        draws.extend(selected.reshape(count, -1).mean(1).tolist())
    alpha = settings['interval_alpha']
    return np.quantile(draws, [alpha/2, 1-alpha/2])


def review():
    started = time.perf_counter_ns()
    frozen = run.verify_freeze(ROOT)
    protocol = json.loads((SOURCE/'PROTOCOL.json').read_text())['feedback']
    published = json.loads((ROOT/'FEEDBACK_RESULTS.json').read_text())
    arms = protocol['arms']
    native_arms = {'numeric', 'analytic', 'event', 'quantized', 'zero', 'reset'}
    all_rows = {arm: [] for arm in arms}
    archive_reviews, seed_reviews, hashes = [], [], {}
    total_native_ticks, total_requests, total_kernel_ns, total_roundtrip_ns = 0, 0, 0, 0
    logical_events, packet_bytes, codec_packets = Counter(), Counter(), Counter()
    amount_differences = 0
    unchanged_training_heads = []
    for seed in protocol['seeds']:
        directory = ROOT/f'feedback_confirmation/seed_{seed}'
        model_dir = ROOT/f'feedback_training/seed_{seed}'
        summary = json.loads((directory/'SUMMARY.json').read_text())
        audit = json.loads((directory/'AUDIT.json').read_text())
        model = json.loads((model_dir/'MODELS.json').read_text())
        data = load_npz(directory/'DATA.npz')
        training, development = load_npz(model_dir/'TRAIN.npz'), load_npz(model_dir/'DEVELOPMENT.npz')
        require(set(data['ids']).isdisjoint(training['ids']) and set(data['ids']).isdisjoint(development['ids']) and set(training['ids']).isdisjoint(development['ids']), 'data_split', 'full ID set disjointness')
        require(data['split'] == 'confirmation' and data['seed'] == 10_000_000+seed*100+3, 'data_split', 'registered confirmation namespace')
        require(summary['dataset_sha256'] == dataset_digest(data) and model['training_dataset_sha256'] == dataset_digest(training) and model['development_dataset_sha256'] == dataset_digest(development), 'identity', 'dataset digests')
        model_path = f'feedback_training/seed_{seed}/MODELS.json'
        require(sha(model_dir/'MODELS.json') == frozen['artifacts_sha256'][model_path] == summary['models_file_sha256'], 'identity', 'frozen model bytes')
        require(summary['model_sha256'] == digest(model) and summary['rows_sha256'] == sha(directory/'ROWS.json.gz') and summary['data_file_sha256'] == sha(directory/'DATA.npz'), 'identity', 'model/rows/data bindings')
        require(audit['passed'] and audit['source_sha256'] == sha(SOURCE/'feedback_study.py'), 'prior_audit', 'auditor source identity')
        c = model['calibration']
        train_error = training['target']-training['initial_output']
        train_noise = training['self_evaluation']-training['target']
        close(c['error_variance'], np.mean(train_error**2), 'training_parameters', 'error-variance MLE')
        close(c['noise_scale'], np.mean(train_noise**2/training['sensor_variance']), 'training_parameters', 'noise-scale MLE')
        training_summary = json.loads((model_dir/'TRAINING_SUMMARY.json').read_text())
        require(training_summary['confirmation_used'] is False, 'training_parameters', 'no confirmation used declaration')
        for arm, head in model['heads'].items():
            receipt = training_summary['head_receipts'][arm]
            require(receipt['coefficients'] == len(head['weights']) == 63 and receipt['updates_per_l2'] == 600 and len(receipt['candidates']) == 33, 'training_parameters', 'matched head size/update/search opportunities')
            require(receipt['final_weights_sha256'] == digest(head['weights']), 'training_parameters', 'trained weight receipt digest')
            if receipt['initial_weights_sha256'] == receipt['final_weights_sha256']:
                require(arm in ('zero','reset') and receipt['parameter_l2_change'] == 0 and all(c['gradient_norm'] == 0 for c in receipt['candidates']), 'training_parameters', 'constant head has verified zero gradient')
                unchanged_training_heads.append({'seed':seed,'arm':arm,'reason':'constant input and zero recorded training gradient; 600 updates per L2 did not change weights'})
            else:
                require(receipt['parameter_l2_change'] > 0, 'training_parameters', 'nonzero trained parameter update')
            best = max(receipt['candidates'], key=lambda x:(x['utility'], -x['repairs'], x['l2'], x['threshold']))
            require(head['l2'] == best['l2'] and head['threshold'] == best['threshold'], 'training_parameters', 'development-only selection receipt')
        with gzip.open(directory/'ROWS.json.gz','rt') as stream:
            rows = json.load(stream)
        require(len(rows) == len(arms)*protocol['confirmation_rows'], 'coverage', 'episode count')
        sample_cases = {str(data['ids'][0]), str(data['ids'][-1])}
        receipts, archive_report = archive_read(directory, summary['archive'], sample_cases)
        archive_reviews.append({'seed':seed, **archive_report})
        position = {str(case):i for i,case in enumerate(data['ids'])}
        seen, by_arm, used_receipts = set(), {arm:[] for arm in arms}, set()
        ticks, requests, roundtrip, kernel = 0, 0, 0, 0
        for row in rows:
            case, arm = row['case'], row['arm']
            require(case in position and arm in arms and (case,arm) not in seen, 'coverage', 'unique registered case/arm')
            seen.add((case,arm)); i=position[case]
            entries = {}
            for kind,stage in [('delivery','initial'),('observation','self_evaluation'),('observation','sensor_variance'),('observation','repair_cost'),('delivery','feedback'),('delivery','final')]:
                key=(case,arm,kind,stage);used_receipts.add(key);entries[stage]=receipts[key]
            public={'initial':entries['initial'][1], 'residual':entries['feedback'][1],
                    'sensor_variance':entries['sensor_variance'][1], 'repair_cost':entries['repair_cost'][1]}
            expected={'initial':float(data['initial_output'][i]),'residual':float(data['self_evaluation'][i]-data['initial_output'][i]),
                      'sensor_variance':float(data['sensor_variance'][i]),'repair_cost':float(data['repair_cost'][i])}
            require(public == expected == row['acquired']['public'] and row['acquired']['public_sha256'] == digest(public), 'public_information', 'readbacks drive public dictionary')
            require(entries['self_evaluation'][1] == data['self_evaluation'][i], 'public_information', 'actual self-evaluation')
            timeline=[entries['initial'][0]['readback_ns']]
            for stage in ['self_evaluation','sensor_variance','repair_cost','feedback']:
                timeline += [entries[stage][0]['began_ns'], entries[stage][0]['readback_ns']]
            timeline += [row['acquired']['acquired_ns'],row['decision_ns'],entries['final'][0]['began_ns'],entries['final'][0]['readback_ns'],row['final_readback_ns'],row['score_started_ns']]
            require(all(a<=b for a,b in zip(timeline,timeline[1:])), 'chronology', 'public acquisition then choice/delivery/scoring record')
            alpha, noise = c['error_variance'], c['noise_scale']*public['sensor_variance']
            mean = alpha*public['residual']/(alpha+noise)
            variance = alpha*noise/(alpha+noise)
            if arm in ('event','quantized'):
                codec=row['posterior']['codec'];config={**c['event_config'],'mode':'error_feedback' if arm=='event' else 'direct_quantization'}
                levels=[0,0];steps=[config['mean_step'],config['logvar_step']]
                require(len(codec['packets'])==2,'codec','two target updates')
                for sequence,(packet,target) in enumerate(zip(codec['packets'],[(0.,math.log(alpha)),(mean,math.log(variance))]),1):
                    expected_levels=[math.floor(target[j]/steps[j]+.5) for j in range(2)]
                    require(set(packet)=={'schema','config_sha256','sequence','time','observation_kind','counts'},'codec','packet contains no continuous bypass')
                    require(packet['counts']==[expected_levels[j]-levels[j] for j in range(2)] and packet['sequence']==sequence and packet['config_sha256']==digest(config),'codec','independent count reconstruction')
                    levels=expected_levels
                require(codec['decoder']['levels']==levels and codec['decoder']['sequence']==2,'codec','decoder state')
                mean,variance=levels[0]*steps[0],math.exp(levels[1]*steps[1])
                amount_differences += int(mean != alpha*public['residual']/(alpha+noise)) if arm=='event' else 0
                count=sum(abs(x) for packet in codec['packets'] for x in packet['counts'])
                size=sum(len(json.dumps(packet,sort_keys=True,separators=(',',':')).encode()) for packet in codec['packets'])
                require(codec['logical_unit_events']==count and codec['packet_bytes']==size,'codec','logical event and encoded byte costs')
                logical_events[arm]+=count;packet_bytes[arm]+=size;codec_packets[arm]+=2
            else:
                require(row['posterior']['codec'] is None,'codec','noncodec arm')
            amount=mean; cost=public['repair_cost']
            if amount==0:
                threshold=None;probability=0.;event='empty_positive_gain_event'
            else:
                threshold=(amount*amount+cost)/(2*amount)
                probability=float(ndtr((mean-threshold)/math.sqrt(variance))) if amount>0 else float(ndtr((threshold-mean)/math.sqrt(variance)))
                event='call: E>threshold' if amount>0 else 'put: E<threshold'
            for key,value in [('mean',mean),('variance',variance),('repair_amount',amount),('expected_gain',amount*amount-cost),('improvement_probability',probability)]:
                close(row['posterior'][key],value,'posterior',key)
            require(row['posterior']['event']==event and (row['posterior']['threshold'] is None)==(threshold is None),'posterior','event semantics')
            if threshold is not None:close(row['posterior']['threshold'],threshold,'posterior','threshold')
            raw=np.array([public['residual'],math.log(public['sensor_variance']),math.log(cost)])
            z=(raw-np.array(c['public_center']))/np.array(c['public_scale'])
            feature=None
            if arm=='history':
                powers=[(a,b,d) for a in range(4) for b in range(4) for d in range(4) if a+b+d<=3]
                feature=np.r_[[np.prod(z**p) for p in powers],np.exp(-.5*np.sum((np.array(c['history_centers'])-z)**2,axis=1))]
            elif arm in native_arms:
                logv=(math.log(variance)-c['logvar_center'])/c['logvar_scale']
                drives=np.tanh(z/3) if arm=='numeric' else np.array([2*probability-1,math.tanh(logv/3),math.tanh(z[2]/3)])
                if arm=='zero':drives=np.zeros(3)
                require(len(row['native'])==3,'native_record','three channels')
                vector=[]
                for channel,native in enumerate(row['native']):
                    q=int(round(float(drives[channel])*(1<<24)))
                    require(native['feedback_q24']==q and native['public_sha256']==digest(public) and native['native_binary_sha256']==model['native_binary_sha256'],'native_record','public drive/binary binding')
                    require(native['original_sparse_tick_calls']==2 and len(native['ticks'])==2 and native['checkpoint_reset_intervention']==(arm=='reset'),'native_record','two ticks/reset scope')
                    require(row['acquired']['acquired_ns']<=native['started_ns']<=native['completed_ns']<=row['decision_ns'],'chronology','native before choice')
                    first,second=native['ticks']
                    require(first['drive_q24']==[max(-q,0),max(q,0),(1<<24)//4]+[0]*7 and second['drive_q24']==[0]*10,'native_record','first drive and zero continuation')
                    require(second['checkpoint_before']==('0'*64 if arm=='reset' else first['checkpoint_after']),'native_record','checkpoint chain')
                    require(first['sequence']==1 and second['sequence']==(1 if arm=='reset' else 2),'native_record','state sequence')
                    for tick in native['ticks']:
                        require(tick['authority']=='DENY_ALL' and tick['requires_calibration'] and tick['native_owner_integration'] is False,'native_record','research authority boundary')
                    coordinates=[x/(1<<24) for key in ['activation_q24','eligibility_q24'] for x in second[key]]
                    close(native['features'],coordinates,'features','native recorded readout')
                    vector += [1.]+coordinates
                    ticks+=2;requests+=1;roundtrip+=native['subprocess_roundtrip_ns'];kernel+=sum(t['native_ns'] for t in native['ticks'])
                feature=np.asarray(vector)
            if feature is None:
                require(row['feature'] is None and row['native']==[],'features','direct arm')
                score=probability;repair=amount*amount-cost>0 if arm=='gaussian' else score>.5
            else:
                close(row['feature'],feature,'features','independent readout assembly')
                head=model['heads'][arm];score=float(expit(np.dot(feature,head['weights'])))
                repair=True if head['threshold']==0 else False if head['threshold']==1 else score>=head['threshold']
            close(row['score'],score,'decision','frozen score')
            require(row['repair']==bool(repair),'decision','frozen policy action')
            delivered=entries['final'][1]
            close(delivered,public['initial']+(amount if repair else 0.),'delivery','final numeric readback')
            require(struct.pack('>d',row['delivered'])==struct.pack('>d',delivered),'delivery','stored delivery bits')
            paid=cost if repair else 0.; error=(delivered-data['target'][i])**2
            for key,value in [('cost',paid),('squared_error',error),('utility',1-error-paid)]:close(row[key],value,'score',key)
            gain=(public['initial']-data['target'][i])**2-(public['initial']+amount-data['target'][i])**2-cost
            require(row['improvement_label']==bool(gain>0) and row['model_sha256']==digest(model),'score','postchoice label/model binding')
            by_arm[arm].append(row)
        require(used_receipts==set(receipts),'coverage','all receipts used by registered episodes')
        require(ticks==summary['native_ticks']==audit['native_ticks_replayed']==9216 and requests==summary['native_requests']==4608,'cost_counts','native counts')
        require(roundtrip==summary['native_roundtrip_ns']==audit['recorded_native_roundtrip_ns'] and kernel==audit['recorded_native_kernel_tick_ns'],'cost_counts','nested native timing')
        total_native_ticks+=ticks;total_requests+=requests;total_kernel_ns+=kernel;total_roundtrip_ns+=roundtrip
        for arm in arms:
            ordered=sorted(by_arm[arm],key=lambda x:x['case'])
            require(len(ordered)==256 and {x['case'] for x in ordered}==set(position),'coverage','paired arm cases')
            for key in ['utility','cost','squared_error','wall_ns']:
                close(summary['summary'][arm][key],np.mean([x[key] for x in ordered]),'seed_summary',arm+'/'+key)
            all_rows[arm].append(ordered)
        seed_reviews.append({'seed':seed,'episodes':len(rows),'prior_native_replay_passed':audit['passed'],
                             'native_ticks_in_recorded_evaluation':ticks,'native_requests':requests,
                             'archive_wall_ns':summary['archive']['archive_ns'], 'evaluation_wall_ns':summary['wall_ns'],
                             'evaluation_parent_cpu_ns':summary['cpu_ns'], 'prior_native_audit_wall_ns':audit['wall_ns']})
        for name in ['ROWS.json.gz','DATA.npz','SUMMARY.json','AUDIT.json','evaluation_readbacks.tar.gz']:
            hashes[(directory/name).relative_to(ROOT).as_posix()]=sha(directory/name)
    arm_summary={}
    for arm,seeds in all_rows.items():
        flat=[x for rows in seeds for x in rows]
        p=np.array([x['score'] for x in flat]);y=np.array([x['improvement_label'] for x in flat],float)
        q=np.clip(p,1e-12,1-1e-12);bins=np.minimum(np.floor(p*10).astype(int),9)
        ece=sum(np.mean(bins==b)*abs(p[bins==b].mean()-y[bins==b].mean()) for b in range(10) if np.any(bins==b))
        calibration={'ece':ece,'brier':float(np.mean((p-y)**2)),
                     'clipped_binary_nll':float(np.mean(-y*np.log(q)-(1-y)*np.log1p(-q)))}
        for key,value in calibration.items():close(published['arms'][arm]['calibration'][key],value,'calibration',arm+'/'+key)
        values={k:float(np.mean([x[k] for x in flat])) for k in ['utility','cost','squared_error','wall_ns']}
        for key,value in values.items():close(published['arms'][arm][key],value,'aggregate_summary',arm+'/'+key)
        require(published['arms'][arm]['repairs']==sum(x['repair'] for x in flat) and published['arms'][arm]['episodes']==len(flat),'aggregate_summary','counts')
        arm_summary[arm]={**values,'calibration':calibration,'repairs':sum(x['repair'] for x in flat),
                          'clipped_probability_count':int(np.sum(p!=q))}
    comparisons={}
    for index,(candidate,baseline) in enumerate(protocol['contrasts']):
        delta=np.array([[a['utility']-b['utility'] for a,b in zip(s,t)] for s,t in zip(all_rows[candidate],all_rows[baseline])])
        name=candidate+'_vs_'+baseline;expected=published['contrasts'][name]
        bounds=independent_interval(delta,protocol['statistics'],index)
        close(expected['mean_difference'],delta.mean(),'comparisons',name+' mean',1e-12)
        close(expected['per_seed_mean_difference'],delta.mean(1),'comparisons',name+' seeds',1e-12)
        close(expected['interval'],bounds,'comparisons',name+' interval',1e-12)
        require(expected['descriptive_only'] and not expected['production_superiority_established'],'comparisons','no inflated promotion')
        comparisons[name]={'mean_difference':float(delta.mean()),'interval95':bounds.tolist(),
                           'per_seed_mean':delta.mean(1).tolist(),'independent_recomputation_matches':True}
    mechanism={name:0 for name in ['analytic_vs_numeric','event_vs_numeric','event_vs_quantized','gaussian_vs_probit']}
    for name in mechanism:
        a,b=name.split('_vs_')
        mechanism[name]=sum(x['repair']!=y['repair'] for sa,sb in zip(all_rows[a],all_rows[b]) for x,y in zip(sa,sb))
    require(published['episodes']==sum(len(s) for v in all_rows.values() for s in v)==11520,'coverage','total episodes')
    require(published['native_ticks_replayed']==total_native_ticks==46080,'coverage','prior audit native replay count')
    after=run.verify_freeze(ROOT)
    require(frozen==after,'freeze','before/after source and artifact identity')
    limitations=[
        'All nine contrasts are secondary descriptive intervals; no multiplicity-adjusted production superiority is established.',
        'Only five independent training seeds; 11,520 model episodes represent 1,280 paired unique confirmation trajectories, not 11,520 independent samples.',
        'Event and direct quantization are exactly equivalent here; the experiment does not identify an incremental benefit of error-feedback recurrence or a new function class.',
        'Zero/reset ablations retain a separate public-posterior repair-amount path. They test state-dependent decision gating, not removal of every feedback pathway.',
        'Event repair amounts are quantized, while zero/reset repair amounts are continuous; event-versus-ablation differences are not a pure single-mechanism intervention.',
        'score_started_ns is sampled after error and gain calculations. Source order places private target use after final delivery, but the timestamp is a scoring-record time, not independently observed first-target-access time.',
        'The feedback native operation uses original sparse_tick in a fresh two-tick local research chain with native_owner_integration=false; this is not itself production owner/journal integration.',
        'No native tick was reexecuted by this review. All prior full native replay audit records were verified and all saved tick inputs/checkpoint links/readout features were independently checked.',
        'All archive bytes, text and JSON values were checked; PNG pixel decoding in this review covers 270 preselected images. The earlier audited execution reports full PNG decoding.',
        'The packet counts/bytes are logical codec accounting; this feedback study applies packet dictionaries in-process and does not establish transport energy or network efficiency.',
        'Low ECE of constant zero/reset scores is not evidence of strong prediction or utility: their Brier/log loss and all-repair utility remain worse.',
        'CPU/IPC/kernel/archive times have nested scopes and must not be summed as disjoint costs; shared-host elapsed times do not establish hardware performance.',
        'Training calibration parameters and heads use supervised training labels and development-only selection; explicit artifact ID sets are disjoint, but there is no process-memory isolation proof.',
        'Numeric text and lossless PNG fixtures are controlled feedback transport, not natural-language or natural-image task capability.',
    ]
    return {'schema':'hepta.analytic-event.feedback-independent-review.v1','passed':True,
            'reviewer':'retention_round2; did not author the feedback implementation or summary',
            'scope':'Post-freeze independent artifact/statistical reconstruction without training, dataset generation or policy reevaluation',
            'source_commit':frozen['source_commit'],'freeze_sha256':sha(ROOT/'FREEZE.json'),
            'frozen_sources_verified':len(frozen['sources_sha256']),'frozen_artifacts_verified':len(frozen['artifacts_sha256']),
            'source_sha256':{name:sha(SOURCE/name) for name in ['feedback.py','feedback_study.py','feedback_summary.py']},
            'results_sha256':sha(ROOT/'FEEDBACK_RESULTS.json'),'raw_evidence_sha256':hashes,
            'checks_by_category':dict(COUNTS),'maximum_absolute_recomputation_error':ERRORS,
            'unchanged_constant_control_heads':unchanged_training_heads,
            'episodes_fully_reconstructed':11520,'unique_confirmation_trajectories':1280,
            'native_ticks_record_inspected':total_native_ticks,'native_requests_inspected':total_requests,
            'native_ticks_reexecuted_in_this_review':0,'prior_full_native_replay_ticks_verified':total_native_ticks,
            'archives':archive_reviews,'seed_reviews':seed_reviews,'arm_summary':arm_summary,
            'comparisons':comparisons,'action_disagreements':mechanism,
            'event_repair_amount_differs_from_unquantized_case_count':amount_differences,
            'logical_codec_accounting':{'unit_events':dict(logical_events),'packet_bytes':dict(packet_bytes),'packets':dict(codec_packets)},
            'costs':{'evaluation_wall_ns':sum(x['evaluation_wall_ns'] for x in seed_reviews),
                     'evaluation_parent_cpu_ns':sum(x['evaluation_parent_cpu_ns'] for x in seed_reviews),
                     'archive_wall_ns_nested_in_evaluation':sum(x['archive_wall_ns'] for x in seed_reviews),
                     'native_roundtrip_ns_nested_in_evaluation':total_roundtrip_ns,
                     'native_kernel_tick_ns_nested_in_roundtrip':total_kernel_ns,
                     'prior_audit_wall_ns_separate':sum(x['prior_native_audit_wall_ns'] for x in seed_reviews)},
            'limitations':limitations,'scientific_conclusion':'Actual feedback/state-dependent choice is exercised; extra analytic/event coding superiority over numeric, history or classical Gaussian is not established.',
            'recommendation':'KEEP_RESEARCH; retain negative and equivalence outcomes; no production promotion from feedback results',
            'review_tool_recovery':'Read-only review attempts encountered a local variable-shadowing bug while recording the first archive hash and an overly broad requirement that constant zero/reset control heads change weights. The latter was corrected to check their zero gradient and zero parameter-change receipts explicitly; seed 211 legitimately retains initial weights for these two controls. The post-freeze review script was corrected; no experimental source, model, protocol, data or result changed, and no experiment was reexecuted.',
            'review_wall_ns':time.perf_counter_ns()-started}


if __name__=='__main__':
    report=review()
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'passed':report['passed'],'episodes':report['episodes_fully_reconstructed'],
                      'checks':sum(report['checks_by_category'].values()),'action_disagreements':report['action_disagreements'],
                      'costs':report['costs'],'path':str(OUT)},indent=2),flush=True)
