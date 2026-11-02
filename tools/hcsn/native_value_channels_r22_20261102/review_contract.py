"""Read-only independent exact-rational scope and source-contract checks."""
import argparse
import ast
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPECTED_R11 = "69f5b28c61301bcb89d1c860212e7532fa292538214967e6871ed355e5e367b0"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_contract():
    checks = []
    def check(name, condition):
        checks.append({"name": name, "passed": bool(condition)})
        if not condition: raise AssertionError(name)
    protocol = json.loads((HERE/"PROTOCOL.json").read_text())
    check("physical_order", protocol["parameter_order"] == ["r", "delta", "alpha", "tax", "coupon", "principal", "sigma", "liquidity", "maturity"])
    check("state_coordinate", protocol["state_coordinate"] == "log_distance")
    check("five_outputs", protocol["outputs"] == ["boundary", "equity", "F", "G", "debt"])
    check("registered_box", protocol["lower"] == [.079,.0195,.59,.265,6.30,61.,.15,.002,.5]
          and protocol["upper"] == [.081,.0205,.61,.275,6.48,62.4,.4,.04,2.])
    check("continuation_only_state_box", protocol["state_box"] == [.005,.6])
    check("fixed_states", protocol["formal_states"] == [.01,.2,.5])
    check("fixed_namespace", protocol["confirmation_namespace"] == 2026110210)
    check("fixed_selected_indices", protocol["independent_math_selected_indices"] == [0,46,95,142,189,194])
    check("unchanged_value_tolerances", (protocol["values_atol"],protocol["values_rtol"]) == (2e-9,2e-11))
    check("unchanged_jacobian_tolerances", (protocol["jacobian_atol"],protocol["jacobian_rtol"]) == (2e-8,2e-10))
    check("unchanged_fd_contract", protocol["finite_difference_width_fraction"] == .001 and protocol["finite_difference_tolerance"] == .000005)
    check("unchanged_R11_snapshot", digest(HERE/"r11_kernel_snapshot.py") == EXPECTED_R11)
    original = ROOT/"tools/hcsn/calibrated_operator_r11_20261031/numerics/kernel.py"
    if original.exists(): check("snapshot_matches_existing_R11", digest(original) == EXPECTED_R11)
    tree = ast.parse((HERE/"verify.py").read_text())
    assignment = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)
                  and node.targets[0].id in ("ORDER","INVERSE")}
    order, inverse = assignment["ORDER"], assignment["INVERSE"]
    check("parameter_mapping", order == [0,1,6,2,3,7,8,4,5])
    check("jacobian_mapping", inverse == [0,1,3,4,7,8,2,5,6,9]
          and [order[i] for i in inverse[:9]] == list(range(9)))
    imported = {}
    for name in ("reference.py", "independent_math.py"):
        names=[]
        for node in ast.walk(ast.parse((HERE/name).read_text())):
            if isinstance(node, ast.Import): names += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom): names.append(node.module or "")
        imported[name] = names
        check(name+"_does_not_import_candidate_or_R11", all(not ("reference" in value or "r11" in value or "channels" in value or "verify" in value or "dual" in value) for value in names))
    # Convexity in each coordinate puts the maximum of (d-v/2)^2/v
    # on a corner of this positive d/v rectangle. All constants are exact rationals.
    d_box = (F(".079")-F(".0205"), F(".081")-F(".0195"))
    v_box = (F(".15")**2, F(".4")**2)
    maximum = max((d-v/2)**2/v for d in d_box for v in v_box)
    root_scale_square_bound = (maximum + 2*(F(".081")+F(".04")))*F(2)
    state_scale_square_bound = F(".6")**2/(F(".15")**2*F(".5"))
    check("drift_variance_corner_bound", maximum == F(".112225"))
    check("liquid_root_scale_bound", root_scale_square_bound == F(".70845") and F(".842")**2 > root_scale_square_bound)
    check("state_scale_bound", state_scale_square_bound == 32 and F("5.657")**2 > state_scale_square_bound)
    check("all_real_CDF_arguments_inside_admission", F("5.657")+F(".842") == F("6.499") < 12)
    check("raw_R11_branch_only", F(".005") > F(".002"))
    return {"passed": True, "checks": checks, "count": len(checks), "imports": imported,
            "rational_bounds": {"maximum_mu_square_over_variance": str(maximum),
                 "zt_s_square_maximum": str(root_scale_square_bound), "x_over_s_square_maximum": str(state_scale_square_bound),
                 "cdf_argument_absolute_upper_bound": "6.499 < 12"},
            "source_sha256": {name:digest(HERE/name) for name in protocol["sources"]},
            "reviewer_source_sha256": digest(Path(__file__)),
            "scope": "Exact-rational real-domain and read-only source-contract checks. No new parameter points, native numerical runs, derivative measurements, uniform quadrature/FP64 bound or model-adoption evidence."}


if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    result=check_contract()
    with args.output.open("x") as stream: json.dump(result,stream,indent=2,sort_keys=True);stream.write("\n")
    print(json.dumps({"passed":True,"checks":result["count"]},sort_keys=True))
