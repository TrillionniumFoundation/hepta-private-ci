"""Model-free adversarial regressions. Fixture reports are never native evidence."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from four_gate_core import (COMPUTE_ARMS, NDU_ARMS, TASKS, PredictionJournal, canonical, causal_depth,
                            components, default_plan, digest, generic_nested_risk, latency, metrics,
                            paired_interval, probabilities, read_bytes, read_jsonl, recursive_value,
                            risk_ce, strict_loads, validate_plan, verify_journal, work_totals, write_once)
from four_gate_review import behavior_census, bound_path, review_cell, review_compute


def event(i, parents=None, kind="cell"):
    return {"event_id": str(i), "activation_id": "a" + str(i), "kind": kind, "parents": parents or []}


def tree():
    return {"root": {"actions": [
        {"id": "safe", "cost": .1, "duration": 2, "successors": [{"node": "half", "probability": 1.}]},
        {"id": "risky", "cost": .05, "duration": 1, "successors": [{"node": "yes", "probability": .6}, {"node": "no", "probability": .4}]}]},
        "half": {"terminal": .5}, "yes": {"terminal": 1.}, "no": {"terminal": 0.}}


def compute_rows():
    base = {"schema": "hepta.four-gate-compute.v1", "plan_digest": digest(default_plan()),
            "logical_cells": 64, "active_fraction": 1., "input_repeat_fraction": .5, "task_similarity": "high", "repetition": 0,
            "requests": 64, "ticked_cell_ids": [str(i) for i in range(64)], "unique_admitted_inputs": 32,
            "workload_digest": digest("inputs"), "host_session_digest": digest("host"),
            "encoder_pipeline_digest": digest("same encoder"), "weights_digest": digest("same weights"),
            "request_latencies_ms": [float(i + 1) for i in range(64)], "peak_rss_bytes": 10000,
            "cpu_seconds": .1, "wall_seconds": 1., "isolated_process_measurement": True,
            "arrival_profile": "cohort_burst", "gpu_seconds": None, "energy_joules": None,
            "production_promotion_permitted": False}
    result = []
    for arm in COMPUTE_ARMS:
        shared = arm == "shared_features_heads"
        result.append(dict(base, arm=arm, execution_id=arm, encoded_samples=32 if shared else 64,
                           encoder_batch_calls=1 if shared else 2, encoded_tokens=256 if shared else 576,
                           cache_hits=32 if shared else 0, inflight_coalesced=0))
    return result


def behavior_rows(arms=("single_step", "fixed_depth", "matched_budget_feedforward"), kind="reasoning"):
    plan = default_plan()
    budget = {"max_" + p + "_wall_seconds": 10. for p in ("training", "search", "inference", "evaluation", "migration")}
    predictions, outcomes = [], []
    for arm in arms:
        row = {"plan_digest": digest(plan), "kind": kind, "case_id": "case-1", "arm": arm,
               "production_promotion_permitted": False, "request_digest": digest(["request", arm]),
               "objective_digest": digest("fixed goal"), "producer_id": "policy",
               "status": "Succeeded", "split": "held_out", "window": "future_1", "task_family": TASKS[0],
               "root_source_ids": ["test-source"], "training_root_source_ids": ["train-source"],
               "information_digest": digest("same observations"), "training_dataset_digest": digest("same training data"),
               "common_budget": budget, "common_budget_digest": digest(budget),
               "activation_trace": [event(0)], "external_cost_price": .1,
               "work_ledger": [{"physical_work_id": arm + "/job", "phase": "inference", "wall_seconds": .2, "cpu_seconds": .1}]}
        predictions.append(row)
        outcomes.append({"case_id": row["case_id"], "arm": arm, "terminal": True, "censored": False,
                         "observer_role": "external_result_owner", "observer_id": "independent-fixture",
                         "correct": True, "request_digest": row["request_digest"], "objective_digest": row["objective_digest"]})
    return predictions, outcomes


class JsonAndJournalTests(unittest.TestCase):
    def test_duplicate_json_rejected(self):
        with self.assertRaises(ValueError): strict_loads('{"a":1,"a":2}')

    def test_nonfinite_json_rejected(self):
        for raw in ('{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError): strict_loads(raw)

    def test_nested_duplicate_rejected(self):
        with self.assertRaises(ValueError): strict_loads('{"x":{"a":1,"a":2}}')

    def test_canonical_order(self):
        self.assertEqual(digest({"b":2,"a":1}), digest({"a":1,"b":2}))

    def test_write_once(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.json'; write_once(p, {"value":1}); original=p.read_bytes()
            with self.assertRaises(FileExistsError): write_once(p, {"value":2})
            self.assertEqual(original,p.read_bytes())

    def test_invalid_write_creates_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.json'
            with self.assertRaises(ValueError): write_once(p, {"x":float('nan')})
            self.assertFalse(p.exists())

    def test_symlink_read_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'original';p.write_text('valid'); link=Path(d)/'link';link.symlink_to(p)
            with self.assertRaises(ValueError): read_bytes(link)

    def test_blank_jsonl_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'rows';p.write_text('{"a":1}\n\n')
            with self.assertRaises(ValueError): read_jsonl(p)

    def test_prelabel_journal_replay(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'journal'
            with PredictionJournal(p) as j:
                token=j.seal({"case_id":"one","p":[.2,.8]});j.before_label_reveal("one",token)
                with self.assertRaises(ValueError): j.before_label_reveal("one",token)
            self.assertEqual(verify_journal(read_jsonl(p)),1)

    def test_journal_label_leak_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with PredictionJournal(Path(d)/'j') as j:
                with self.assertRaises(ValueError): j.seal({"case_id":"one","nested":{"label":1}})

    def test_journal_duplicate_case(self):
        with tempfile.TemporaryDirectory() as d:
            with PredictionJournal(Path(d)/'j') as j:
                j.seal({"case_id":"one"})
                with self.assertRaises(ValueError): j.seal({"case_id":"one"})

    def test_journal_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'j'
            with PredictionJournal(p) as j: j.seal({"case_id":"one"})
            rows=read_jsonl(p);rows[0]['prediction']['case_id']='other'
            with self.assertRaises(ValueError): verify_journal(rows)

    def test_journal_reordered(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'j'
            with PredictionJournal(p) as j:
                j.seal({"case_id":"one"});j.seal({"case_id":"two"})
            with self.assertRaises(ValueError): verify_journal(read_jsonl(p)[::-1])

    def test_bound_artifact(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a';p.write_bytes(b'content')
            entry={'path':'a','sha256':hashlib.sha256(b'content').hexdigest()}
            self.assertEqual(bound_path(Path(d),entry),p)
            p.write_bytes(b'changed')
            with self.assertRaises(ValueError): bound_path(Path(d),entry)

    def test_artifact_escape(self):
        with self.assertRaises(ValueError): bound_path(Path('/tmp'),{'path':'../escape','sha256':digest(1)})


class NumericalTests(unittest.TestCase):
    def test_probabilities(self):
        for p in ([True,0],[-.1,1.1],[.2,.2],[float('nan'),1]):
            with self.subTest(p=p),self.assertRaises(ValueError): probabilities(p)

    def test_brier_ece(self):
        x=metrics([[.2,.8],[.9,.1]],[1,0])
        self.assertEqual(x['accuracy'],1)
        self.assertAlmostEqual(x['normalized_brier'],.025)
        self.assertAlmostEqual(x['ece15'],.15)

    def test_latency_is_request_quantile(self):
        x=latency([1,2,3,100]);self.assertAlmostEqual(x['p99_ms'],97.09)

    def test_parallel_depth_is_not_sum(self):
        x=causal_depth([event(0),event(1),event(2,['0','1'])])
        self.assertEqual(x['sequential_cell_depth'],2);self.assertEqual(x['actual_activations'],3)

    def test_retry_is_not_learning_depth(self):
        x=causal_depth([event(0),event(1,['0'],'retry'),event(2,['1'],'guard')])
        self.assertEqual(x['sequential_cell_depth'],1);self.assertEqual(x['retries'],1)

    def test_future_causal_parent(self):
        with self.assertRaises(ValueError): causal_depth([event(0,['1']),event(1,['0'])])

    def test_duplicate_activation(self):
        a,b=event(0),event(1,['0']);b['activation_id']=a['activation_id']
        with self.assertRaises(ValueError): causal_depth([a,b])

    def test_transitive_source_clustering(self):
        rows=[{'root_source_ids':['a']},{'root_source_ids':['a','b']},{'root_source_ids':['b']},{'root_source_ids':['c']}]
        self.assertEqual(sorted(map(len,components(rows))),[1,3])

    def test_correlated_calls_do_not_create_effective_n(self):
        rows=[{'case_id':str(i),'root_source_ids':['same'],'external_scores':{'a':1,'b':0}} for i in range(80)]
        x=paired_interval(rows,'a','b',draws=1000)
        self.assertEqual(x['source_components'],1);self.assertFalse(x['positive_diagnostic'])

    def test_paired_swap_sign(self):
        rows=[{'case_id':str(i),'root_source_ids':[str(i)],'external_scores':{'a':.6,'b':.1}} for i in range(30)]
        a=paired_interval(rows,'a','b',draws=1000);b=paired_interval(rows,'b','a',draws=1000)
        self.assertAlmostEqual(a['difference'],-b['difference'])

    def test_no_outcome_imputation(self):
        with self.assertRaises(ValueError): paired_interval([{'case_id':'1','root_source_ids':['a'],'external_scores':{'a':1}}],'a','b',draws=1000)

    def test_physical_work_dedup(self):
        row={'physical_work_id':'shared','phase':'training','wall_seconds':2.,'cpu_seconds':1.}
        x=work_totals([row,row]);self.assertEqual(x['unique_jobs'],1);self.assertEqual(x['total_cpu_seconds'],1.)

    def test_physical_work_conflict(self):
        a={'physical_work_id':'shared','phase':'training','wall_seconds':2.,'cpu_seconds':1.}
        with self.assertRaises(ValueError): work_totals([a,dict(a,cpu_seconds=2.)])

    def test_unknown_work_phase(self):
        with self.assertRaises(ValueError): work_totals([{'physical_work_id':'a','phase':'free','wall_seconds':0,'cpu_seconds':0}])

    def test_zero_risk_is_expectation(self):
        self.assertAlmostEqual(risk_ce([0,1],[.25,.75],0),.75)

    def test_risk_monotonicity(self):
        self.assertLess(risk_ce([0,1],[.5,.5],2),risk_ce([0,1],[.5,.5],1))

    def test_risk_translation(self):
        self.assertAlmostEqual(risk_ce([4,5],[.5,.5],2),4+risk_ce([0,1],[.5,.5],2))

    def test_risk_invalid_covariance_law(self):
        with self.assertRaises(ValueError): risk_ce([0,1],[.1,.1],1)

    def test_generic_ndu_equivalence(self):
        for risk in (0,.01,1,20):
            for gamma in (.7,1):
                with self.subTest(risk=risk,gamma=gamma):
                    a,_=recursive_value(tree(),'root',risk=risk,discount=gamma)
                    b=generic_nested_risk(tree(),'root',risk=risk,discount=gamma)
                    self.assertAlmostEqual(a,b,places=12)

    def test_recursive_cost_charged_once(self):
        x={'root':{'actions':[{'id':'a','cost':.2,'duration':2,'successors':[{'node':'t','probability':1.}]}]},'t':{'terminal':1.}}
        value,_=recursive_value(x,'root',risk=0,discount=.9);self.assertAlmostEqual(value,.61)

    def test_recursive_cycle(self):
        x=tree();x['root']['actions'][0]['successors'][0]['node']='root'
        with self.assertRaises(ValueError): recursive_value(x,'root',risk=1)

    def test_negative_resource_cost(self):
        x=tree();x['root']['actions'][0]['cost']=-1
        with self.assertRaises(ValueError): recursive_value(x,'root',risk=1)

    def test_duplicate_action(self):
        x=tree();x['root']['actions'][1]['id']='safe'
        with self.assertRaises(ValueError): recursive_value(x,'root',risk=1)


class ReviewTests(unittest.TestCase):
    def test_frozen_plan(self):
        self.assertEqual(validate_plan(default_plan()),digest(default_plan()))

    def test_plan_cannot_drop_zero_repeat(self):
        p=default_plan();p['input_repeat_fractions']=[.5,.9]
        with self.assertRaises(ValueError): validate_plan(p)

    def test_plan_cannot_relax_multiplicity(self):
        p=default_plan();p['planned_comparisons']=1
        with self.assertRaises(ValueError): validate_plan(p)

    def test_plan_unknown_field(self):
        p=default_plan();p['skip_failing_models']=True
        with self.assertRaises(ValueError): validate_plan(p)

    def test_compute_same_stem_allowed_without_promoting(self):
        r=review_compute(compute_rows(),default_plan())
        self.assertTrue(r['accounting_precheck']);self.assertFalse(r['matrix_complete']);self.assertFalse(r['production_promotion_permitted'])

    def test_missing_compute_arm(self):
        with self.assertRaises(ValueError): review_compute(compute_rows()[:2],default_plan())

    def test_compute_phantom_calls(self):
        x=compute_rows();x[2]['encoded_samples']=0
        with self.assertRaises(ValueError): review_compute(x,default_plan())

    def test_compute_reuse_conservation(self):
        x=compute_rows();x[2]['cache_hits']=64
        with self.assertRaises(ValueError): review_compute(x,default_plan())

    def test_compute_unticked_logical_cells(self):
        x=compute_rows();x[0]['ticked_cell_ids']=x[0]['ticked_cell_ids'][:-1]
        with self.assertRaises(ValueError): review_compute(x,default_plan())

    def test_compute_p99_without_samples(self):
        x=compute_rows();x[0]['request_latencies_ms']=[];x[0]['p99_ms']=1
        with self.assertRaises(ValueError): review_compute(x,default_plan())

    def test_compute_unpaired_workload(self):
        x=compute_rows();x[2]['workload_digest']=digest('different')
        with self.assertRaises(ValueError): review_compute(x,default_plan())

    def test_compute_cumulative_rss_rejected(self):
        x=compute_rows();x[2]['isolated_process_measurement']=False
        with self.assertRaises(ValueError): review_compute(x,default_plan())

    def test_behavior_census(self):
        p,o=behavior_rows();cases,_=behavior_census(p,o,default_plan(),('single_step','fixed_depth','matched_budget_feedforward'),'reasoning')
        self.assertEqual(len(cases),1)

    def test_behavior_missing_failed_arm_not_dropped(self):
        p,o=behavior_rows();o.pop()
        with self.assertRaises(ValueError): behavior_census(p,o,default_plan(),('single_step','fixed_depth','matched_budget_feedforward'),'reasoning')

    def test_behavior_observer_separate(self):
        p,o=behavior_rows();o[0]['observer_id']='policy'
        with self.assertRaises(ValueError): behavior_census(p,o,default_plan(),('single_step','fixed_depth','matched_budget_feedforward'),'reasoning')

    def test_behavior_prediction_cannot_self_reward(self):
        p,o=behavior_rows();p[0]['utility']=1
        with self.assertRaises(ValueError): behavior_census(p,o,default_plan(),('single_step','fixed_depth','matched_budget_feedforward'),'reasoning')

    def test_behavior_training_leakage(self):
        p,o=behavior_rows();p[0]['training_root_source_ids']=['test-source']
        with self.assertRaises(ValueError): behavior_census(p,o,default_plan(),('single_step','fixed_depth','matched_budget_feedforward'),'reasoning')

    def test_behavior_budget_binding(self):
        p,o=behavior_rows();p[0]['common_budget_digest']=digest('other')
        with self.assertRaises(ValueError): behavior_census(p,o,default_plan(),('single_step','fixed_depth','matched_budget_feedforward'),'reasoning')

    def test_behavior_censoring_not_zero(self):
        p,o=behavior_rows();o[0]['censored']=True
        with self.assertRaises(ValueError): behavior_census(p,o,default_plan(),('single_step','fixed_depth','matched_budget_feedforward'),'reasoning')

    def test_behavior_failed_correct_rejected(self):
        p,o=behavior_rows();p[0]['status']='Failed'
        with self.assertRaises(ValueError): behavior_census(p,o,default_plan(),('single_step','fixed_depth','matched_budget_feedforward'),'reasoning')

    def test_behavior_failed_false_retained(self):
        p,o=behavior_rows();p[0]['status']='Failed';o[0]['correct']=False
        _,meta=behavior_census(p,o,default_plan(),('single_step','fixed_depth','matched_budget_feedforward'),'reasoning')
        self.assertEqual(meta['attempt_statuses']['Failed'],1)

    def test_cell_bridge_requires_original_artifacts(self):
        with self.assertRaises(ValueError): review_cell({},Path('/tmp'),default_plan())


class AdditionalInputIntegrityTests(unittest.TestCase):
    def test_nested_bool_cannot_alias_one(self):
        plan = default_plan()
        plan["depths"][0] = True
        with self.assertRaises(ValueError):
            validate_plan(plan)

    def test_missing_none_prelabel_token_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with PredictionJournal(Path(tmp) / "prelabel.jsonl") as journal:
                with self.assertRaises(ValueError):
                    journal.before_label_reveal("unseen", None)


if __name__ == '__main__': unittest.main()
