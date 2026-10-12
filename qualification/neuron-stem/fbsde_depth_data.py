"""Versioned label-free belief contexts; no semantic labels or policy scores.

This is a design distribution, not an empirical law of Hepta requests.
"""
import math
import random
from four_gate_common import digest, require

def numeric_inputs(seed, count, split):
    """No semantic labels or solver results can select the public teacher cases."""
    require(type(count) is int and 1 <= count <= 512, 'teacher inventory bound')
    rng = random.Random(seed); result = []
    for i in range(count):
        unique = 1+i%3; length = unique+1+i%4
        group = [j%unique for j in range(length)]; rng.shuffle(group)
        components = []
        for _ in range(3):
            laws = []
            for _ in range(unique):
                raw = [rng.gammavariate((.15,.5,2.)[i%3],1) for _ in range(3)]
                laws.append([p/math.fsum(raw) for p in raw])
            components.append([laws[g] for g in group])
        result.append({'source_id':f'{split}:{i}','query':rng.randrange(3),
            'components':components,'weights':[1/3]*3,
            'keys':[digest([split,i,g]) for g in group]})
    return result


def construct(row, model, calibration, scope='depth-research'):
    from fbsde_tracking_tied import InputTiedBelief
    binding = {'source':digest(row),'model':model,'calibration':calibration,'scope':scope,'generation':3}
    return InputTiedBelief(3,row['query'],row['components'],row['weights'],row['keys'],binding)

