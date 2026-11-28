"""Directed intervals for a real eigenvalue of the instantaneous reset PDE."""
import json
from pathlib import Path
from mpmath import iv
from halfline import Stationary
from stability import Transfer
from enclose import Rigorous,Dual,enclosing_numbers

def run():
    p=Stationary(Rigorous)
    # Narrow u using independently proved endpoint signs, to avoid excessive
    # interval dependency in the Laplace formulas.
    first,last=".1428750322624379",".1428750322624386"
    at=[p.stationary(Dual(z))[0].v for z in (first,last)]
    if not (at[0]>0 and at[1]<0):
        first,last=".1428750322623",".1428750322626"
        at=[p.stationary(Dual(z))[0].v for z in (first,last)]
    if not (at[0]>0 and at[1]<0):
        raise ArithmeticError("root interval")
    tr=Transfer(p,Dual(iv.mpf([first,last])))
    freq=[".48",".51"]
    responses=[tr.response(Dual(z)).v for z in freq]
    if not (responses[0]>1 and responses[1]<1):
        raise ArithmeticError(responses)
    return dict(mid_inward_drift=[first,last],drift_residuals=[enclosing_numbers(v) for v in at],
                real_growth_rate_bracket=freq,transfer_at_bracket=[enclosing_numbers(v) for v in responses],
                characteristic_equation="1-H(s)=0",refractory_law="deterministic delay of 0.25")

if __name__=="__main__":
    result=run()
    Path(__file__).with_name("growth.json").write_text(json.dumps(result,indent=2)+"\n")
    print(result)
