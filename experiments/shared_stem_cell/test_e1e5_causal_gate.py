"""Isolated mechanism tests; synthetic fixtures are not empirical model evidence."""
import copy,importlib.util,pathlib,tempfile,unittest
p=pathlib.Path(__file__).with_name("e1e5_causal_gate.py")
spec=importlib.util.spec_from_file_location("causal",p);g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
H="a"*64
def fixture(stage):
 cases=[]
 for i,(part,reader) in enumerate(zip(g.SPLITS,("none","retrieved","sufficient","premise_removed","sufficient","sufficient","retrieved"))):
  c={"case_id":f"c{i}","scope":"s","source_group":f"g{i}","input_sha256":f"{i+1:064x}","split":part,
   "modality":"video" if stage=="E4" else "text","observed_at":i+1,"reader_condition":reader,"reader_correct":True,"answer_label":i%2}
  if stage=="E4":c.update(counterfactual_pair_id="pair",frame_order_sha256=H)
  cases.append(c)
 resources={k:1 for k in g.COSTS}
 arms=[{"name":n,"model_sha256":H,"head_sha256":H,"actual_model_forward":True,"reader_invocations":0,
 "resources":resources.copy(),"predictions":[{"case_id":c["case_id"],"input_sha256":c["input_sha256"],"prelabel_sealed":True,
 "positive_probability":.9 if c["answer_label"] else .1} for c in cases]} for n in sorted(g.STAGES[stage])]
 return {"schema":g.SCHEMA,"stage":stage,"source_tree_sha256":H,"dataset_sha256":H,"plan_sha256":H,
 "evaluator_sha256":H,"scope":"s","authority":"DENY_ALL","production_promotion_permitted":False,
 "cases":cases,"arms":arms,"logical_cells":64,"active_cells":5}
class Tests(unittest.TestCase):
 def rejects(self,modify,stage="E1"):
  d=fixture(stage);modify(d)
  with self.assertRaises((ValueError,TypeError,KeyError)):g.audit(d)
 def test_each_stage_synthetic_mechanism(self):
  for stage in g.STAGES:
   with self.subTest(stage=stage):
    result=g.audit(fixture(stage))
    self.assertEqual(set(result["arms"]),g.STAGES[stage])
    self.assertFalse(result["production_promotion_permitted"])
    self.assertFalse(result["outcome_and_cost_independently_authenticated"])
 def test_duplicate_control(self):self.rejects(lambda d:d["arms"].append(copy.deepcopy(d["arms"][0])))
 def test_missing_control(self):self.rejects(lambda d:d["arms"].pop())
 def test_source_leakage(self):self.rejects(lambda d:d["cases"][2].update(source_group="g0"))
 def test_raw_input_reuse(self):self.rejects(lambda d:d["cases"][2].update(input_sha256=d["cases"][0]["input_sha256"]))
 def test_time_travel(self):self.rejects(lambda d:d["cases"][3].update(observed_at=1.5))
 def test_missing_reader(self):self.rejects(lambda d:[c.update(reader_condition="retrieved") for c in d["cases"] if c["reader_condition"]=="sufficient"])
 def test_reader_failure_does_not_claim_adequacy(self):
  d=fixture("E1");d["cases"][2]["reader_correct"]=False
  self.assertFalse(g.audit(d)["reader_adequacy_on_supplied_sufficient_cases"])
 def test_missing_energy(self):self.rejects(lambda d:d["arms"][0]["resources"].pop("energy_joules"))
 def test_unknown_resource(self):self.rejects(lambda d:d["arms"][0]["resources"].update(fake=0))
 def test_false_physical_execution(self):self.rejects(lambda d:d["arms"][0].update(actual_model_forward=False))
 def test_unsealed_prediction(self):self.rejects(lambda d:d["arms"][0]["predictions"][0].update(prelabel_sealed=False))
 def test_swapped_prediction(self):self.rejects(lambda d:d["arms"][0]["predictions"][0].update(input_sha256=H))
 def test_missing_prediction(self):self.rejects(lambda d:d["arms"][0]["predictions"].pop())
 def test_nan_probability(self):self.rejects(lambda d:d["arms"][0]["predictions"][0].update(positive_probability=float("nan")))
 def test_forbidden_authority(self):self.rejects(lambda d:d.update(production_promotion_permitted=True))
 def test_bad_e5_coverage(self):self.rejects(lambda d:d.update(active_cells=65),"E5")
 def test_missing_e4_order(self):self.rejects(lambda d:d["cases"][0].pop("frame_order_sha256"),"E4")
 def test_json_duplicate_and_nan(self):
  with tempfile.TemporaryDirectory() as tmp:
   file=pathlib.Path(tmp)/"bad.json"
   for raw in ('{"a":1,"a":2}','{"a":NaN}'):
    file.write_text(raw)
    with self.assertRaises(ValueError):g.read(file)
if __name__=="__main__":unittest.main()
