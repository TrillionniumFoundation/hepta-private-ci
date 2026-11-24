# MemoryCell historical single-hop matching audit (2026-10-11)

**Scope:** the 8 authored, previously exposed development tasks from generating source `59f9eadd5cc919359079e04442f7343838a60057`. This is a read-only reconstruction of selected source IDs and pre-existing reader outputs. **No model generation was performed.**

Source original plan SHA-256: `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`. Real Qwen reader ZIP SHA-256: `831ce9658bafcbaf04f4a15879982e58317322f7cd5137724498d7d20df7bb98`. Smol reader ZIP SHA-256: `67d46247bd1881c8fb3f73ec6122415d0d15a0ec24b02f193fb1294e7ea63bae`. Both archives had all 21 inner SHA-256 member checks pass and 48 distinct successful generated/strict-scored answers each.

The source-only `single_hop` selection exactly matches the archived `entity_time` selection for **4/8** queries: 2 new-fact and 2 correction tasks. On these four cases the archived Qwen success is **4/4**; the archived Smol success is **0/4**. For the other **4/8** composition/procedure tasks, no archived arm supplied that same single-hop selection. Their actual single-hop outcomes are **unobserved** and must not be estimated from the six-arm data.

If the historical outcomes are reused *only where the ordered evidence source list matches*, and every unobserved task is counted as unknown, the descriptive bounds are Qwen **4/8–8/8 (50%–100%)** and Smol **0/8–4/8 (0%–50%)**. These are not confidence intervals, predictive guarantees, or proof that a newly labeled condition would have generated identical tokens. They merely express how little of the additional single-hop question is currently identifiable from archived outputs. The new nine-arm reader trial remains necessary to measure the missing four cases, and must be independently replayed.

The source-only checker is `memorycell_archived_single_hop_audit.py`; the machine-readable detail is `memorycell_single_hop_observed_bounds_20261011.json` (one row per query per model). `production_accepted=false`, `model_generation_executed=false`, and `statistical_superiority=false`.

## Complete source-only reproduction script

```python
"""Reproduce observed-only single-hop evidence-substitution bounds from sealed archives.

Research-only, source-selection equivalence rather than new model generation.
Run against the historical source zip already extracted (plan/ and observations/)
and the two reader ZIPs, with the MemoryCell source modules in PYTHONPATH.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile
from strong_rag_hop_control import derive_single_hop

PINS = {
    'event-reader-actual-48.zip': '831ce9658bafcbaf04f4a15879982e58317322f7cd5137724498d7d20df7bb98',
    'event-reader-smol-48.zip': '67d46247bd1881c8fb3f73ec6122415d0d15a0ec24b02f193fb1294e7ea63bae',
}
PLAN_SHA = '9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897'
SOURCE_COMMIT = '59f9eadd5cc919359079e04442f7343838a60057'
ARMS = ('empty','hybrid','entity_time','organized','program_support','without_prerequisite')


def verified_records(path: Path):
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PINS[path.name]:
        raise ValueError('outer archive bytes differ')
    with zipfile.ZipFile(path) as zipfile_obj:
        files=set(zipfile_obj.namelist())
        entries={}
        for line in zipfile_obj.read('SHA256SUMS').decode().splitlines():
            found=re.fullmatch(r'([0-9a-f]{64})  (?:\./)?(.+)',line)
            if not found:raise ValueError('malformed inner digest entry')
            sha,filename=found.groups()
            if filename in entries or filename not in files:raise ValueError('duplicate or missing ZIP member')
            entries[filename]=sha
            if hashlib.sha256(zipfile_obj.read(filename)).hexdigest()!=sha:
                raise ValueError('inner ZIP member digest changed')
        if set(entries)!=files-{'SHA256SUMS'}:raise ValueError('ZIP member census mismatch')
        if zipfile_obj.read('tested-commit.txt').decode().strip()!=SOURCE_COMMIT:
            raise ValueError('generating source commit changed')
        rows=json.loads(zipfile_obj.read('run/scored-answers.json'))
        if len(rows)!=48 or len({(r['question_id'],r['arm']) for r in rows})!=48:
            raise ValueError('incomplete historical controlled reader census')
        if any(r['status']!='succeeded' or type(r['strict_task_success']) is not bool for r in rows):
            raise ValueError('failed or invalid archived model call')
        return rows,len(entries)


def audit(root: Path, reader_archives: Path):
    plan_bytes=(root/'plan/plan.json').read_bytes()
    if hashlib.sha256(plan_bytes).hexdigest()!=PLAN_SHA:
        raise ValueError('pinned original plan altered')
    plan=json.loads(plan_bytes)
    specs=json.loads((root/'observations/questions.json').read_text())
    sources=json.loads((root/'plan/source-view.json').read_text())
    cases,proof=derive_single_hop(plan['cases'],specs,{x['identity']:x for x in sources})
    if len(cases)!=8 or len(proof['test_cases'])!=8:
        raise ValueError('wrong historical scope count')
    reports={}
    for f in PINS:
        rows,files=verified_records(reader_archives/f)
        lookup={(r['question_id'],r['arm']):r for r in rows}
        if set(lookup)!={(q['query']['identity'],a) for q in cases for a in ARMS}:
            raise ValueError('historical question/arm census changed')
        observations=[]
        for case in cases:
            qid=case['query']['identity']; selected=case['controls']['single_hop']['selected']
            matches=[lookup[qid,a] for a in ARMS if lookup[qid,a]['selected']==selected]
            input_ids={r['receipt']['input_ids_digest'] for r in matches}
            answers={r['answer'] for r in matches}
            outcomes={r['strict_task_success'] for r in matches}
            if len(input_ids)>1 or len(answers)>1 or len(outcomes)>1:
                raise ValueError('identical historical evidence gives incompatible archived outcomes')
            observations.append(dict(question_id=qid,kind=case['kind'],single_hop_ids=selected,
                                     matched_historical_arms=[r['arm'] for r in matches],
                                     observed=bool(matches),
                                     observed_strict_success=matches[0]['strict_task_success'] if matches else None,
                                     archived_input_sha256=matches[0]['receipt']['input_ids_digest'] if matches else None))
        observed=sum(x['observed'] for x in observations)
        wins=sum(x['observed_strict_success'] is True for x in observations)
        n=len(observations)
        reports[f]=dict(zip_sha256=PINS[f],verified_inner_files=files,
                        historic_actual_calls=len(rows),first_hop_observed_questions=observed,
                        first_hop_unobserved_questions=n-observed,observed_successes=wins,
                        strict_success_lower_bound=wins/n,
                        strict_success_upper_bound=(wins+n-observed)/n,
                        note='Bound is about source-matched historical answers; not a new single-hop reader evaluation',
                        questions=observations)
    return dict(schema='hepta.memorycell.historical-single-hop-observation.v1',
                source_commit=SOURCE_COMMIT,historical_plan_sha256=PLAN_SHA,
                questions=len(cases), model_generation_executed=False,
                independent_semantic_review=False,
                statistical_superiority=False,production_accepted=False,
                reused_historic_control_responses_only=True,
                controls=reports)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('frozen_source',type=Path)
    parser.add_argument('archived_readers',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    value=audit(args.frozen_source,args.archived_readers)
    with args.output.open('x',encoding='utf-8') as f:
        json.dump(value,f,indent=2,ensure_ascii=False,allow_nan=False)
        f.write('\n')
    print(json.dumps({k:{'observed':v['first_hop_observed_questions'],'wins':v['observed_successes'], 'success_bounds':[v['strict_success_lower_bound'],v['strict_success_upper_bound']]} for k,v in value['controls'].items()},indent=2))
```
