"""One fixed pure-probability verification and full saved-support enumeration."""

import argparse
import hashlib
import io
import itertools
import json
from pathlib import Path
import resource
import subprocess
import unittest

import numpy as np

from content_theory import test_geometry
from content_theory.categorical import (
    ALPHA, RHO, binary_face_geometry, binary_population_stationary,
    logit_geometry, maximal_coupling, symmetric_binary,
)


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    paths = list((ROOT / "content_theory").glob("*.py"))
    paths += [ROOT / "content_theory/PROTOCOL.md", ROOT / "content_joint/objectives.py",
              ROOT / "utility.py", ROOT / "data.py",
              ROOT / "runs/content-joint-train-v1-20261023/evidence/final-status.json"]
    binding = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    console = io.StringIO()
    tests = unittest.TextTestRunner(stream=console, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(test_geometry))
    (args.out / "unit-tests.txt").write_text(console.getvalue())
    result = dict(scope="pure hand laws and retained reward support; independent research review",
        source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        ALPHA=ALPHA, RHO=RHO, bindings=binding, tests_run=tests.testsRun,
        unit_tests_passed=tests.wasSuccessful(), seeds={}, symmetric_hand_case=symmetric_binary(.9),
        model_forward_calls=0, decoder_forward_calls=0, optimizer_updates=0,
        generated_random_samples=0, real_requests=0, images_rendered=0,
        model_weights_loaded=0, formal_data_opened=False,
        old_status_and_10second_failures_unchanged=True)
    if not tests.wasSuccessful():
        result["exit_code"] = 1
        (args.out / "verification.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(console.getvalue())
        raise SystemExit(1)
    for seed in (11, 23, 47):
        path = ROOT / f"runs/content-reconcile-probe-v1-20261023/R-{seed}.npz"
        binding[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        with np.load(path, allow_pickle=False) as saved:
            full = saved["reward"].copy()
            r = np.diagonal(full, axis1=1, axis2=2).copy()
            assert np.array_equal(saved["text_sem"], np.arange(12))
            assert np.array_equal(saved["image_sem"], np.arange(12))
        gaps, spreads, sign_checks, faces = [], [], 0, []
        for y in range(12):
            wrong = np.arange(12) != y
            gaps.extend((r[y, y] - r[y, wrong]).tolist())
            spread = float(r[y, wrong].max() - r[y, wrong].min())
            spreads.append(spread)
            assert np.all(r[y, y] > r[y, wrong])
            assert ALPHA > spread
            assert ALPHA > (1 - np.exp(-RHO * spread)) / RHO
            for py in (.01, .5, .99):
                law = np.full(12, (1 - py) / 11)
                law[y] = py
                for arm in ("A", "N"):
                    _, gradient, _ = logit_geometry(np.log(law), np.eye(12)[y], r, arm)
                    assert gradient[y] < 0 and np.all(gradient[wrong] > 0)
                    sign_checks += 1
        for a, b in itertools.combinations(range(12), 2):
            pair = [a, b]
            rr = r[np.ix_(pair, pair)]
            other = [c for c in range(12) if c not in pair]
            rows = r[pair]
            reward_dom = .5 * (rows[:, a] + rows[:, b])[:, None] - rows[:, other]
            k = np.exp(-RHO * rows)
            kernel_dom = k[:, other] - .5 * (k[:, a] + k[:, b])[:, None]
            assert reward_dom.min() > 0 and kernel_dom.min() > 0
            face = binary_population_stationary(rr)
            assert abs(binary_face_geometry(face["A_optimum"], rr, "A")[1]) < 1e-10
            assert all(abs(x["gradient"]) < 1e-8 for x in face["N_stationary"])
            minima = [x for x in face["N_stationary"] if x["kind"] == "minimum"]
            best_loss = min(x["loss"] for x in minima)
            global_minima = [x for x in minima if x["loss"] <= best_loss + 1e-12]
            face.update(pair=pair, hand_label_law=[.5, .5],
                outside_reward_dominance_min=float(reward_dom.min()),
                outside_kernel_dominance_min=float(kernel_dom.min()),
                N_global_minima=global_minima,
                N_at_A_optimum=binary_face_geometry(face["A_optimum"], rr, "N")[0],
                p_point_51_A_gradient=binary_face_geometry(.51, rr, "A")[1],
                p_point_51_N_gradient=binary_face_geometry(.51, rr, "N")[1],
                joint_success_at_every_face_law=.5)
            faces.append(face)
        coupling_checks = []
        p = np.arange(1., 13.) / 78
        for name, q in (("same", p), ("reversed", p[::-1]), ("rotated", np.roll(p, 3))):
            joint = maximal_coupling(p, q)
            independent = np.outer(p, q)
            observed = np.sum(full * (joint - independent)[None, :, :], axis=(1, 2))
            predicted = .3 * (np.minimum(p, q) - p * q) + .35 * (np.minimum(p, q).sum() - np.sum(p * q))
            np.testing.assert_allclose(observed, predicted, atol=1e-12, rtol=0)
            np.testing.assert_allclose(joint.sum(1), p, atol=1e-15)
            np.testing.assert_allclose(joint.sum(0), q, atol=1e-15)
            coupling_checks.append(dict(hand_law=name,
                max_raw_reward_identity_error=float(np.max(np.abs(observed - predicted))),
                unchanged_marginals=True, joint_success_increase_equals_both_wrong_increase=True))
        result["seeds"][str(seed)] = dict(native_reward_support=r.tolist(),
            correct_minus_wrong_gap_minmax=[min(gaps), max(gaps)],
            wrong_reward_spread_minmax=[min(spreads), max(spreads)],
            analytical_known_label_logit_sign_certificate=True,
            hand_known_label_sign_checks=sign_checks,
            ambiguity_faces=faces,
            negative_center_curvature_faces=sum(f["N_center_curvature"] < 0 for f in faces),
            three_stationary_faces=sum(len(f["N_stationary"]) == 3 for f in faces),
            two_local_minima_faces=sum(sum(x["kind"] == "minimum" for x in f["N_stationary"]) == 2 for f in faces),
            N_optimum_differs_from_A_faces=sum(min(x["loss"] for x in f["N_global_minima"]) < f["N_at_A_optimum"] - 1e-12 for f in faces),
            opposite_direction_at_51_faces=sum(f["p_point_51_A_gradient"] > 0 and f["p_point_51_N_gradient"] < 0 for f in faces),
            center_curvature_minmax=[min(f["N_center_curvature"] for f in faces), max(f["N_center_curvature"] for f in faces)],
            A_optimum_p_minmax=[min(f["A_optimum"] for f in faces), max(f["A_optimum"] for f in faces)],
            illustrative_FIXED_pair_0_1=next(f for f in faces if f["pair"] == [0, 1]),
            maximal_coupling_hand_identity_checks=coupling_checks)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result["independent_research_CPU_before_receipt"] = usage.ru_utime + usage.ru_stime
    result["exit_code"] = 0
    (args.out / "verification.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(console.getvalue())
    print(json.dumps(dict(CPU=result["independent_research_CPU_before_receipt"],
        symmetric_hand_case=result["symmetric_hand_case"],
        support={seed: {key: value[key] for key in ("negative_center_curvature_faces", "three_stationary_faces",
            "two_local_minima_faces", "N_optimum_differs_from_A_faces", "opposite_direction_at_51_faces",
            "center_curvature_minmax", "A_optimum_p_minmax")} for seed, value in result["seeds"].items()}), indent=2))


if __name__ == "__main__":
    main()
