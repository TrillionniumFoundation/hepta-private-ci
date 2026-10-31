"""Once-only verification statistics; source pairs retain both future branches."""

import argparse
import json
from pathlib import Path

import numpy as np

from ...abc_recovery.training_run import file_sha, write_json
from .forecast import ACTIONS, Q, predict, runtime_predictions
from .qualify import check_freeze, load, stats
from .boundaries import verified_data


def interval(values, rng, count=4000):
    values = np.asarray(values)
    sampled = np.array([values[rng.integers(0,len(values),len(values))].mean() for _ in range(count)])
    return np.quantile(sampled,[.025,.975]).tolist()


def source_mean(values, pair):
    return np.asarray([values[pair==key].mean() for key in np.unique(pair)])


def ece_interval(probability, labels, pair, rng):
    ids=np.unique(pair);bins=np.minimum((probability*10).astype(int),9)
    differences=np.asarray([[np.sum((labels-probability)[(pair==key)&(bins==j)])
                            for j in range(10)] for key in ids])
    counts=np.asarray([(pair==key).sum() for key in ids])
    draws=[]
    for _ in range(4000):
        sample=rng.integers(0,len(ids),len(ids))
        draws.append(float(np.abs(differences[sample].sum(0)).sum()/counts[sample].sum()))
    return np.quantile(draws,[.025,.975]).tolist()


def verify(protocol, data, model, output):
    check_freeze(protocol,model,"calibrator-freeze.json")
    output.mkdir(parents=True,exist_ok=False)
    weights=json.loads((model/"weights.json").read_text())
    calibration=json.loads((model/"calibration.json").read_text())
    d=verified_data(data,protocol,"verification");x=d["x_q24"]/Q;future=d["future_q24"]/Q;past=d["past_q24"]/Q
    forecast,_,p,_,_,cp,op,_=runtime_predictions(weights,calibration,x,future)
    result=stats(weights,calibration,d); rng=np.random.default_rng(194017)
    learned=(forecast-future)**2; baseline=(past-future)**2
    pair=d["pair"]; advantage=source_mean((baseline-learned).mean(1),pair)
    result["ece_source_bootstrap_descriptive95"]={}
    for name,probability in (("prospective",p),("native",cp/1e6)):
        for subset,mask in (("full",np.ones(len(pair),dtype=bool)),("id",~d["ood"])):
            result["ece_source_bootstrap_descriptive95"][name+"_"+subset]=ece_interval(
                probability[mask],d["y"][mask],pair[mask],rng)
    result["primary"]={"contrast":"persistence MSE minus learned forecast MSE","advantage":float(advantage.mean()),
        "nominal_confidence":.95,"paired_source_interval":interval(advantage,rng),
        "independent_source_pairs":len(advantage),"bootstrap_draws":4000}
    result["primary"]["positive_lower_endpoint"]=result["primary"]["paired_source_interval"][0]>0
    descriptions={"all":np.ones(len(pair),dtype=bool),"id":~d["ood"],"complete_absence":d["ood"]}
    descriptions.update({name:d["action"]==i for i,name in enumerate(ACTIONS)})
    strata={}
    for name,mask in descriptions.items():
        mse_gain=source_mean((baseline[mask]-learned[mask]).mean(1),pair[mask])
        strata[name]={"pairs":len(mse_gain),"learned_mse":float(learned[mask].mean()),
            "persistence_mse":float(baseline[mask].mean()),"gain":float(mse_gain.mean()),
            "descriptive95":interval(mse_gain,rng),
            "image_learned_mse":float(learned[mask,:16].mean()),"image_persistence_mse":float(baseline[mask,:16].mean()),
            "text_learned_mse":float(learned[mask,16:].mean()),"text_persistence_mse":float(baseline[mask,16:].mean())}
    result["strata"]=strata
    errors=np.abs(forecast-future).max(1)
    coverage={}
    for ood in (False,True):
        ids=np.unique(pair[d["ood"]==ood]); radius=calibration["source_max_error_radius90"][str(ood)]
        maxima=np.asarray([errors[pair==key].max() for key in ids])
        source_errors=np.asarray([learned[pair==key].mean() for key in ids])
        covered=maxima<=radius
        coverage[str(ood)]={"source_pairs":len(ids),"calibration_radius":radius,
            "both_actions_all_coordinates_covered":int(covered.sum()),"coverage":float(covered.mean()),
            "descriptive95":interval(covered.astype(float),rng),
            "source_max_error_p50_p95_p99":np.quantile(maxima,[.5,.95,.99]).tolist(),
            "source_mse_cvar90":float(np.sort(source_errors)[-max(1,int(np.ceil(.1*len(ids)))):].mean())}
    result["calibrated_error_radius_verification"]=coverage
    before=json.loads((model/"calibration-result.json").read_text())
    result["native_measured_ece_ppm"]=int(np.ceil(max(before["native_ece_id"],before["native_ece_full"],
            result["native_ece_id"],result["native_ece_full"])*1e6))
    result["native_measured_false_acceptance_ppm"]=int(np.ceil(max(before["native_ood_false_acceptance_pair_rate"],
            result["native_ood_false_acceptance_pair_rate"])*1e6))
    result["native_config_point_qualified"]=(result["native_measured_ece_ppm"]<=30000
            and result["native_measured_false_acceptance_ppm"]<=4999)
    result.update({"schema":"hepta.abc4.future-verification.v1","protocol_sha256":file_sha(protocol),
        "calibrator_freeze_sha256":file_sha(model/"calibrator-freeze.json"),"data_sha256":file_sha(data/"data.npz"),
        "independence":"one original image source pair, two futures clustered; no additional independent N from native replay",
        "scope":"fixed generator, two named future actions, constructed complete absence; not global dynamics or universal conditional guarantees"})
    write_json(output/"verification.json",result)
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("protocol","data","model","output"):p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args();verify(a.protocol,a.data,a.model,a.output)
