"""Synthetic only: qualify source/label identity and zero temporal overclaims."""
import copy
import unittest
from unittest.mock import patch

import public_agnews_confirmatory as c
from public_agnews_panel import canonical, select_rows, sha


def inputs():
    original = select_rows(
        [{"text": f"Train {i} topic {i%2}", "label": i%2} for i in range(400)],
        [{"text": f"Old val1 {i} topic {i%2}", "label": i%2} for i in range(400)])
    new = [{"text": f"Fresh val2 record {i} theme {i%2}", "label": i%2}
           for i in range(400)]
    return original, new


class ConfirmatorySource(unittest.TestCase):
    def test_repeatable_source_only_selection_and_disjoint(self):
        old, newer = inputs()
        with patch.object(c,"SOURCE_PANEL_SHA256",sha(canonical(old))):
            x=c.create_panel(old,newer)
            y=c.create_panel(old,list(reversed(newer)))
            self.assertEqual(canonical(x),canonical(y))
            self.assertEqual(c.check_panel(x,old)[0],sha(canonical(x)))
            self.assertEqual(x["case_count"],128)
            self.assertEqual(sum(z["label"] for z in x["cases"]),64)
            self.assertFalse(x["selection_uses_model_predictions"])
            self.assertFalse(x["chronological_future_claim"])
            self.assertFalse(x["foundation_pretraining_overlap_ruled_out"])
            self.assertEqual(x["production_promotion"],"DENY_ALL")
            self.assertFalse(set(z["source_digest"] for z in x["cases"]) &
                             set(z["source_digest"] for z in old["cases"]))

    def test_tampering_missing_labels_and_authority_fails(self):
        old, newer=inputs()
        with patch.object(c,"SOURCE_PANEL_SHA256",sha(canonical(old))):
            baseline=c.create_panel(old,newer)
            for kind in ("future","overlap","source","label","duplicate","reorder"):
                attempt=copy.deepcopy(baseline)
                if kind=="future":attempt["chronological_future_claim"]=True
                elif kind=="overlap":attempt["cases"][0]=copy.deepcopy(old["cases"][0]);attempt["cases"][0]["split"]="new_holdout"
                elif kind=="source":attempt["cases"][0]["source_digest"]="0"*64
                elif kind=="label":attempt["cases"][0]["label"]=3
                elif kind=="duplicate":attempt["cases"][1]=copy.deepcopy(attempt["cases"][0])
                else:attempt["cases"].reverse()
                with self.subTest(kind=kind),self.assertRaises(c.ConfirmatoryError):
                    c.check_panel(attempt,old)

    def test_new_holdout_must_supply_both_classes_without_replays(self):
        old,new=inputs()
        with patch.object(c,"SOURCE_PANEL_SHA256",sha(canonical(old))):
            with self.assertRaises(c.ConfirmatoryError):
                c.create_panel(old,[r for r in new if r["label"]==1])
            with self.assertRaises(c.ConfirmatoryError):
                c.create_panel(old,[dict(r,text="same source" if i%2==0 else r["text"])
                                   for i,r in enumerate(new[:8])])
            bad=list(new)
            bad.append({"text":new[0]["text"],"label":1-new[0]["label"]})
            with self.assertRaises(c.ConfirmatoryError):c.create_panel(old,bad)

    def test_frozen_baseline_binding_is_nonoptional(self):
        old,new=inputs()
        with self.assertRaises(c.ConfirmatoryError):c.create_panel(old,new)


if __name__=="__main__":unittest.main()
