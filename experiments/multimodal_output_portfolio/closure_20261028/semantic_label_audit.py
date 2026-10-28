"""Training-metadata label coverage and exact-window ambiguity audit.

No new development/calibration/qualification prediction or pixel is read. The
fixed cohorts and adequacy thresholds are not changed by this diagnostic.
"""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path

from .data_sources import digest,save


def audit(root,output):
    plan=json.loads((Path(root)/"SOURCE_PROTOCOL.json").read_text())
    body=dict(plan);pin=body.pop("protocol_sha256")
    if digest(body)!=pin:raise ValueError("Frozen allocation changed")
    reports={}
    for role in ("generator_train","observer_train"):
        sources=[source for source in plan["selected"] if source["role"]==role]
        results={"sources":len(sources),"events":sum(source["retained_event_count"] for source in sources),"labels":{}}
        for kind in ("action","sound"):
            counts=Counter();source_mass=Counter();upper=0.;conflicts=[]
            for source in sources:
                events=source["events"][:source["retained_event_count"]]
                windows=defaultdict(Counter)
                for event in events:
                    label=event[kind+"_id"]
                    counts[label]+=1;source_mass[label]+=1/(len(sources)*len(events))
                    # This is exactly the decoder's shared frame/audio index.
                    windows[round(event["window_start_seconds"]*8)][label]+=1
                upper+=sum(max(labels.values()) for labels in windows.values())/(len(sources)*len(events))
                conflicts.extend({"source_id":source["source_id"],"first_frame_index":first,"labels":dict(labels)}
                                 for first,labels in windows.items() if len(labels)>1)
            majority=max(source_mass,key=source_mass.get)
            results["labels"][kind]={"published_ontology_classes":len(plan["ontology"][kind]),
                "present_training_classes":len(counts),"event_counts":dict(sorted(counts.items())),
                "source_uniform_class_mass":dict(sorted(source_mass.items())),
                "training_majority_label":majority,"training_majority_accuracy":source_mass[majority],
                "identical_window_conflicting_label_groups":len(conflicts),"conflicts":conflicts,
                "optimistic_deterministic_training_accuracy_upper_bound_from_exact_window_collisions":upper,
                "upper_bound_scope":"finite retained training metadata only; other visually/acoustically indistinguishable windows can lower this bound further"}
        reports[role]=results
    result={"schema":"hepta.closure.semantic-training-label-audit.v1","source_protocol_sha256":pin,
            "roles":reports,"only_training_metadata_read":True,"new_development_predictions":0,
            "new_calibration_predictions":0,"new_qualification_pixels_or_predictions":0,
            "source_selection_or_adequacy_thresholds_changed":False}
    save(output,result)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument('--assets',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();r=audit(args.assets,args.output)
    print({role:{kind:{key:value for key,value in report['labels'][kind].items() if key not in ('event_counts','source_uniform_class_mass','conflicts','upper_bound_scope')}
                 for kind in ('action','sound')} for role,report in r['roles'].items()})
