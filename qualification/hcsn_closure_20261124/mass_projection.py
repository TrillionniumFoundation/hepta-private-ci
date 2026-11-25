"""Opt-in bounded joint mass projection; not an unprojected CTMC solver.

The map is identity on the unit-mass manifold in real arithmetic. Its ambient
Jacobian is a tangent projection, so it does not preserve arbitrary independent
probability-coordinate derivatives. Input/parameter sensitivities and legal
zero-total-mass perturbations require separate comparison with the FP64 law.
Small defects alone do not establish their origin as roundoff. Every raw local
defect and accumulated correction is reported; defects outside the fixed
2e-6 admission bound are rejected, never repaired.
"""

import torch

from .normalized_uniformization import NormalizedUniformizedHCSN


def project_joint(density, hits, value, risk, margin, tolerance=2e-6):
    mass = density[..., 0, :].sum(-1)
    defect = (mass-1).abs()
    if (not bool(torch.isfinite(mass).all()) or bool((mass <= 0).any())
            or bool((defect > tolerance).any())):
        raise FloatingPointError("joint mass projection refused a nonlocal defect: "
                                 +str(float(defect.detach().max())))
    factor = mass.reciprocal()
    corrected = density*factor[..., None, None]
    projected_hits = hits*factor[..., None]
    projected_risk = risk*factor
    if (bool((projected_risk < -tolerance).any())
            or bool((projected_risk > 1+tolerance).any())
            or bool((projected_risk > projected_hits[..., 0]+tolerance).any())):
        raise FloatingPointError("joint projection violates first-event semantics")
    record = {"raw_mass_defect_max": float(defect.detach().max()),
              "applied_probability_l1_max": float((corrected[..., 0, :]-density[..., 0, :]).abs().sum(-1).detach().max()),
              "applied_signed_l1_max": float((corrected[..., 1, :]-density[..., 1, :]).abs().sum(-1).detach().max())}
    return (corrected, projected_hits, value*factor, projected_risk, margin*factor), record


class ProjectedUniformizedHCSN(NormalizedUniformizedHCSN):
    def forward(self, *args, **kwargs):
        if getattr(self, "_projection_rows", None) is not None:
            raise RuntimeError("joint projection forward is not reentrant")
        self._projection_rows = []
        try:
            result = super().forward(*args, **kwargs)
            rows = self._projection_rows
            self.last_diagnostics.update({"joint_projection": self.config.precision == "native32",
                "projection_steps": len(rows), "projection_local_admission": 2e-6,
                "raw_local_mass_defect_max": max((r["raw_mass_defect_max"] for r in rows), default=0.),
                "probability_correction_l1_sum_of_step_maxima": sum(r["applied_probability_l1_max"] for r in rows),
                "signed_correction_l1_sum_of_step_maxima": sum(r["applied_signed_l1_max"] for r in rows)})
            return result
        finally:
            self._projection_rows = None

    def _flow(self, density, jump, generator, event, boundary, cost):
        values = super()._flow(density, jump, generator, event, boundary, cost)
        if self.config.precision != "native32":
            return values
        projected, record = project_joint(*values)
        self._projection_rows.append(record)
        return projected
