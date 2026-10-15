"""Model-free fault injections. Synthetic data are not model success evidence."""
import copy,importlib.util,pathlib,tempfile,unittest,json
p=pathlib.Path(__file__).with_name('e1e5_confirmatory_review.py')
spec=importlib.util.spec_from_file_location('reviewer',p)
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
H='a'*64

def fixture(stage='E1',big=False):
    cases=[]
    groups_per_split=50 if big else 2
    for sidx,split in enumerate(g.SPLITS):
        for i in range(groups_per_split):
            idx=len(cases)
            cases.append(dict(case_id=f'c{idx}',scope='s',split=split,modality='text',
                              source_group=f'g{sidx}-{i}',input_sha256=f'{idx+1:064x}',observed_at=10*sidx+i/(groups_per_split+1)+1,
                              reader_condition='sufficient',reader_correct=True,answer_label=i%2))
    resources={k:1 for k in ('load_ms','encode_ms','bridge_fit_ms','head_train_ms','cache_ms','migration_ms','recompute_ms','serving_ms','evaluation_ms','checkpoint_ms','peak_rss_bytes','cpu_ms','gpu_ms','energy_joules','throughput_per_sec','p95_ms','p99_ms')}
    armnames={nm for cand,controls in g.STAGE_COMPARISONS[stage].items() for nm in (cand,*controls)}
    arms=[]
    for name in sorted(armnames):
        predictions=[]
        for c in cases:
            good='head' in name or name.startswith('residual') or name in ('learned_bridge','native_multimodal','audio_bridge','temporal_adapter','shared_stem')
            if name=='frozen_head':good=False
            prob=(.9 if c['answer_label']==1 else .1) if good else (.1 if c['answer_label']==1 else .9)
            predictions.append(dict(case_id=c['case_id'],input_sha256=c['input_sha256'],prelabel_sealed=True,positive_probability=prob))
        arms.append(dict(name=name,model_sha256=H,head_sha256=H,actual_model_forward=True,reader_invocations=0,resources=resources.copy(),predictions=predictions,
             trainable_parameters=1024,optimizer_steps=40,initial_prediction_matches_baseline=True))
    obs=dict(schema=g.OBS_SCHEMA,stage=stage,authority='DENY_ALL',production_promotion_permitted=False,
             source_tree_sha256=H,dataset_sha256=H,plan_sha256=H,evaluator_sha256=H,scope='s',
             observer_producer_id='model_pipeline',cases=cases,arms=arms,logical_cells=64,active_cells=2,
             encoder_candidate='granite_97m_r2',feature_width=384,pooling_profile='cls_l2',upstream_revision='b'*40,tokenizer_sha256=H)
    outcome=dict(schema=g.OUT_SCHEMA,dataset_sha256=H,plan_sha256=H,producer_id='gold_label_owner',
                  rows=[dict(case_id=c['case_id'],source_group=c['source_group'],input_sha256=c['input_sha256'],
                             split=c['split'],observed_at=c['observed_at'],label=c['answer_label'],outcome_sha256=H) for c in cases])
    trials=[]
    for case in cases[2:4]:
        task=case['case_id']
        for j,condition in enumerate(g.READER_CONDITIONS):
            r=dict(task_id=task,condition=condition,task_input_sha256=case['input_sha256'],reader_model_sha256=H,
                   prompt_template_sha256=H,budget_tokens=512,seed=1,source_group=case['source_group'],
                   input_sha256=f'{j+100+(0 if task=="c2" else 20):064x}',answer_sha256=H,
                   correct=(condition=='sufficient'),abstained=False)
            if condition=='sufficient':r.update(reviewed_sufficient_evidence_sha256=H,independent_reviewer_id='reviewerA')
            if condition=='premise_removed':r.update(removed_critical_premise_sha256=H)
            trials.append(r)
    reader=dict(schema=g.READER_SCHEMA,trials=trials)
    return obs,outcome,reader

