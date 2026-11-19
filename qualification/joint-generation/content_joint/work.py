"""Complete useful-kernel profiles; immutable original scalar prices apply."""

from content_joint.analyze import add, single_head_parts


def forward_work(n):
    return single_head_parts(12, "H", n)["forward"]


def native_step_work(arm, n):
    return add(*single_head_parts(12, arm, n).values(), {"compare_ops": n})


def native_cache_work(arm):
    if arm != "N":
        return {}
    return dict(scalar_ops=2 * 144, compare_ops=12 * 11, exp_ops=144)


def independent_cache_work(arm):
    if arm != "N":
        return {}
    return dict(scalar_ops=2 * 1728, compare_ops=12 * 143, exp_ops=1728)


def evidence_work(elements):
    # Separate useful norm/clip trace; the optimizer's own norm is already paid.
    return dict(scalar_ops=2 * elements + 4, sqrt_ops=1, div_ops=1, compare_ops=1)
