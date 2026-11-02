"""Causal saved-owner replay from original tensors, without model/runner imports."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np
from scipy.linalg import expm
import torch
from torch.nn import functional as F


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODULE = ROOT / "tools/hcsn/learned_native_r19_20261102"
TRAINED = ROOT / "experiments/hcsn_learned_core_r19_20261102/run_01"


def load(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fnv(raw):
    value = 0xcbf29ce484222325
    for byte in raw:
        value = ((value^byte)*0x100000001b3) % 2**64
    return value


def run(directory, development=False):
    torch.set_num_threads(1)
    summary, start = load(directory/"SUMMARY.json"), load(directory/"START.json")
    assert start["development"] is development and summary["development"] is development
    assert start["publication"] == summary["publication"]
    if not development:
        freeze = load(MODULE/"OWNER_SOURCE_FREEZE.json")
        assert summary["publication"]["readback_verified"] and summary["publication"]["manifest_sha256"] == digest(MODULE/"OWNER_SOURCE_FREEZE.json")
        for name, sha in freeze["files"].items():
            assert digest(ROOT/name) == sha, name
    profiles = {row["name"]:row for row in load(MODULE/"PROFILE_MANIFEST.json")["profiles"]}
    matrices, tensors = {}, {}
    for name, profile in profiles.items():
        checkpoint = TRAINED/f"weights_{name}.pt"
        assert digest(checkpoint) == profile["checkpoint_sha256"]
        assert digest(MODULE/profile["profile"]) == profile["profile_sha256"]
        weights = torch.load(checkpoint, weights_only=True)
        tensors[name] = weights
        q = weights["Q"].numpy()*float(weights["log_scale"].exp())
        matrices[name] = (q, {})
    maxima = dict(state=0.,logits=0.,probabilities=0.,read_value=0.)
    cases = queries = reads = effects_count = kills = choices = 0
    tapes, registered = set(), set()
    for declared in summary["cases"]:
        assert declared["status"] == "PASS"
        name, domain, fault = declared["profile"], declared["domain"], declared["fault"]
        if fault == "none":
            index = declared["seed"] - (193610000000001 if development else 193630000000001) - (1000 if domain == "ood" else 0)
            folder = directory/f"{name}_{domain}_{index}"
            assert index in (0,1)
        else:
            folder = directory/f"{name}_{fault}"
        check = load(folder/"CHECK.json")
        assert check == declared
        assert (name,domain,declared["seed"],fault) not in registered
        registered.add((name,domain,declared["seed"],fault))
        profile, weights = profiles[name], tensors[name]
        text = (folder/"owner.state").read_text()
        body, seal = text.rsplit("CHECK\t",1)
        assert seal == f"{fnv(body.encode()):016x}\n"
        lines = [row.split("\t") for row in body.splitlines()]
        header = lines[0]
        assert len(header) == 20 and header[0] == "LEARNED_OWNER" and int(header[5]) == 6 and header[6] == "open"
        assert header[2] == profile["checkpoint_sha256"]+f":bytes-{fnv((MODULE/profile['profile']).read_bytes()):016x}"
        assert header[3] == check["checkpoint_sha256"] == profile["checkpoint_sha256"]
        raw_rows = [row for row in lines if row[0] == "ROW"]
        assert [int(row[1]) for row in raw_rows] == list(range(6))
        actual = np.array([row[2:] for row in raw_rows],dtype=float)
        assert actual.shape == (6,205) and np.isfinite(actual).all()
        pair = np.load(folder/"TORCH_PARITY.npz")
        assert np.array_equal(pair["native"],actual)
        db = sqlite3.connect(f"file:{folder/'provider.sqlite'}?mode=ro",uri=True)
        opens = {}
        for (reply,) in db.execute("SELECT response FROM replies"):
            if reply.startswith("OPEN\t"):
                fields = reply.split("\t")
                assert len(fields) == 9
                query = int(fields[1])
                if query in opens:
                    assert opens[query] == fields
                opens[query] = fields
        assert set(opens) == set(range(6))
        effects = [(opid,json.loads(semantic),response,float(fee)) for opid,semantic,response,fee in db.execute("SELECT opid,semantic,response,fee FROM effects")]
        assert len({row[0] for row in effects}) == len(effects)
        for opid,context,reply,fee in effects:
            assert context[1] == header[1] and context[-1] == opid
        encoded = weights["symbol.weight"].T.contiguous().softmax(-1).numpy().astype(float)
        emission = (.01+.96*weights["symbol.weight"].softmax(-1)).numpy().astype(float)
        phase = weights["phase_prior"].numpy()
        initial = list(map(int,opens[0][7].split(',')))
        state = np.stack([(phase[:,None]*encoded[token][None]).ravel() for token in initial])
        q, cache = matrices[name]
        expected_rows, fee_micros, read_count = [], 0, 0
        def logits(value):
            source = torch.from_numpy(np.asarray(value,dtype=np.float32))
            return F.linear(torch.tanh(F.linear(source,weights["head.0.weight"],weights["head.0.bias"])),weights["head.2.weight"],weights["head.2.bias"])
        for index in range(6):
            public = opens[index]
            key, dt, scale = int(public[2]),float(public[3]),float(public[6])
            if public[8] != "-":
                for event in public[8].split(','):
                    address, token = map(int,event.split(':'))
                    state[address] = (state[address].reshape(10,4).sum(1)[:,None]*encoded[token][None]).ravel()
            duration = 3*dt
            if duration not in cache:
                cache[duration] = expm(q*duration)
            state = state@cache[duration]
            before = logits(state[key:key+1])
            p = before.softmax(-1)
            post = state[key][None]*np.tile(emission.T,(1,10))
            post /= post.sum(1)[:,None]
            after_logits, after_prob = logits(post), logits(post).softmax(-1)
            value = ((p@weights["channel"])*after_prob.max(-1).values[None]).sum(-1)
            fee32 = np.float32(.07*scale+.003*duration)
            predicted_read = bool((value-torch.tensor([fee32])-p.max(-1).values > 0)[0]) if profile["control"] == "value" else bool(fee32 <= np.float32(profile["threshold"]))
            # Compare choice BEFORE consulting this query's purchased token.
            assert predicted_read == bool(actual[index,0])
            choices += 1
            actuators = [row for row in effects if row[1][0] == "ACT" and row[1][2] == index]
            if predicted_read:
                assert len(actuators) == 2 and {row[1][4] for row in actuators} == {"WAIT","REFRESH"}
                wait = next(row for row in actuators if row[1][4] == "WAIT")
                refresh = next(row for row in actuators if row[1][4] == "REFRESH")
                assert wait[1][3] == 0 and refresh[1][3] == 1
                wr, rr = wait[2].split("\t"),refresh[2].split("\t")
                assert int(wr[2]) == 1 and int(wr[3]) == -1 and int(wr[5]) == 0
                assert int(rr[2]) == 3 and abs(float(rr[4])-float(public[5])) < 1e-10
                token = int(rr[3])
                assert 0 <= token < 4
                assert int(rr[5]) == round(.07*scale*1e6) and refresh[3] == int(rr[5])/1e6
                state[key] = post[token]
                answer = int(after_logits[token].argmax())
                fee_micros += round(.003*dt*1e6)+round(.003*2*dt*1e6)+int(rr[5])
                read_count += 1
            else:
                assert not actuators
                answer = int(before[0].argmax())
            assert answer == int(actual[index,1])
            heads = torch.cat((before,after_logits),0).topk(2,dim=-1).values
            head_gap = (heads[:,0]-heads[:,1]).min()
            action_gap = (value-torch.tensor([fee32])-p.max(-1).values).abs() if profile["control"] == "value" else torch.tensor([abs(fee32-np.float32(profile["threshold"]))])
            expected = np.r_[float(predicted_read),answer,state.ravel(),before.numpy().ravel(),p.numpy().ravel(),after_logits.numpy().ravel(),after_prob.numpy().ravel(),float(value[0]),float(action_gap[0]),float(head_gap)]
            expected_rows.append(expected)
            queries += 1
        expected = np.stack(expected_rows)
        assert np.array_equal(actual[:,:2],expected[:,:2])
        difference = abs(actual-expected)
        measured = dict(state=float(difference[:,2:162].max()),logits=float(max(difference[:,162:166].max(),difference[:,170:186].max())),probabilities=float(max(difference[:,166:170].max(),difference[:,186:202].max())),read_value=float(difference[:,202].max()))
        assert measured["state"] < 5e-9 and measured["logits"] < 1e-5 and measured["probabilities"] < 2e-6
        for label,value in measured.items():
            maxima[label] = max(maxima[label],value)
        assert np.max(abs(np.array(lines[1][1:],dtype=float)-actual[-1,2:162])) == 0
        assert int(header[16]) == fee_micros
        assert len(effects) == 6+2*read_count == check["effects"]
        assert read_count == check["reads"]
        # Only now inspect targets/scorer, after all causal predictions are fixed.
        scores = [json.loads(row[0]) for row in db.execute("SELECT body FROM scores ORDER BY query")]
        assert scores == load(folder/"PRIVATE_SCORER.json") and len(scores) == 6
        for index,score in enumerate(scores):
            assert score["answer"] == int(actual[index,1]) and score["reward"] == int(score["answer"] == score["target"])
            assert abs(score["utility"]-(score["reward"]-score["fee"])) < 1e-12
        assert round(sum(row["fee"] for row in scores)*1e6) == fee_micros
        cursor = json.loads(db.execute("SELECT body FROM cursor").fetchone()[0])
        assert cursor["query"] == 6 and cursor["generation"] == int(header[4]) == (2 if check["actually_killed"] else 1)
        assert abs(float(header[12])-float(header[13])) < 1e-10
        if check["actually_killed"]:
            assert load(folder/"owner1.process.json")["exit_code"] == -9
            assert load(folder/"owner2.process.json")["exit_code"] == 0
            assert (folder/"fault.marker").exists()
            kills += 1
        else:
            assert load(folder/"owner1.process.json")["exit_code"] == 0
        tapes.add((declared["seed"],domain))
        db.close()
        reads += read_count
        effects_count += len(effects)
        cases += 1
    receipts = [load(path) for path in directory.rglob("*.process.json")]
    cpu = sum(row["cpu_seconds"] for row in receipts)
    assert len(receipts) == summary["process_count"] and abs(cpu-summary["complete_child_cpu_seconds"]) < 1e-9
    assert cases == summary["case_count"] == (14 if development else 144) and queries == cases*6 and kills == summary["actual_kills"]
    assert summary["all_passed"] and len(tapes) == (3 if development else 5)
    return dict(schema="hcsn-r19-independent-actual-trained-owner-v1",all_checks_passed=True,
        development=development,owner_source_freeze_sha256=None if development else digest(MODULE/"OWNER_SOURCE_FREEZE.json"),publication=summary["publication"],
        original_trained_profiles=summary["profile_count"],case_attempts=cases,distinct_public_price_filtered_or_normal_tapes=len(tapes),normal_tapes=2 if development else 4,public_price_filtered_stress_tapes=1,
        actual_queries=queries,causal_checkpoint_tensor_recomputed_choices=choices,actual_READs=reads,durable_effects=effects_count,actual_cold_kills=kills,
        maximum_independent_tensor_replay_errors=maxima,process_receipts=len(receipts),included_child_cpu_seconds=cpu,
        scope="Direct originalcheckpoint tensors+SciPygammaQ propagation+FP32linear/tanh from onlypublicOPEN andpurchasedREFRESH, choices checkedbeforetoken andtargets checkedlast; no model/runner/reference imports",
        limits=["144profile/fault attempts are not144independentworlds;5distinctphysicaltapes shared across16originalmodels",
                "UnreachedREADhooks do not count as actualkills", "Trusted-host mailbox+atomiccheckpoint/fencing, notnetwork/powerloss/authentication/production",
                "Extendsactualtrainedmodelcausalexecution/recoveryonly; doesnotreopenfailedcoregain/generalization/costgates"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory",type=Path)
    parser.add_argument("--development",action="store_true")
    args = parser.parse_args()
    with torch.no_grad():
        report = run(args.directory,args.development)
    target = "independent_learned_owner_development.json" if args.development else "independent_learned_owner.json"
    with (HERE/target).open("x") as stream:
        json.dump(report,stream,indent=2,sort_keys=True)
        stream.write("\n")
    print(json.dumps(report))