class ReviewTest(unittest.TestCase):
    def deny(self,change,stage='E1'):
        doc=fixture(stage);change(*doc)
        with self.assertRaises((g.Invalid,ValueError,TypeError,KeyError)):
            g.review(*doc)
    def test_all_stages_mechanism_only(self):
        for stage in g.STAGE_COMPARISONS:
            with self.subTest(stage=stage):
                o,out,r=fixture(stage)
                if stage=='E4':
                    # E4 requires exactly paired videos
                    c0,c1=o['cases'][0],o['cases'][1]
                    for c in (c0,c1):
                        c.update(modality='video',counterfactual_pair_id='reverse1',frame_content_multiset_sha256=H)
                    c0['frame_order_sha256']='1'*64;c1['frame_order_sha256']='2'*64
                    c1['source_group']=c0['source_group'];out['rows'][1]['source_group']=c0['source_group']
                    c1['answer_label']=1-c0['answer_label'];out['rows'][1]['label']=c1['answer_label']
                if stage=='E5':
                    o['worker_trace']=dict(worker_receipt_type='research_unverified_worker_trace_v1',stem_sha256=H,target_host_sha256=H,
                                            requests=[dict(request_id='r1',cell_id='cell1',scope='s',generation=1,input_sha256=H,forward_id='forward1',backend_batch_id='batch1',final_use_checked=True,cache_hit=False),
                                                      dict(request_id='r2',cell_id='cell2',scope='s',generation=1,input_sha256=H,forward_id='forward1',backend_batch_id='batch1',final_use_checked=True,cache_hit=True)])
                ans=g.review(o,out,r)
                self.assertFalse(ans['production_promotion_permitted'])
                self.assertFalse(ans['model_weights_and_forwards_independently_verified'])
    def test_independent_producer_separation(self):
        self.deny(lambda o,out,r:out.update(producer_id='model_pipeline'))
    def test_missing_energy(self):
        self.deny(lambda o,out,r:o['arms'][0]['resources'].pop('energy_joules'))
    def test_p99_below_p95(self):
        self.deny(lambda o,out,r:o['arms'][0]['resources'].update(p99_ms=0.5))
    def test_e2_encoder_drift(self):
        self.deny(lambda o,out,r:o['arms'][0].update(model_sha256='b'*64),'E2')
    def test_e1_pooling_profile(self):
        self.deny(lambda o,out,r:o.update(pooling_profile='mean_l2'),'E1')
    def test_e2_head_budget(self):
        def change(o,out,r):
            next(a for a in o['arms'] if a['name']=='residual_2k')['trainable_parameters']=2049
        self.deny(change,'E2')
    def test_unbound_reader_task(self):
        self.deny(lambda o,out,r:[t.update(task_input_sha256='b'*64) for t in r['trials'][:4]])
    def test_tampered_label(self):
        self.deny(lambda o,out,r:out['rows'][0].update(label=1-out['rows'][0]['label']))
    def test_missing_outcome(self):
        self.deny(lambda o,out,r:out['rows'].pop())
    def test_repeated_outcome(self):
        self.deny(lambda o,out,r:out['rows'].__setitem__(1,copy.deepcopy(out['rows'][0])))
    def test_plan_swap(self):
        self.deny(lambda o,out,r:out.update(plan_sha256='b'*64))
    def test_reader_missing_condition(self):
        self.deny(lambda o,out,r:r['trials'].pop())
    def test_reader_changed_model(self):
        self.deny(lambda o,out,r:r['trials'][0].update(reader_model_sha256='b'*64))
    def test_reader_missing_review(self):
        self.deny(lambda o,out,r:r['trials'][2].pop('independent_reviewer_id'))
    def test_reader_duplicate_group(self):
        self.deny(lambda o,out,r:[t.update(source_group='g0-0') for t in r['trials'][4:]])
    def test_reader_sufficient_failure_reported(self):
        o,out,r=fixture();r['trials'][2]['correct']=False
        result=g.review(o,out,r)
        self.assertFalse(result['reader']['all_sufficient_correct'])
    def test_prediction_swap(self):
        self.deny(lambda o,out,r:o['arms'][0]['predictions'][0].update(input_sha256='b'*64))
    def test_cross_window_raw_input(self):
        self.deny(lambda o,out,r:o['cases'][2].update(input_sha256=o['cases'][0]['input_sha256']))
    def test_never_authorize(self):
        self.deny(lambda o,out,r:o.update(production_promotion_permitted=True))
    def test_underpowered_future(self):
        o,out,r=fixture();res=g.review(o,out,r)
        self.assertIsNone(res['comparisons'][0]['windows'][0]['lcb_accuracy_gain'])
    def test_powered_future_bootstrap(self):
        o,out,r=fixture(big=True);res=g.review(o,out,r)
        for cmp in res['comparisons']:
            for w in cmp['windows']:
                self.assertEqual(w['independent_groups'],50)
                self.assertGreater(w['lcb_accuracy_gain'],0)
        self.assertFalse(res['all_acceptance_gates_passed'])
    def test_duplicate_keys_and_nan(self):
        with tempfile.TemporaryDirectory() as tmp:
            x=pathlib.Path(tmp)/'bad.json'
            for text in ('{"a":1,"a":2}','{"a":NaN}'):
                x.write_text(text)
                with self.assertRaises(g.Invalid):g.load(x)
    def test_temporal_identical_orders(self):
        def change(o,out,r):
            c=o['cases'][0];c.update(modality='video',counterfactual_pair_id='same',frame_content_multiset_sha256=H,frame_order_sha256=H)
        self.deny(change,'E4')
    def test_temporal_identical_labels(self):
        def change(o,out,r):
            a,b=o['cases'][:2]
            for c in (a,b):c.update(modality='video',counterfactual_pair_id='same',frame_content_multiset_sha256=H)
            a['frame_order_sha256']='1'*64;b['frame_order_sha256']='2'*64
            b['source_group']=a['source_group'];out['rows'][1]['source_group']=a['source_group']
            b['answer_label']=a['answer_label'];out['rows'][1]['label']=a['answer_label']
        self.deny(change,'E4')
    def test_scale_false_cache(self):
        def change(o,out,r):
            o['worker_trace']=dict(worker_receipt_type='research_unverified_worker_trace_v1',stem_sha256=H,target_host_sha256=H,
              requests=[dict(request_id=f'r{i}',cell_id=f'c{i}',scope='s',generation=1,input_sha256=H,
                              forward_id='forward1',backend_batch_id='batch1',final_use_checked=True,cache_hit=True) for i in (1,2)])
        self.deny(change,'E5')
    def test_scale_cross_scope_reuse(self):
        def change(o,out,r):
            o['worker_trace']=dict(worker_receipt_type='research_unverified_worker_trace_v1',stem_sha256=H,target_host_sha256=H,
              requests=[dict(request_id='r1',cell_id='c1',scope='s',generation=1,input_sha256=H,forward_id='f1',backend_batch_id='batch1',final_use_checked=True,cache_hit=False),
                        dict(request_id='r2',cell_id='c2',scope='other',generation=1,input_sha256=H,forward_id='f1',backend_batch_id='batch1',final_use_checked=True,cache_hit=True)])
        self.deny(change,'E5')

if __name__=='__main__':unittest.main()
