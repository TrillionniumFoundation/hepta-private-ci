"""Candidate only: unbiased CE-anchor control variate, before norm clipping.

No model, data, optimizer or observer is constructed here. This function has not
been used for TRAIN. Both A and N would receive the same paid estimator.
"""

import numpy as np

from independent.learning import CONTENT_PARAMETERS

CE_ANCHOR = 0.2


def correct(gradient, reference_ce_mean, reference_ce_batch):
    """g_B(theta) + .2*(G_CE(theta0) - g_CE,B(theta0)).

    Reference CE gradients exclude the .2 coefficient. Both batch estimators
    must use identical indices, views and importance weights. The reference
    mean covers all TRAIN sources/rows and the original .5/.5 view law.
    """
    expected = set(CONTENT_PARAMETERS)
    if any(set(value) != expected for value in (gradient, reference_ce_mean, reference_ce_batch)):
        raise ValueError("complete six content-gradient groups required")
    for key in CONTENT_PARAMETERS:
        arrays = [value[key] for value in (gradient, reference_ce_mean, reference_ce_batch)]
        if (any(not isinstance(a, np.ndarray) or a.dtype != np.float64 or a.size == 0
                or not np.isfinite(a).all() for a in arrays)
                or any(a.shape != arrays[0].shape for a in arrays)):
            raise ValueError("matching finite float64 gradients required")
    return {key: gradient[key] + CE_ANCHOR*(reference_ce_mean[key]-reference_ce_batch[key])
            for key in CONTENT_PARAMETERS}


def correction_work(elements):
    if type(elements) is not int or not 1 <= elements <= 4_000_000:
        raise ValueError("bounded positive content element count required")
    return {"scalar_ops": 3*elements, "compare_ops": 3*elements}
