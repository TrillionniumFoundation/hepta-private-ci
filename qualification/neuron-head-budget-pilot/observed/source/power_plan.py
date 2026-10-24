"""Scenario planning only: no observed test outcomes are loaded."""
import json,math
from statistics import NormalDist
from pathlib import Path
P=Path(__file__).resolve().parent
n=1600;z=NormalDist().inv_cdf(.9875);zpower=NormalDist().inv_cdf(.8)
rows=[{'assumed_head_discordance':q,'test_n':n,'approx_se_delta_zero_pp':100*math.sqrt(q/n),'approx_two_sided_97_5_halfwidth_pp':100*z*math.sqrt(q/n),'rough_80pct_power_min_delta_pp':100*(z+zpower)*math.sqrt(q/n)} for q in [.05,.1,.2]]
out={'method':'Normal approximation for a paired accuracy difference; scenario parameters not estimated from old or new test. Not a guarantee; joint two-estimand claim is less powered. Budget-gain variance includes unknown covariance and is not estimated here.','scenarios':rows,'interpretation':'At discordance 0.10, about 2.44 percentage points, not sub-1pp effects, are plausibly detectable with 80% marginal power. An inconclusive result does not justify equivalence.'}
(P/'power-planning.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
