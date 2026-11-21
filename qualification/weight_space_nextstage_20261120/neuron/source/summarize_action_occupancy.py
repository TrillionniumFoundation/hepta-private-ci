"""Descriptive occupancy from saved actions/edges; no model or optimizer calls."""
from pathlib import Path
import gzip,hashlib,json,math,time

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"v2/attempt001"


def read(path,expected=None):
    raw=path.read_bytes()
    if expected is not None and hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError("saved graph identity mismatch")
    return json.loads(gzip.decompress(raw) if path.suffix==".gz" else raw)


def occupancy(graph,arm):
    values=[0.]*len(graph["states"]);values[graph["initial"]]=1.
    for before in graph["order"]:
        action=graph["arm_actions"][arm][before]
        if action in (1,2,3):
            for probability,after,_ in graph["edges"][before][action-1]:
                if probability:values[after]+=values[before]*probability
    return values


def main():
    started=time.process_time();result={}
    for domain in ("iid","ood"):
        rows=[]
        for fit in (11,23,37,53,71):
            block=read(OUT/f"confirmation_{fit}_{domain}.json.gz")
            for record in block["records"]:
                graph=read(OUT/record["graph"],record["graph_sha256"])
                P_occupancy=occupancy(graph,"P")
                differences=[a!=b for a,b in zip(graph["arm_actions"]["RP"],graph["arm_actions"]["P"])]
                occupied=math.fsum(p for different,p in zip(differences,P_occupancy) if different)
                rows.append(dict(fit=fit,graph=record["graph"],graph_sha256=record["graph_sha256"],
                    support_states=len(differences),different_actions=sum(differences),
                    P_occupied_disagreement_mass=occupied,
                    P_occupied_disagreement_fraction=occupied/math.fsum(P_occupancy),
                    utility_delta=record["arms"]["RP"]["utility"]-record["arms"]["P"]["utility"]))
        result[domain]=dict(worlds=len(rows),support_states=sum(r["support_states"] for r in rows),
            different_actions=sum(r["different_actions"] for r in rows),
            worlds_with_action_difference=sum(r["different_actions"]>0 for r in rows),
            worlds_with_P_occupied_action_difference=sum(r["P_occupied_disagreement_mass"]>0 for r in rows),
            worlds_with_utility_difference=sum(r["utility_delta"]!=0 for r in rows),records=rows)
    payload=dict(schema="hepta.saved-action-occupancy-diagnostic.v1",
        scope="Post hoc descriptive action/edge arithmetic only; does not change primary tests or candidate selection",
        source_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        model_calls=0,optimizer_calls=0,CPU_seconds=time.process_time()-started,comparisons=result)
    with (ROOT/"ACTION_OCCUPANCY_DIAGNOSTIC.json").open("x") as stream:
        json.dump(payload,stream,sort_keys=True,indent=2);stream.write("\n")
    print(json.dumps({d:{k:v for k,v in values.items() if k!="records"} for d,values in result.items()},indent=2))


if __name__=="__main__":main()
