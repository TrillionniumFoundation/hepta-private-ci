"""Check the pinned amber originals against the prior independent NumPy GPT-2 reader."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile
import numpy as np
from tokenizers import Tokenizer
from cell_experiments import chat_protocol, data
from cell_experiments.online_v4 import circuit_bundle as circuit, circuit_router


def compare(fixture, reader, archive):
    def sha(raw):
        return hashlib.sha256(raw).hexdigest()
    assert sha(fixture.read_bytes()) == "08640f268030dbb74b97cc63f1631e510848c99b8522231314b1f2a9b5c83099"
    assert sha(reader.read_bytes()) == "672cb8b57548ac78077f1822d875e720682fb6338d9d7b454c2d6c3055378fc6"
    assert sha(archive.read_bytes()) == "b8620883ae0ec097512e179b966ad8c38cc5f56e06e5e880ef104fb0a431877e"
    spec = importlib.util.spec_from_file_location("archived_tensor_reader", reader)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    with zipfile.ZipFile(fixture) as old, zipfile.ZipFile(archive) as new:
        def read(n):
            return json.loads(new.read(n))
        pair = json.loads(old.read(next(n for n in old.namelist() if n.endswith("/paired.json"))))
        parent = read("materials/parent.json")
        assert parent == pair["candidate"]
        fail, correct = [read("materials/"+k+".json") for k in ("failure","correction")]
        source = fail["task"]["input"]
        assert fail["task"] == correct["task"] and source == "Return the JSON integer one for this amber receipt."
        for row, passed in ((fail,False),(correct,True)):
            src = row["source"]["sha256"]
            assert sha(new.read("materials/originals/"+src)) == src
            event = row["trajectory"][-1]["receipt_sha256"]
            sink = read("materials/originals/"+event)
            assert data.digest(sink) == event
            assert new.read("materials/originals/"+sink["readback_sha256"]) == row["final_answer"].encode()
            assert data.verify_answer(row,row["final_answer"])["success"] is passed
        op = next(n for n in new.namelist() if n.endswith("/ROUTER-FIT.json")).removesuffix("ROUTER-FIT.json")
        search = read(op+"router-search/SEARCH.json")
        receipt = read(op+"ROUTER-FIT.json")
        assert receipt["search_sha256"] == data.digest(search)
        tok = Tokenizer.from_str(old.read("original/materials/base/tokenizer.json").decode())
        assert json.loads(old.read("original/materials/base/tokenizer_config.json"))["chat_template"] == "{% for m in messages %}{{ m.content }}{% if not loop.last %} {% endif %}{% endfor %}"
        outputs = []
        utilities = []
        for g, entry in zip(parent["router"]["graphs"],search["observations"],strict=True):
            graph = circuit._graph(g)
            raw = read(op+"router-search/"+entry["result_path"])
            assert entry["graph_id"] == graph.graph_id and data.digest(raw) == entry["result_digest"]
            replay = []
            for i,(cell,actual) in enumerate(zip(graph.path,raw["nodes"],strict=True)):
                request = circuit._request(circuit._task({"input":source}),graph,i,replay,circuit.Budget(**parent["budget"]))
                wire = chat_protocol.inference_wire_messages(source,request["messages"])
                ids = tok.encode(" ".join(m["content"] for m in wire),add_special_tokens=False).ids
                nxt = reference.replay_token(old,parent["models"][cell],ids)
                answer = tok.decode([nxt],skip_special_tokens=True)
                assert actual["cell_id"] == cell and request == actual["request"]
                assert actual["output"]["input_ids"] == ids and actual["output"]["output_ids"] == [nxt]
                assert actual["output"]["answer"] == answer
                replay.append({"output":{"answer":answer}})
            passed = data.verify_answer(fail,replay[-1]["output"]["answer"])["success"]
            assert passed is entry["success"] is raw["success"]
            utilities.append(float(passed))
            outputs.append(dict(graph=graph.graph_id,passed=passed,answer=replay[-1]["output"]["answer"],
                                token_ids=[n["output"]["output_ids"] for n in raw["nodes"]]))
        cfg = parent["router"]["plan"]
        assert cfg["output_token_penalty"] == cfg["model_call_penalty"] == 0
        features,_ = circuit_router.prompt_features(fail,cfg["feature_dimensions"])
        x = np.array([features])
        weights = np.linalg.solve(x.T@x+cfg["ridge"]*np.eye(x.shape[1]),x.T@np.asarray([utilities])).T
        assert np.allclose(weights,read(op+"router-search/ROUTER.json")["weights"],atol=1e-12,rtol=1e-10)
        decision = read(op+"NO_UPDATE.json")["decision"]
        assert decision == "no_update_no_distinct_graph_success" and op+"FROZEN.json" not in new.namelist()
        return dict(archive_sha256=sha(archive.read_bytes()),source_artifacts=2,independent_forward_passes=4,
                    ridge_parameters=weights.size,originals=outputs,decision=decision,enrolled_people=0,
                    prospective_admissions=0,payments=0)


if __name__ == "__main__":
    print(json.dumps(compare(*(Path(v) for v in sys.argv[1:])),indent=2))
