"""Execute local independent evidence generation; never asserts production admission."""
import datetime
import json
import math
import platform
from pathlib import Path
import numpy
import scipy
from fpt_reference import FPT,float_diagnostic,transformed_integral,formula
from qvi_toy import audit as qvi_audit
from event_memory_tasks import audit_matrix
from gate_contract import write_template,assess,empty_ledger
from stress_envelope import run_stress


def main():
    out=Path(__file__).parent/'reports'
    out.mkdir(exist_ok=True)
    sigma=1.8581469732429565
    rate=.007595780582070804
    frozen=FPT(math.log(1.000000000000002),
               rate-3.5072936797757205e-07-sigma*sigma/2,
               sigma,2.2216211523554883e-08,rate)
    high_precision_frozen=float_diagnostic(frozen,125)
    # Cross-check moderate regimes with genuinely different derivations.
    checks=[]
    for p in [FPT(.8,-.3,.7,.9,.05),FPT(.2,.2,.6,1.2,0),
              FPT(1.4,.4,.5,1.1,.11)]:
        closed=formula(p,75)
        integrated=transformed_integral(p,65)
        checks.append({'parameters':p.__dict__,'closed':closed,
                       'density_integral':integrated,
                       'delta_F':abs(float(closed['F'])-float(integrated['F'])),
                       'delta_G':abs(float(closed['G'])-float(integrated['G']))})
    result={'date_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'scope':'local independent scalar and synthetic task checks only',
            'environment':{'python':platform.python_version(),'numpy':numpy.__version__,
                           'scipy':scipy.__version__, 'cpu_only':True},
            'frozen_fpt':high_precision_frozen,'fpt_cross_checks':checks,
            'qvi_toy':qvi_audit(),'memory_oracle_matrix':audit_matrix(),
            'fpt_stress':run_stress(),
            'admission':assess(empty_ledger())}
    (out/'local_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    write_template(out/'evidence_template.json')
    print('frozen F-G:',high_precision_frozen['reference']['F_minus_G'])
    print('float classification:',high_precision_frozen['classification'])
    print('toy QVI policy oracle gap:',result['qvi_toy']['max_policy_gap'])
    print('FPT stress:',{k:v for k,v in result['fpt_stress'].items() if k!='cases'})
    print('memory task configs checked:',len(result['memory_oracle_matrix']))
    print('production admission:',result['admission']['policy'])

if __name__=='__main__':main()
