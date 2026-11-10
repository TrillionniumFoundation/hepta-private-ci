"""Offline audit of archived real-model execution; does NOT rerun model."""
import hashlib
import json
from pathlib import Path
import unittest
HERE=Path(__file__).resolve().parent

class RealCpuEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r=json.loads((HERE/"real_cpu_clock_v1_RESULT.json").read_text())

    def test_source_and_holds(self):
        r=self.r
        self.assertEqual(r["schema"],"HPCA-REAL-CPU-LORA-CLOCK-V1")
        self.assertEqual(r["authority"],"CANDIDATE_ONLY_DENY_ALL_HOLD_NO_GO")
        self.assertEqual(r["decision"],"HOLD_NO_GO")
        self.assertEqual(r["selection"],"NO_UPDATE_RECOMMENDED_NOT_OWNER_DECISION")
        self.assertEqual(r["identities"]["script_sha256"],hashlib.sha256(
            (HERE/"native_lora_clock.py").read_bytes()).hexdigest())
        self.assertIn("NOT independent",r["sources"])
        self.assertTrue(all(len(v)==64 for v in r["identities"].values()))
        for key in ("external independent B","2x2 NDU",
                    "seven lineage controllers","energy",
                    "host-cold owner recovery"):
            self.assertIn(key," ".join(r["not_measured"]))
        self.assertEqual(r["cpu_threads"],4)

    def test_fixed_roster_same_information_and_budget(self):
        r=self.r
        self.assertFalse(set(r["training_source_ids"]) & set(r["B_source_ids"]))
        self.assertEqual((len(r["seeds"]), len(set(r["seeds"]))), (4, 4))
        self.assertEqual(len(r["runs"]),8)
        self.assertEqual(sorted((x["seed"],x["arm"]) for x in r["runs"]),
                         sorted((s,a) for s in r["seeds"]
                                for a in ("uniform","heterogeneous")))
        for seed in r["seeds"]:
            pair={x["arm"]:x for x in r["runs"] if x["seed"]==seed}
            self.assertEqual(pair["uniform"]["all_source_events"],
                             pair["heterogeneous"]["all_source_events"])
            self.assertEqual(pair["uniform"]["input_tokens_train"],
                             pair["heterogeneous"]["input_tokens_train"])
            for arm,row in pair.items():
                self.assertEqual(row["steps"],12)
                self.assertEqual(len(row["step_log"]),12)
                self.assertEqual(row["all_source_events"],
                                 [x["source_id"] for x in row["step_log"]])
                self.assertTrue(set(row["all_source_events"])<=set(r["training_source_ids"]))
                self.assertEqual(row["schedule"].count(0),6 if arm=="uniform" else 9)
                self.assertEqual(row["schedule"].count(1),6 if arm=="uniform" else 3)
                self.assertEqual(row["equal_group_parameters"],{"0":69120,"1":69120})
                self.assertEqual(row["adapter_parameters_total"],138240)
                self.assertEqual(row["actual_updated_parameter_elements"],829440)
                self.assertGreater(row["process_cpu_seconds"],0)
                self.assertGreater(row["train_evaluate_save_reload_wall_seconds"],0)
                self.assertLessEqual(row["cold_reload_max_p_yes_difference"],1e-5)
                for section,count in (("calibration",4),("B_exposed_eval",4),
                                      ("C_operator_constructed",8)):
                    data=row["scores"][section]
                    self.assertEqual(len(data["rows"]),count)
                    self.assertEqual(data["accuracy"],
                                     sum(x["correct"] for x in data["rows"])/count)
                    self.assertTrue(all(x["correct"]==(x["truth"]==x["prediction"])
                                        and 0<=x["p_yes"]<=1 for x in data["rows"]))
                for section in ("B_exposed_eval","C_operator_constructed"):
                    old=row["scores"][section]["rows"]
                    new=row["cold_reloaded_scores"][section]["rows"]
                    self.assertEqual([(x["id"],x["prediction"]) for x in old],
                                     [(x["id"],x["prediction"]) for x in new])
                self.assertEqual(set(row["checkpoint_files"]),
                                 {"adapter_config.json","adapter_model.safetensors",
                                  "README.md"})
            diffs=next(x for x in r["paired_seed_deltas"] if x["seed"]==seed)
            for target,sec in (("B","B_exposed_eval"),("C","C_operator_constructed")):
                self.assertEqual(diffs["heterogeneous_minus_uniform_"+target+"_accuracy"],
                                 pair["heterogeneous"]["scores"][sec]["accuracy"]
                                 -pair["uniform"]["scores"][sec]["accuracy"])
        self.assertEqual(r["B_descriptive_mean_delta"],0)
        self.assertEqual(r["C_descriptive_mean_delta"],0)

if __name__=="__main__":
    unittest.main()
