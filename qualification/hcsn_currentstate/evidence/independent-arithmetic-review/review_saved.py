"""Independent stdlib arithmetic over saved bytes. No candidate/oracle imports."""
from collections import Counter
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path

ROOT = Path('/workspace/scratch/c06d659c1e72/currentstate-packets')
OUT = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'evidence/currentstate-attempt001'
ARTIFACT_COMMIT = 'a9a7fc48d6c27636fc3b5c71065c1a33b7111807'
SOURCE_COMMIT = 'de3d9372d8bd53bb4c523c6f1a43e3e213d33790'
FLOOR = 1e-12
TOL = 2e-11
KEYS = {'active', 'upper', 'M', 'H', 'A', 'R', 'Z'}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def flat(value):
    if isinstance(value, list):
        for item in value:
            yield from flat(item)
    else:
        yield value

def finite(value):
    assert all(type(v) in (int, float) and math.isfinite(v) for v in flat(value))

def exactsum(value):
    return sum((F.from_float(float(v)) for v in flat(value)), F(0))

def maximum_difference(a, b):
    aa, bb = list(flat(a)), list(flat(b))
    assert len(aa) == len(bb)
    return max((abs(x-y) for x, y in zip(aa, bb)), default=0.)

def decoded(value):
    shape = value['shape']
    assert all(type(n) is int and n >= 0 for n in shape)
    data = [float.fromhex(h) for h in value['hex']]
    assert len(data) == math.prod(shape) and all(math.isfinite(x) for x in data)
    return shape, data

def frac(raw):
    assert len(raw) == 2 and all(type(x) is int for x in raw)
    value = F(*raw)
    assert [value.numerator, value.denominator] == raw
    return value

def read(path):
    return json.loads(path.read_text())

