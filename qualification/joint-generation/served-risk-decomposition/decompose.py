"""Saved-report arithmetic only: no model, dataset, gradient, or training imports."""
import argparse
import hashlib
import json
import math
from pathlib import Path

SEEDS = (41011, 41023)
NOISE = ('sigma-1/16', 'sigma-3/16')
CELLS = tuple((s, a, m) for s in SEEDS for a in ('C', 'E') for m in ('S', 'A', 'N'))
BINS = ((0.0, .5), (.5, .9), (.9, .99), (.99, 1.0))
TOL = 1e-12
METRICS = ('expected_accuracy', 'expected_mse', 'expected_utility', 'conditional_entropic_rho2')


def bounded(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('finite unit-interval '+name+' required')
    return float(value)


def rho(p, mse):
    p, mse = bounded(p, 'class mass'), bounded(mse, 'decoded MSE')
    q = math.exp(-mse/.04)
    return -math.log1p(-p*(-math.expm1(-2*q)))/2


def channels(p_left, m_left, p_right, m_right):
    """Symmetric metric identity, not a realizable hybrid model or causal effect."""
    ll, rr = rho(p_left, m_left), rho(p_right, m_right)
    lr, rl = rho(p_left, m_right), rho(p_right, m_left)
    p_part = math.fsum((lr-rr, ll-rl))/2
    m_part = math.fsum((rl-rr, ll-lr))/2
    delta = ll-rr
    if abs(math.fsum((p_part, m_part))-delta) > TOL:
        raise ArithmeticError('two-channel identity')
    return {'rho_delta': delta, 'class_mass_component': p_part, 'image_mse_component': m_part,
            'accuracy_delta': p_left-p_right, 'mse_delta': m_left-m_right}


def bin_index(p):
    bounded(p, 'reference mass')
    return 0 if p < .5 else 1 if p < .9 else 2 if p < .99 else 3


def digest(s):
    if type(s) is not str or len(s) != 64 or any(c not in '0123456789abcdef' for c in s):
        raise ValueError('SHA256 identity')
    return s


def report_rows(report):
    if (report.get('schema') != 'endpoint-anchor-comparison-fresh-AA-v1/served-report'
            or report.get('origin') != 'DEV-developmental' or report.get('checkpoint') != 'final'
            or report.get('panel') != 'corrupted' or report.get('official_TEST_read') is not False
            or tuple(report.get('cell', ())) not in CELLS):
        raise ValueError('exact saved developmental final report required')
    digest(report['cohort_sha256']); digest(report['source_sha256'])
    rows = report['request_rows']; indexed = {}; grouped = {}
    if len(rows) != 1530:
        raise ValueError('complete 765-source two-variant report')
    for r in rows:
        key = (r['source_id'], r['variant'])
        if (type(key[0]) is not str or not key[0] or key[1] not in NOISE or key in indexed
                or type(r['label']) is not int or not 0 <= r['label'] <= 9
                or r.get('law') != 'finite-u53-fixed-10'):
            raise ValueError('unique fixed-law request identity')
        digest(r['request_sha256']); digest(r['target_sha256'])
        p, m = bounded(r['expected_accuracy'], 'class mass'), bounded(r['expected_mse'], 'MSE')
        if p*2**53 != int(p*2**53):
            raise ValueError('exact served u53 mass')
        eu, risk = p*math.exp(-m/.04), rho(p, m)
        if any(type(r[k]) not in (int, float) or not math.isfinite(r[k]) for k in METRICS):
            raise ValueError('finite saved metrics')
        if abs(eu-r['expected_utility']) > TOL or abs(risk-r['conditional_entropic_rho2']) > TOL:
            raise ValueError('saved law does not reconstruct as one fixed image')
        nll = r['actual_class_nll']
        if p == 0:
            if nll != {'tag':'positive_infinity','value':None}: raise ValueError('unsmoothed zero mass')
        elif nll.get('tag') != 'finite' or abs(nll['value']+math.log(p)) > TOL:
            raise ValueError('saved class NLL')
        indexed[key] = r; grouped.setdefault(key[0], []).append(r)
    if len(grouped) != 765 or any({r['variant'] for r in g} != set(NOISE) or
            len({(r['target_sha256'],r['label']) for r in g}) != 1 for g in grouped.values()):
        raise ValueError('complete source pairs and shared target')
    for metric in METRICS:
        expected = math.fsum(math.fsum(r[metric] for r in g)/2 for _,g in sorted(grouped.items()))/765
        if abs(expected-report['overall']['metrics'][metric]) > TOL:
            raise ValueError('saved equal-source aggregation')
    return indexed


def plans(seed):
    return ([(m+' E-C', (seed,'E',m), (seed,'C',m)) for m in ('S','A','N')]
            + [(a+' N-'+m, (seed,a,'N'), (seed,a,m)) for a in ('C','E') for m in ('S','A')])


def summarize(rows, denominator=None):
    denominator = len(rows) if denominator is None else denominator
    keys = ('rho_delta','class_mass_component','image_mse_component','accuracy_delta','mse_delta')
    if not rows:
        return {'requests':0,'mean':None,'contribution_to_stratum_mean':{k:0.0 for k in keys}}
    means = {k:math.fsum(r[k] for r in rows)/len(rows) for k in keys}
    residual = math.fsum((means['class_mass_component'],means['image_mse_component']))-means['rho_delta']
    if abs(residual) > TOL: raise ArithmeticError('aggregate channel identity')
    return {'requests':len(rows),'mean':means,'reconstruction_residual':residual,
            'contribution_to_stratum_mean':{k:math.fsum(r[k] for r in rows)/denominator for k in keys}}


def analyze(reports):
    if len(reports) != 12 or {tuple(r['cell']) for r in reports} != set(CELLS):
        raise ValueError('all 12 cells required; no partial winner')
    indexed = {tuple(r['cell']):report_rows(r) for r in reports}
    identities = [{k:(v['label'],v['request_sha256'],v['target_sha256']) for k,v in x.items()} for x in indexed.values()]
    if any(x != identities[0] for x in identities[1:]): raise ValueError('unpaired report inventories')
    if len({(r['cohort_sha256'],r['source_sha256']) for r in reports}) != 1: raise ValueError('same frozen cohort/source')
    results = []
    for seed in SEEDS:
        for name,left,right in plans(seed):
            l,r = indexed[left],indexed[right]; values=[]
            for key in sorted(l):
                a,b=l[key],r[key]
                d=channels(a['expected_accuracy'],a['expected_mse'],b['expected_accuracy'],b['expected_mse'])
                if abs(d['rho_delta']-(a['conditional_entropic_rho2']-b['conditional_entropic_rho2'])) > TOL:
                    raise ArithmeticError('saved paired delta reconstruction')
                values.append({**d,'variant':key[1],'bin':bin_index(b['expected_accuracy'])})
            strata={}
            for variant in ('all',)+NOISE:
                rows=[v for v in values if variant=='all' or v['variant']==variant]
                strata[variant]={'overall':summarize(rows),'reference_mass_bins':[
                    {'interval':list(bounds),'upper_inclusive':i==3,**summarize([v for v in rows if v['bin']==i],len(rows))}
                    for i,bounds in enumerate(BINS)]}
                for k in ('rho_delta','class_mass_component','image_mse_component'):
                    if abs(math.fsum(x['contribution_to_stratum_mean'][k] for x in strata[variant]['reference_mass_bins'])-strata[variant]['overall']['mean'][k]) > TOL:
                        raise ArithmeticError('exhaustive bin conservation')
            results.append({'seed':seed,'name':name,'left':list(left),'right':list(right),'strata':strata})
    return {'schema':'saved-served-risk-decomposition-v1','status':'DESCRIPTIVE_POST_BUDGET_FAILURE_ONLY',
            'reports':12,'requests_per_report':1530,'contrasts':results,'models_or_datasets_read':False,
            'training_or_model_evaluation_repeated':False,'official_TEST_read':False,
            'original_protocol_acceptance':False,'causal_training_claim':False,'new_policy_feasibility_claim':False,
            'statistical_inference':'none; reused developmental reports, fixed seeds and bins, no independent confirmation'}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('manifest');ap.add_argument('output');args=ap.parse_args()
    plan=json.loads(Path(args.manifest).read_text());reports=[]
    for ref in plan['input_reports']:
        raw=Path(ref['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest(ref['sha256']):raise ValueError('input report hash changed')
        d=json.loads(raw)
        if d['cell']!=ref['cell']:raise ValueError('input cell identity')
        reports.append(d)
    result=analyze(reports);result['input_report_sha256']=[r['sha256'] for r in plan['input_reports']]
    result['plan_sha256']=hashlib.sha256(Path(args.manifest).read_bytes()).hexdigest()
    Path(args.output).write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':result['status'],'reports':12,'contrasts':len(result['contrasts'])}))


if __name__=='__main__':main()
