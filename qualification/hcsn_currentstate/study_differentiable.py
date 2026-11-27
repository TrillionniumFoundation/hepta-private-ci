"""Bounded finite-state continuation, differentiation and identification study."""

import argparse
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import platform
import resource
import subprocess
import time
import unittest

import numpy as np
import torch

from .differentiable import Work, advance, initial, refractory
from .test_differentiable import DifferentiableCurrentStateTests, dde_reference, physics


LIMITS = {"initial_cases": 3, "optimizer_steps": 60, "final_to_initial_loss": .1,
          "state_difference": 3e-10, "max_dimension": 256, "max_packets": 256}


def run():
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    started, cpu = time.perf_counter(), time.process_time()
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(DifferentiableCurrentStateTests))
    if not result.wasSuccessful():
        raise AssertionError("complete-state tests failed")
    rates = torch.tensor([.7,.3,.6,.2,.05,.08], dtype=torch.float64)
    initials = [rates.new_tensor([[a,1-a],[-.3,.8]]) for a in (.2,.5,.8)]
    targets, rows = [], []
    for index, active in enumerate(initials):
        scale = (.8,1.2,1.6)[index]
        p1, p2 = physics(rates), physics(rates*scale)
        reference = dde_reference([p1,p2], [F(3,20),F(13,20)], active.numpy())
        targets.append(torch.from_numpy(reference))
        work = Work()
        before = time.perf_counter()
        s = advance(initial(active), p1, F(3,20), work)
        s = advance(s, p2, F(13,20), work)
        elapsed = time.perf_counter()-before
        actual = torch.cat((s.active, s.upper[:,None], s.hits[:,None], s.occupation[:,None],
                            s.discounted_hits[:,None], s.value[:,None]),1)
        error = float((actual-targets[-1]).abs().max())
        rows.append({"case":index,"dde_max_absolute_error":error,"forward_seconds":elapsed,
                     "state_tensor_bytes":s.tensor_bytes(),"pending_packets":len(s.pending),
                     "exponentials":work.exponentials,"largest_matrix":work.largest_dimension,
                     "mass_and_signed_mark_error":float((s.active.sum(1)+s.upper+refractory(s)-active.sum(1)).abs().max())})
        if error > LIMITS['state_difference']:
            raise AssertionError("DDE state comparison failed")
    raw = torch.nn.Parameter(torch.log(torch.expm1(rates*.65+.08)))
    optimizer = torch.optim.Adam([raw], lr=.04)
    losses = []
    maximum_gradient = 0.
    training_started = time.perf_counter()
    for step in range(LIMITS['optimizer_steps']+1):
        current_rates = torch.nn.functional.softplus(raw)
        loss = raw.new_zeros(())
        for index, active in enumerate(initials):
            s = advance(initial(active), physics(current_rates), F(3,20))
            s = advance(s, physics(current_rates*(.8,1.2,1.6)[index]), F(13,20))
            prediction = torch.cat((s.active, s.upper[:,None], s.hits[:,None], s.occupation[:,None],
                                    s.discounted_hits[:,None], s.value[:,None]),1)
            loss = loss + (prediction-targets[index]).square().mean()/len(initials)
        losses.append(float(loss.detach()))
        if step == LIMITS['optimizer_steps']:
            break
        optimizer.zero_grad(); loss.backward()
        if not bool(torch.isfinite(raw.grad).all()):
            raise FloatingPointError("nonfinite complete-state training gradient")
        maximum_gradient = max(maximum_gradient, float(raw.grad.norm()))
        optimizer.step()
    if losses[-1] > LIMITS['final_to_initial_loss']*losses[0]:
        raise AssertionError("identification did not meet the frozen loss-reduction limit")
    return {"schema":"hcsn-differentiable-currentstate-study-v1", "limits":LIMITS,
            "tests_run":result.testsRun,"rows":rows,"optimizer_steps":LIMITS['optimizer_steps'],
            "training_loss":losses,"maximum_gradient_norm":maximum_gradient,
            "fitted_rates":torch.nn.functional.softplus(raw).detach().tolist(),
            "training_seconds":time.perf_counter()-training_started,
            "wall_seconds":time.perf_counter()-started,"cpu_seconds":time.process_time()-cpu,
            "peak_rss_native_units":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "platform":platform.platform(),"torch":torch.__version__,"numpy":np.__version__,
            "scope":"finite CTMC system identification; not encoder task, continuum qualification, or C2 replay",
            "checkpoint_scope":"cold forward state only; serialized state does not preserve earlier autograd tape"}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as out:
        frozen = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                  (Path(__file__),Path(__file__).with_name('differentiable.py'),
                   Path(__file__).with_name('test_differentiable.py'))}
        report = {"status":"started","source_sha256":frozen,
                  "git_head":subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()}
        out.write(json.dumps(report)+'\n'); out.flush()
        try:
            report.update(run()); report['status']='passed'
        except Exception as error:
            report.update(status='failed', error=repr(error))
            raise
        finally:
            out.seek(0); json.dump(report,out,sort_keys=True,allow_nan=False); out.write('\n'); out.truncate()


if __name__ == '__main__':
    main()
