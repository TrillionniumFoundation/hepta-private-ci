"""Fixed temporal features from delivered media; no labels enter this module."""

from pathlib import Path
from urllib.request import Request, urlopen
import json

from .natural_data import OLD, digest


def download_pretrained(destination):
    """Reuse the three original publisher URLs and byte/SHA256 identities."""
    from ..closure_20261028.semantic_backbones import PINS
    from ..closure_20261028.semantic_tsm import TSM_FILE, TSM_SHA
    expected = {**PINS, TSM_FILE: TSM_SHA}
    manifest = json.loads((OLD / "semantic_top1_v4/ci/PILOT.json").read_text())
    rows = [row for row in manifest["weights"] if row["name"] in expected]
    if len(rows) != 3 or any(row["sha256"] != expected[row["name"]] for row in rows):
        raise ValueError("Original publisher checkpoint manifest changed")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for row in rows:
        path = destination / row["name"]
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".pending")
            with urlopen(Request(row["url"], headers={"User-Agent": "hepta-observer-v2/1"}), timeout=120) as response:
                with temporary.open("xb") as stream:
                    total = 0
                    while block := response.read(min(1048576, row["bytes"] - total + 1)):
                        total += len(block)
                        if total > row["bytes"]:
                            raise ValueError("Checkpoint exceeded its original byte bound")
                        stream.write(block)
            if temporary.stat().st_size != row["bytes"] or digest(temporary.read_bytes()) != row["sha256"]:
                raise ValueError("Downloaded publisher checkpoint identity mismatch")
            temporary.replace(path)
        if path.stat().st_size != row["bytes"] or digest(path.read_bytes()) != row["sha256"]:
            raise ValueError("Cached publisher checkpoint identity mismatch")
    return rows


def temporal_audio_features(model, waveform):
    """One frozen PANN forward, then global and three fixed temporal pools."""
    import numpy as np
    import torch
    from scipy.signal import resample_poly
    from torch.nn import functional as F
    waveform = np.asarray(waveform, np.float32)
    if waveform.ndim != 2 or waveform.shape[1] != 32000 or not np.isfinite(waveform).all():
        raise ValueError("Expected finite two-second 16 kHz delivered PCM")
    with torch.no_grad():
        x = torch.from_numpy(resample_poly(waveform, 2, 1, axis=1).copy())
        x = F.pad(x[:, None], (512, 512), mode="reflect")
        stft = model.spectrogram_extractor.stft
        power = (stft.conv_real(x).square() + stft.conv_imag(x).square()).transpose(1, 2)
        mel = 10.0 * torch.log10((power @ model.logmel_extractor.melW).clamp_min(1e-10))
        x = model.bn0(mel[:, None].transpose(1, 3)).transpose(1, 3)
        hidden = model.features(x).mean(3)
        if hidden.shape[2] < 3:
            raise ValueError("Registered temporal pooling requires three nonempty bins")
        pools = [hidden, *torch.tensor_split(hidden, 3, dim=2)]
        features = []
        for block in pools:
            embedding = F.relu(model.fc1(block.amax(2) + block.mean(2)))
            features.append(torch.cat((embedding, torch.sigmoid(model.fc_audioset(embedding))), 1))
        return torch.cat(features, 1).cpu().numpy()


class ObserverBackbones:
    """The prepare_role feature interface, retaining independent baseline blocks."""

    def __init__(self, root):
        from ..closure_20261028.semantic_backbones import SemanticBackbones
        from ..closure_20261028.semantic_tsm import TsmObserver
        self.base = SemanticBackbones(root)
        self.tsm = TsmObserver(root)

    def features(self, frames, waveform):
        import numpy as np
        video = np.concatenate((self.base.video_features(frames), self.tsm.features(frames)), axis=1)
        audio = temporal_audio_features(self.base.audio, waveform)
        if video.shape[1] != 3646 or audio.shape[1] != 6204:
            raise ValueError("Unexpected registered v2 feature width")
        return video, audio, {"video_width": 3646, "audio_width": 6204}
