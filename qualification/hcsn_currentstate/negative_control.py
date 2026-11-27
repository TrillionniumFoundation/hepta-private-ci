"""Same complete scalar totals, different future phase release laws."""
import mpmath as mp


def counterexample(dps):
    with mp.workdps(dps):
        q = mp.mpf(3)/20; low = mp.mpf(1)/20; middle = mp.mpf(1)/10; high = mp.mpf(3)/20
        t = mp.mpf(3)/40; rate = mp.mpf(5)/2
        w = mp.expm1(q*(high-middle))/mp.expm1(q*(high-low))
        same_z = w*mp.exp(-q*low)+(1-w)*mp.exp(-q*high)
        # At current t=0 all mass is refractory, zero accrued reward/hits and zero
        # active/upper coordinates. At future t=.075 only law B has released.
        future_active_b = w*mp.exp(-rate*(t-low))
        future_lower_b = w*(mp.mpf(2)/rate)*(-mp.expm1(-rate*(t-low)))
        return {"dps": dps, "law_A": {"times": [str(middle)], "weights": ["1"]},
                "law_B": {"times": [str(low), str(high)], "weights": [mp.nstr(w, dps), mp.nstr(1-w, dps)]},
                "current": {"active": "0", "upper": "0", "M": "0", "H": "0", "A": "0", "R": "1", "Z": mp.nstr(mp.exp(-q*middle), dps)},
                "equal_Z_residual": mp.nstr(abs(same_z-mp.exp(-q*middle)), dps),
                "future_time": str(t), "future_active_A": "0", "future_active_B": mp.nstr(future_active_b, dps),
                "future_first_hit_A": "0", "future_first_hit_B": mp.nstr(future_lower_b, dps),
                "admission": "totals_only_restore_is_insufficient"}
