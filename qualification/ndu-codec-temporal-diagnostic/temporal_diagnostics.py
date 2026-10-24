"""Reference-aligned pixel diagnostics, never a semantic or acceptance score."""
import numpy as np


def temporal_diagnostics(reference, reconstruction, reference_times, reconstruction_times):
    """Compare presentation-ordered frames on an identical timestamp grid.

    Caller must obtain presentation order from its decoder, not packet order.
    Values are diagnostic only: a frozen output can beat a noisy correct codec
    on delta residual. Do not collapse these measurements into pass/fail.
    """
    x, y = np.asarray(reference), np.asarray(reconstruction)
    if x.shape != y.shape or x.ndim != 4 or x.shape[0] < 2 or not x.size:
        raise ValueError("matching nonempty TCHW arrays with at least two frames required")
    if x.dtype.kind != "f" or y.dtype.kind != "f":
        raise ValueError("floating point pixels required")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("finite pixels required")
    tx, ty = np.asarray(reference_times, dtype=np.float64), np.asarray(reconstruction_times, dtype=np.float64)
    if tx.shape != (len(x),) or ty.shape != tx.shape:
        raise ValueError("one presentation timestamp per frame required")
    with np.errstate(over='ignore', invalid='ignore'):
        dt = np.diff(tx)
    if not np.isfinite(tx).all() or not np.isfinite(ty).all() or not np.isfinite(dt).all() or not np.all(dt > 0):
        raise ValueError("finite strictly increasing presentation timestamps required")
    if not np.array_equal(tx, ty):
        raise ValueError("timestamp grids must match exactly; no implicit resampling")
    x, y = x.astype(np.float64), y.astype(np.float64)
    with np.errstate(over='raise', invalid='raise'):
        try:
            dx, dy = np.diff(x, axis=0), np.diff(y, axis=0)
            residual = np.abs(dy - dx)
            aligned = np.abs(y - x)
        except FloatingPointError as error:
            raise ValueError('pixel differences overflow diagnostic domain') from error
    with np.errstate(over='ignore', invalid='ignore'):
        magnitudes = [float(np.abs(dx).mean()), float(np.abs(dy).mean()),
                      float(residual.mean()), float(aligned.mean())]
        intervals = residual.mean(axis=(1, 2, 3))
    if not np.isfinite(magnitudes).all() or not np.isfinite(intervals).all():
        raise ValueError('diagnostic reduction exceeds finite arithmetic domain')
    return {
        "reference_temporal_magnitude": magnitudes[0],
        "reconstruction_temporal_magnitude": magnitudes[1],
        "ordered_delta_mae": magnitudes[2],
        "ordered_delta_mae_by_interval": intervals.tolist(),
        "aligned_frame_mae": magnitudes[3],
        "presentation_times_seconds": tx.tolist(),
        "interval_seconds": dt.tolist(),
        "acceptance_threshold": None,
    }
