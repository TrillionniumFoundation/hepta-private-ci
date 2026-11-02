"""Final fitted renewal raw parameters versus independent physical generators."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from .joint_law import IndependentLaw


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(); p.add_argument("--root",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True); a = p.parse_args()
    frozen = json.loads((a.root/"MODEL_FREEZE.json").read_bytes())
    maximum = 0.; rows = []
    for fit in (11,23,37,53,71):
        path = a.root/f"fit_{fit}/model_renewal/model.json"
        assert sha(path) == frozen["models"][str(path.relative_to(a.root))]
        model = json.loads(path.read_bytes()); law = IndependentLaw(model["core"]["raw"])
        assert model["parameter_count"] == 4332
        assert model["confusion"] == frozen["data"][str(fit)]["confusion"]
        assert np.array_equal(model["coordinates"],law.u)
        for key,value in law.physical.items():
            assert abs(value-model["core"]["physical"][key]) <= 1e-14
        error = max(float(np.max(np.abs(np.asarray(model["core"]["generators"][str(d)])-law.generator(d)))) for d in (-1,0,1))
        maximum = max(maximum,error)
        rows.append(dict(fit=fit,raw=model["core"]["raw"],max_Q_error=error))
    assert maximum <= 1e-12
    result = dict(passed=True,model_freeze_sha256=sha(a.root/"MODEL_FREEZE.json"),
        audit_source_sha256=sha(__file__),max_fitted_generator_error=maximum,fits=rows,
        scope="Final5 renewal raw/physical/generator exports match independent SciPy-law construction; eight coefficients do not establish eight identifiable effects or continuum accuracy")
    with a.out.open("x") as stream:
        json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False); stream.write("\n")
    print(json.dumps(result,sort_keys=True))


if __name__ == "__main__": main()
