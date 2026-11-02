"""Development-only diagnosis of the v3 typed-binding numerical refusal."""

import json
from pathlib import Path

import torch

from . import adapter, audit


def run():
    torch.set_num_threads(1)
    model = audit.typed_retention.install(audit.model_for("binding"))
    candidate = adapter.ExactAddressedAdapter(model, "joint_online")
    arrays = audit.data.batch("binding", 3, 972582, "dev", "long_tokens_128")
    x, dt, seen = [torch.from_numpy(arrays[k]) for k in ("x", "dt", "observed")]
    before, after = [], []
    hook = model.read.register_forward_pre_hook(lambda module, args: before.append(args[0].detach().clone()))
    original = adapter._SCRIPTED_READ

    def capture(features, *args):
        after.append(features.detach().clone())
        return original(features, *args)

    with torch.no_grad():
        reference = model(x, dt, seen)
        hook.remove()
        expected = torch.stack(before, 1)
        adapter._SCRIPTED_READ = capture
        actual = candidate(x, dt, seen)
        adapter._SCRIPTED_READ = original
        contiguous = torch.stack([model.read(after[0][:, t].contiguous()) for t in range(x.shape[1])], 1)
    result = dict(source_sha256={str(p.relative_to(audit.ROOT)): audit.digest(p) for p in
                                 [Path(__file__), Path(adapter.__file__)]},
                  case="Original dev003 typed-binding engineering sample, not new confirmation",
                  feature_error=float((expected - after[0]).abs().max()),
                  original_feature_stride=list(before[0].stride()),
                  stacked_slice_stride=list(after[0][:, 0].stride()),
                  scripted_output_error=float((reference - actual).abs().max()),
                  contiguous_decoder_error=float((reference - contiguous).abs().max()))
    audit.write(audit.HERE / "V3_READ_LAYOUT_DIAGNOSIS.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    run()