def main():
    freeze = read(ROOT / 'FREEZE.json')
    summary = read(EVIDENCE / 'SUMMARY.json')
    rows = read(EVIDENCE / 'ROWS.json')
    remote = read(OUT/'GIT_DIRECTORY.json')
    remote_source = read(OUT/'GIT_SOURCE_DIRECTORY.json')
    assert remote['commit'] == ARTIFACT_COMMIT
    assert remote_source['commit'] == freeze['source_commit'] == summary['source_freeze_commit'] == SOURCE_COMMIT
    remote_entries = json.loads(remote['retrieved']['content'])
    remote_source_entries = json.loads(remote_source['retrieved']['content'])
    artifact_paths = {}
    for item in remote_entries:
        name = item['name']
        path = ({'FREEZE.json': ROOT/'FREEZE.json',
                 'RUN.stdout': ROOT/'CURRENTSTATE-attempt001.stdout',
                 'RUN.stderr': ROOT/'CURRENTSTATE-attempt001.stderr'}.get(name, EVIDENCE/name))
        artifact_paths[name] = path
        raw = path.read_bytes()
        assert len(raw) == item['size'] and blob(raw) == item['sha'], name
    assert len(artifact_paths) == 16
    source_paths = {name: ROOT/name for name in freeze['source_sha256']}
    sources_before = {name: sha(p.read_bytes()) for name, p in source_paths.items()}
    artifacts_before = {name: {'bytes': len(p.read_bytes()), 'sha256': sha(p.read_bytes()),
                              'git_blob': blob(p.read_bytes())} for name,p in artifact_paths.items()}
    assert sources_before == freeze['source_sha256'] == summary['source_sha256_before'] == summary['source_sha256_after']
    for item in remote_source_entries:
        path = ROOT/'qualification/hcsn_currentstate'/item['name']
        raw = path.read_bytes()
        assert len(raw) == item['size'] and blob(raw) == item['sha']
    assert len(remote_source_entries) == len(source_paths) == 7
    for name, meta in summary['artifacts'].items():
        assert artifacts_before[name]['bytes'] == meta['bytes']
        assert artifacts_before[name]['sha256'] == meta['sha256']
    assert len(summary['artifacts']) == 12
    stdout = read(ROOT/'CURRENTSTATE-attempt001.stdout')
    assert all(stdout[k] == summary[k] for k in stdout)

    assert len(rows) == summary['rows'] == 18
    assert len({(r['fixture'], r['time']) for r in rows}) == 18
    expected_times = [F(x) for x in ('0','.001','.025','.0625','.13','.2','.201','.28','.36')]
    count = Counter(); eligible = 0; null = 0
    max_abs = {}; max_relative = {}; max_order = {}
    error_checks = 0
    physical_baseline = {}; conservation = {}; balances = {}
    per_fixture = {}
    quantity_shapes = {}
    for row in rows:
        name, t = row['fixture'], F(row['time'])
        per_fixture.setdefault(name, []).append(t)
        obs, r32, r64 = (row[k] for k in ('observed','reference32','reference64'))
        assert set(obs) == set(r32) == set(r64) == set(row['error']) == KEYS
        n = 2 if name == 'mixed' else 1
        assert row['packets'] <= 128 and row['packet_max_dimension'] <= 64
        shapes = {'active': (3,2,n), 'upper': (3,3), 'M': (3,2), 'H': (3,2),
                  'A': (3,3), 'R': (3,3), 'Z': (3,3)}
        quantity_shapes[name] = shapes
        for key in KEYS:
            for value in (obs[key], r32[key], r64[key]):
                finite(value)
                assert len(list(flat(value))) == math.prod(shapes[key])
            errors = row['error'][key]
            arrays = [list(flat(v)) for v in (obs[key],r64[key],r32[key],errors['absolute'],errors['relative_eligible'],errors['reference_order_delta'])]
            assert len({len(x) for x in arrays}) == 1
            for actual, ref, low, err, rel, delta in zip(*arrays):
                assert err == abs(actual-ref)
                assert delta == abs(low-ref)
                max_abs[key] = max(max_abs.get(key,0.), err)
                max_order[key] = max(max_order.get(key,0.), delta)
                if abs(ref) >= FLOOR:
                    assert rel == err/abs(ref)
                    max_relative[key] = max(max_relative.get(key,0.), rel)
                    eligible += 1
                else:
                    assert rel is None
                    null += 1
                count[(name,key)] += 1
                error_checks += 1
        physical = [exactsum(obs['active'][c])+exactsum(obs['upper'][c])+exactsum(obs['R'][c]) for c in range(3)]
        if t == 0:
            physical_baseline[name] = physical
        mass_error = max(abs(a-b) for a,b in zip(physical,physical_baseline[name]))
        conservation[(name,str(t))] = float(mass_error)
        assert mass_error <= F.from_float(TOL) and row['channel_conservation_error'] <= TOL
        # Generation two cannot yet release from refractory at T<2d.
        r2m2 = max(abs(F.from_float(obs['R'][c][2])-F.from_float(obs['M'][c][1])) for c in range(3))
        # Every first hit is either pending, active in generation two, upper in
        # generation two, or a second hit; this is a current-state balance.
        gen1 = max(abs(F.from_float(obs['M'][c][0])-exactsum(obs['active'][c][1])-
                       F.from_float(obs['upper'][c][2])-F.from_float(obs['M'][c][1])-
                       F.from_float(obs['R'][c][1])) for c in range(3))
        z2h2 = max(abs(obs['Z'][c][2]-math.exp(-.15*(.2-float(t)))*obs['H'][c][1]) for c in range(3))
        balances[(name,str(t))] = {'R2_equals_M2_residual': float(r2m2),
                                  'first_hit_current_state_balance_residual': float(gen1),
                                  'Z2_H2_scalar_identity_residual': z2h2}
        assert max(float(r2m2),float(gen1),z2h2) <= TOL
        if t <= F(1,5):
            assert all(x == 0 for x in flat(obs['active'][0][1]))
            assert all(obs[k][c][1] == 0 for k in ('M','H') for c in range(3))
        assert all(v >= 0 for key in KEYS for v in flat(obs[key][0]))
    assert all(times == expected_times for times in per_fixture.values())
    assert set(per_fixture) == {'mixed','rare'}
    assert error_checks == 1026 and (eligible,null) == (629,397)
    assert eligible == summary['eligible_scalar_rows'] and null == summary['ineligible_relative_scalar_rows']
    assert max_abs == summary['max_abs']
    assert max_relative == summary['max_relative_eligible_diagnostic']
    assert max_order == summary['max_reference_order_delta']
    assert summary['finite_control_absolute_checks_passed'] == all(v <= TOL for v in max_abs.values())
    assert summary['reference_order_check_passed'] == all(v <= TOL for v in max_order.values())
    assert summary['conservation_check_passed'] == all(r['channel_conservation_error'] <= TOL for r in rows)

    snapshots = {}; cold_checks = {}; rejected = 0; rare_packet = None
    for name in ('mixed','rare'):
        for label,time in (('resume',F(201,1000)),('final',F(9,25))):
            path = EVIDENCE/f'{name}.{label}.json'; raw = path.read_bytes(); capsule = json.loads(raw)
            assert canonical(capsule) == raw
            assert sha(canonical(capsule['state'])) == capsule['sha256']
            state = capsule['state']; assert frac(state['time']) == time
            assert state['operator'] == 'finite-exponential-flux-packets-v1'
            match = next(r for r in rows if r['fixture'] == name and F(r['time']) == time)
            for key in ('active','upper','M','H','A'):
                shape, data = decoded(state[key])
                assert tuple(shape) == quantity_shapes[name][key]
                assert data == list(flat(match['observed'][key]))
            assert len(state['pending']) == match['packets'] <= 128
            pinfo = []
            for p in state['pending']:
                assert p['kind'] == 'flux'
                assert type(p['target']) is int and type(p['origin']) is int
                assert 1 <= p['target'] <= 3 and p['origin'] == p['target']-1
                start,end = frac(p['start']),frac(p['end'])
                assert time <= start < end
                ash,alpha = decoded(p['alpha']); gsh,g = decoded(p['generator']); osh,o = decoded(p['output'])
                k = osh[0]; assert ash == [3,k] and gsh == [k,k] and osh == [k] and k <= 64
                assert min(alpha[:k]) >= 0 and min(o) >= 0
                assert all(g[i*k+j] >= 0 for i in range(k) for j in range(k) if i != j)
                # Exact positive graph reachability, no propagated values.
                reached = {i for i,x in enumerate(alpha[:k]) if x > 0}
                while True:
                    more = reached | {j for i in reached for j in range(k) if i != j and g[i*k+j] > 0}
                    if more == reached: break
                    reached = more
                reachable = any(o[i] > 0 for i in reached)
                initial_flux = sum(alpha[i]*o[i] for i in range(k))
                info = {'origin':p['origin'],'target':p['target'],'start':str(start),'end':str(end),
                        'dimension':k,'positive_probability_graph_reachable':reachable,
                        'probability_flux_at_support_start':initial_flux}
                pinfo.append(info)
                if name == 'rare' and label == 'resume' and p['origin'] == 2:
                    assert start == F(2,5) and end == F(401,1000) and reachable
                    rare_packet = info
            snapshots[f'{name}.{label}'] = {'sha256':sha(raw),'checksum_valid':True,
                                           'canonical_bytes_exact':True,'time':str(time),'packets':pinfo}
        cold = read(EVIDENCE/f'{name}.cold.json')
        assert cold['restored_snapshot_exact'] is True and cold['start_time'] == '201/1000'
        assert [r['time'] for r in cold['rows']] == ['7/25','9/25']
        assert cold['final_snapshot_sha256'] == snapshots[f'{name}.final']['sha256']
        errors = {key:0. for key in KEYS}
        for crow in cold['rows']:
            fine = next(r for r in rows if r['fixture'] == name and r['time'] == crow['time'])
            for key in KEYS:
                errors[key] = max(errors[key],maximum_difference(crow['observed'][key],fine['observed'][key]))
        assert errors == summary['cost'][name]['cold_errors']
        assert cold['cost'] == summary['cost'][name]['cold']
        assert summary['cost'][name]['cold_final_bytes_exact'] is True
        controls = summary['cost'][name]['reject_controls']
        assert len(controls) == len({c['name'] for c in controls}) == 13
        assert all(c['rejected'] is True for c in controls)
        rejected += len(controls)
        cold_checks[name] = {'final_digest_equals_retained_fine_snapshot':True,
                             'restored_snapshot_exact_reported':True,'recomputed_observation_errors':errors,
                             'snapshot_reject_controls_reported':len(controls)}
    assert rare_packet is not None and rejected == 26
    rare = next(r for r in rows if r['fixture'] == 'rare' and r['time'] == '201/1000')
    rare_detail = {'M2':rare['observed']['M'][0][1], 'reference64_M2':rare['reference64']['M'][0][1],
                  'absolute_error':rare['error']['M']['absolute'][0][1],
                  'relative_eligible':rare['error']['M']['relative_eligible'][0][1],
                  'R_origin2':rare['observed']['R'][0][2], 'H2':rare['observed']['H'][0][1],
                  'Z_origin2':rare['observed']['Z'][0][2], 'retained_packet':rare_packet}
    assert 0 < rare_detail['M2'] < FLOOR and rare_detail['relative_eligible'] is None

    source_after = {name:sha(path.read_bytes()) for name,path in source_paths.items()}
    artifacts_after = {name:{'bytes':len(p.read_bytes()),'sha256':sha(p.read_bytes()),'git_blob':blob(p.read_bytes())}
                       for name,p in artifact_paths.items()}
    assert sources_before == source_after and artifacts_before == artifacts_after
    assert summary['admission'] == 'HOLD_NO_GO' and summary['all_closed'] is False
    assert summary['numerical_roundoff_certified'] is False
    assert all(summary[k] == 0 for k in ('old_kernels','old_refs','training','torch'))
    auxiliary = OUT/'cost-negative/REVIEW.json'
    auxiliary_raw = auxiliary.read_bytes()
    auxiliary_data = json.loads(auxiliary_raw)
    result = {
        'identity':'independent-currentstate-saved-arithmetic-review-v1',
        'artifact_commit':ARTIFACT_COMMIT,'source_freeze_commit':SOURCE_COMMIT,
        'review_method':'stdlib saved-byte hashes, array scalar arithmetic, exact rational balances, packet graph inspection; no candidate/oracle import',
        'new_candidate_calls':0,'new_reference_calls':0,'new_expm_calls':0,'new_quadratures':0,
        'new_training_calls':0,'old_kernel_calls':0,'old_reference_calls':0,
        'remote_git_artifacts_matched':16,'remote_git_source_files_matched':7,
        'source_sha256_before':sources_before,'source_sha256_after':source_after,
        'artifacts_before':artifacts_before,'artifacts_after':artifacts_after,
        'summary_artifact_entries_matched':12,'stdout_summary_fields_matched':True,
        'query_rows':18,'scalar_observation_reference_error_checks':error_checks,
        'eligible_scalars':eligible,'ineligible_relative_null_scalars':null,
        'per_fixture_quantity_counts':{name:{key:count[(name,key)] for key in sorted(KEYS)} for name in ('mixed','rare')},
        'floor':FLOOR,'absolute_tolerance':TOL,'max_absolute_errors':max_abs,
        'max_eligible_relative_diagnostic':max_relative,'max_reference_order_delta':max_order,
        'initial_channel_totals':{name:[str(x) for x in v] for name,v in physical_baseline.items()},
        'max_exact_rational_conservation_residual':max(conservation.values()),
        'max_current_state_balance_residuals':{key:max(v[key] for v in balances.values()) for key in next(iter(balances.values()))},
        'snapshots':snapshots,'cold_checks':cold_checks,'reported_snapshot_rejections':rejected,
        'rare_second_hit_at_0_201':rare_detail,
        'cost_and_negative_independent_review':{'path':str(auxiliary),'sha256':sha(auxiliary_raw),
                                              'read_receipt':auxiliary_data},
        'findings':[],
        'limitations':[
            'Coarse coordinate observations were not retained: schedule comparison is guarded summary-only and is not independently reconstructible from saved arrays.',
            'Cold final snapshot bytes were not separately retained: independent verification matches the cold-reported final SHA256 against retained fine final raw bytes, plus all saved cold observations.',
            '26 rejection outcomes are saved execution receipts; malformed input attempts were not re-executed by this reviewer.',
            'GL32/64 agreement with shared scipy.expm backend is an assembly cross-check, not a numerical-roundoff certificate.',
            'Scope is two finite fixtures, n<=2, three independent linear channels and T<=.36: no continuum, full network, training, gradient or production checkpoint qualification.',
            'Saved parent ru_maxrss omits child RSS; RLIMIT_AS is a per-process address-space cap.'
        ],
        'admission':'HOLD_NO_GO','all_closed':False,
        'review_source_sha256':sha(Path(__file__).read_bytes())
    }
    raw = (json.dumps(result,indent=2,allow_nan=False)+'\n').encode()
    (OUT/'REVIEW.json').write_bytes(raw)
    print(json.dumps({'read_only':True,'artifact_commit':ARTIFACT_COMMIT,'git_artifacts':16,'source_files':7,
                      'scalar_checks':error_checks,'eligible':eligible,'null':null,'max_error':max(max_abs.values()),
                      'rejections_reported':rejected,'rare_M2':rare_detail['M2'],
                      'new_candidate_calls':0,'new_reference_calls':0,'new_expm_calls':0,
                      'review_sha256':sha(raw),'admission':'HOLD_NO_GO'}))

if __name__ == '__main__':
    main()
