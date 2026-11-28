"""Independent reference comparison for CIDEr-D and hand-computable BLEU/ROUGE examples."""
import json
from pathlib import Path
import numpy as np
from metrics import CaptionMetrics
from qa_reference_cider import CiderScorer


def run():
    refs=[[s.split() for s in group] for group in [
        ["a long blue road","a long blue road","a green lake"],["houses surround a square field","many houses and a road"],
        ["four cars in a long line","four cars on a road"],["two airports are visible","the large airport runway"]]]
    cases=[]
    for pred in [[r[0] for r in refs],["a long road".split(),[],["cars"],"two airports are visible".split()]]:
        scorer=CiderScorer()
        for h,rs in zip(pred,refs):scorer+=(" ".join(h),[" ".join(r) for r in rs])
        _,true=scorer.compute_score()
        result,by=CaptionMetrics(refs).evaluate(pred)
        worst=float(np.max(np.abs(true-by["cider_d"])))
        if worst>1e-12:raise ValueError(worst)
        cases.append(dict(worst_abs_cider_d=worst,summary=result))
    assert cases[0]["summary"]["bleu4"]==1 and cases[0]["summary"]["rouge_l"]==1
    assert cases[1]["summary"]["empty"]==1
    return dict(reference_blob="94d66893f9d1a6aa2c027c76de6bea0cdee8cdf8",cases=cases)

if __name__=="__main__":
    result=run();Path(__file__).with_name("metrics_verification.json").write_text(json.dumps(result,indent=2)+"\n")
