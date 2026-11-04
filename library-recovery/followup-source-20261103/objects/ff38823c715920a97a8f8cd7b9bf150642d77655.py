"""Isolated reproduction of the v3 check_cases function, research-only.
Not a substitute for exact-repository CI or source attestation.
"""
import copy, hashlib, unittest
from collections import defaultdict

SPLITS = ('train','calibration','test','future1','future2','future3','ood')
EVAL_SPLITS = ('test','future1','future2','future3','ood')
MODALITY = ('text','image','audio','video')
READER = ('none','retrieved','sufficient','premise_removed')
class Invalid(ValueError): pass

def ident(x):
    if type(x) is not str or not 1 <= len(x) <= 128 or not all(c.isascii() and (c.isalnum() or c in '._:-') for c in x): raise Invalid('invalid ident')
    return x

def digest(x):
    if type(x) is not str or len(x) != 64 or x == '0'*64 or any(c not in '0123456789abcdef' for c in x): raise Invalid('bad digest')
    return x

def number(v,*,positive=False):
    if type(v) not in (float,int) or not -10**18 <= v <= 10**18 or (positive and v <= 0): raise Invalid('number')
    return float(v)

def check_cases(raw):
    if type(raw) is not list or not 1 <= len(raw) <= 50000:
        raise Invalid("missing cohort rows")
    cases, groups, sources, observed = {}, defaultdict(set), defaultdict(set), defaultdict(list)
    # A declared independent source family cannot recycle identical input bytes
    # under another family name to inflate paired bootstrap/source counts.
    source_owner_by_input = {}
    # This is a task-INSTANCE identifier, not a reusable task type. Its
    # presence in a second split leaks prior task identity across windows even
    # if the surrounding context and source-group strings have changed.
    task_split_owner = {}
    reader_by_task = defaultdict(dict)
    for r in raw:
        if type(r) is not dict:
            raise Invalid("invalid case row")
        cid, task = ident(r.get("case_id")), ident(r.get("task_id"))
        split, modality, reader = r.get("split"), r.get("modality"), r.get("reader_condition")
        if cid in cases or split not in SPLITS or modality not in MODALITY or reader not in READER:
            raise Invalid("duplicate case or unsupported split/modality/Reader")
        previous_split = task_split_owner.setdefault(task, split)
        if previous_split != split:
            raise Invalid("task instance identity reused across temporal cohorts")
        group = ident(r.get("source_group"))
        src = digest(r.get("input_sha256"))
        original_owner = source_owner_by_input.setdefault(src, (split, group))
        if original_owner != (split, group):
            raise Invalid("identical input reused across distinct source families")
        number(r.get("observed_at"), positive=True)
        if type(r.get("label")) is not int or r["label"] not in (0, 1):
            raise Invalid("binary externally supplied label missing")
        digest(r.get("expected_effect_sha256"))
        rk = (split, task)
        if reader in reader_by_task[rk]:
            raise Invalid("repeated Reader condition in task")
        reader_by_task[rk][reader] = r
        groups[split].add(group)
        sources[split].add(src)
        observed[split].append(r["observed_at"])
        cases[cid] = r
    for i, a in enumerate(SPLITS):
        for b in SPLITS[i+1:]:
            if groups[a] & groups[b] or sources[a] & sources[b]:
                raise Invalid("source/input leakage between evaluation cohorts")
    if not observed["train"] or not observed["calibration"]:
        raise Invalid("missing train/calibration partition")
    present = [s for s in SPLITS[:-1] if observed[s]]
    if any(max(observed[a]) >= min(observed[b]) for a, b in zip(present, present[1:])):
        raise Invalid("train/future time boundary violated")
    for s in EVAL_SPLITS:
        if not observed[s]:
            raise Invalid("missing prospective/holdout evaluation partition")
    if min(observed["ood"]) <= max(max(observed["train"]), max(observed["calibration"])):
        raise Invalid("OOD examples must occur after train/calibration freeze")
    for (split, task), by_condition in reader_by_task.items():
        if split in EVAL_SPLITS:
            if set(by_condition) != set(READER):
                raise Invalid("missing Reader four-condition task intervention")
            if len({r["label"] for r in by_condition.values()}) != 1:
                raise Invalid("Reader intervention changed original task answer")
            if (by_condition["sufficient"]["input_sha256"]
                    == by_condition["premise_removed"]["input_sha256"]):
                raise Invalid("Reader sufficient/premise-removed intervention has identical input bytes")
            for key in ("modality", "source_group", "expected_effect_sha256"):
                if len({r[key] for r in by_condition.values()}) != 1:
                    raise Invalid("Reader intervention changed original task media/source/effect")
    if not {r["modality"] for r in cases.values()} >= set(MODALITY):
        raise Invalid("not all real media modes declared")
    return cases, groups

def sha(x):return hashlib.sha256(x.encode()).hexdigest()

def fixture():
    raw=[]
    for t,split in enumerate(SPLITS,1):
        for m,mod in enumerate(MODALITY):
            task=f'task-{split}-{mod}'
            for j,condition in enumerate(READER):
                cid=f'case-{split}-{mod}-{j}'
                raw.append(dict(case_id=cid,task_id=task,split=split,source_group=f'family-{split}-{mod}',modality=mod,reader_condition=condition,label=(t+m)%2,input_sha256=sha('input/'+cid),expected_effect_sha256=sha('effect/'+task),observed_at=t*100+4*m+j))
    return raw

class Regression(unittest.TestCase):
    def test_positive_four_views(self):
        rows=fixture();cases,groups=check_cases(rows);self.assertEqual(len(cases),112);self.assertEqual(len(groups['future1']),4)
    def test_train_to_future_identity_leak(self):
        rows=fixture();rows[48]['task_id']=rows[0]['task_id'];
        with self.assertRaisesRegex(Invalid,'task instance identity reused'):check_cases(rows)
    def test_future_to_ood_identity_leak(self):
        rows=fixture();rows[96]['task_id']=rows[64]['task_id'];
        with self.assertRaisesRegex(Invalid,'task instance identity reused'):check_cases(rows)
    def test_same_input_different_family_leak(self):
        rows=fixture();rows[4]['input_sha256']=rows[0]['input_sha256'];
        with self.assertRaisesRegex(Invalid,'identical input reused'):check_cases(rows)
    def test_same_task_reader_different_inputs(self):
        rows=fixture();rows[33]['input_sha256']=rows[32]['input_sha256'];check_cases(rows)
    def test_noop_premise_removal(self):
        rows=fixture();rows[35]['input_sha256']=rows[34]['input_sha256'];
        with self.assertRaisesRegex(Invalid,'sufficient/premise-removed'):check_cases(rows)

if __name__=='__main__': unittest.main(verbosity=2)
