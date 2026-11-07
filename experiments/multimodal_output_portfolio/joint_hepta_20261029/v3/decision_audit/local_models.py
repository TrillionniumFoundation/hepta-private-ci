"""Frozen real local generators; one model family resides in memory at a time.

CPU bfloat16 is explicit. Outputs are a canary, never independent evaluation.
Model files are hash-verified before loading; remote model code is disabled.
"""

import gc
import importlib.metadata
import inspect
import json
from pathlib import Path
import time

from .acquire_models import MODELS, digest_file, resource_snapshot


class LocalModels:
    def __init__(self, vlm_dir, sd_dir, threads=2):
        if type(threads) is not int or not 1 <= threads <= 16:
            raise ValueError("threads must be an integer in [1,16]")
        self.paths = {"vlm": Path(vlm_dir), "sd": Path(sd_dir)}
        self.threads = threads
        self.active = None
        self.model = self.processor = self.pipeline = self.img2img = None
        self.manifests, self.loads = {}, []

    def _verify(self, key):
        path = self.paths[key]; manifest_path = path / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        model, revision, weights = MODELS[key]
        if not manifest.get("complete") or (manifest["model"], manifest["revision"]) != (model, revision):
            raise ValueError("Model manifest is incomplete or uses another revision")
        records = {r["path"]: r for r in manifest["files"]}
        if not set(weights).issubset(records):
            raise ValueError("Pinned weight is absent from model manifest")
        for name, row in records.items():
            file = path / name
            if not file.resolve().is_relative_to(path.resolve()) or file.is_symlink():
                raise ValueError("Model manifest escapes its directory")
            if file.stat().st_size != row["size"] or digest_file(file) != row["sha256"]:
                raise ValueError("Model file differs from its acquisition manifest")
            if name in weights and (row["size"], row["sha256"]) != weights[name]:
                raise ValueError("Weight identity differs from reviewed pin")
        self.manifests[key] = {"model": model, "revision": revision,
                               "manifest_sha256": digest_file(manifest_path),
                               "files": manifest["files"]}

    def _activate(self, key):
        if self.active == key:
            return
        import torch
        started = time.perf_counter()
        self.model = self.processor = self.pipeline = self.img2img = None
        self.active = None; gc.collect()
        self._verify(key)
        torch.set_num_threads(self.threads)
        if key == "vlm":
            from transformers import AutoModelForImageTextToText, AutoProcessor
            self.processor = AutoProcessor.from_pretrained(self.paths[key], local_files_only=True, trust_remote_code=False)
            self.processor.image_processor.size = {"longest_edge": 512}
            self.processor.image_processor.do_image_splitting = False
            self.model = AutoModelForImageTextToText.from_pretrained(
                self.paths[key], local_files_only=True, trust_remote_code=False,
                dtype=torch.bfloat16, attn_implementation="eager", low_cpu_mem_usage=True)
            self.model.eval().requires_grad_(False)
        else:
            from diffusers import StableDiffusionPipeline
            from diffusers.models.model_loading_utils import load_state_dict
            from transformers.modeling_utils import load_state_dict as transformers_load
            if tuple(int(n) for n in torch.__version__.split(".")[:2]) < (2, 6):
                raise RuntimeError("Pinned .bin weights require torch >= 2.6")
            if '"weights_only": True' not in inspect.getsource(load_state_dict):
                raise RuntimeError("Installed diffusion loader does not enforce weights_only=True")
            if inspect.signature(transformers_load).parameters["weights_only"].default is not True:
                raise RuntimeError("Installed transformer loader must default to weights_only=True")
            self.pipeline = StableDiffusionPipeline.from_pretrained(
                self.paths[key], local_files_only=True, torch_dtype=torch.bfloat16,
                use_safetensors=False, low_cpu_mem_usage=True)
            for module in (self.pipeline.unet, self.pipeline.vae, self.pipeline.text_encoder):
                module.eval().requires_grad_(False)
            self.pipeline.set_progress_bar_config(disable=True)
            self.pipeline.enable_attention_slicing(); self.pipeline.enable_vae_slicing()
        self.active = key
        self.loads.append({"model": key, "wall_seconds": time.perf_counter() - started,
                           "resources": resource_snapshot(self.paths[key])})

    def load(self):
        """Actually load both families sequentially; retain only the last one."""
        self._activate("vlm"); self._activate("sd")
        return self

    def describe(self, image_path, prompt, max_tokens=80):
        if type(max_tokens) is not int or not 1 <= max_tokens <= 256 or not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8000:
            raise ValueError("Invalid bounded description request")
        import torch
        from PIL import Image
        self._activate("vlm")
        with Image.open(image_path) as source:
            image = source.convert("RGB"); image.thumbnail((512, 512))
        messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
        rendered = self.processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        inputs = self.processor(text=rendered, images=[image], return_tensors="pt")
        inputs = {k: v.to(dtype=torch.bfloat16) if v.is_floating_point() else v for k, v in inputs.items()}
        with torch.inference_mode():
            generated = self.model.generate(**inputs, max_new_tokens=max_tokens, do_sample=False)
        return self.processor.batch_decode(generated[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()

    def draw(self, prompt, output_path, seed, initial_image=None, steps=12):
        if type(seed) is not int or not 0 <= seed < 2**63 or type(steps) is not int or not 2 <= steps <= 50:
            raise ValueError("Invalid seed or bounded diffusion step count")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8000:
            raise ValueError("Invalid image prompt")
        import torch
        from PIL import Image
        self._activate("sd")
        denoising_steps = []
        def counted_step(pipeline, index, timestep, tensors):
            denoising_steps.append(int(timestep)); return tensors
        args = {"prompt": prompt, "num_inference_steps": steps,
                "generator": torch.Generator(device="cpu").manual_seed(seed), "guidance_scale": 7.5,
                "callback_on_step_end": counted_step}
        if initial_image is None:
            pipeline = self.pipeline; args.update(height=256, width=256)
        else:
            from diffusers import StableDiffusionImg2ImgPipeline
            if self.img2img is None:
                self.img2img = StableDiffusionImg2ImgPipeline(**self.pipeline.components)
                self.img2img.set_progress_bar_config(disable=True)
            pipeline = self.img2img
            with Image.open(initial_image) as source:
                args["image"] = source.convert("RGB").resize((256, 256))
            args["strength"] = 0.65
        with torch.inference_mode():
            result = pipeline(**args)
        output_path = Path(output_path); output_path.parent.mkdir(parents=True, exist_ok=True)
        result.images[0].save(output_path, format="PNG")
        return {"path": str(output_path), "sha256": digest_file(output_path), "size": output_path.stat().st_size,
                "width": 256, "height": 256, "seed": seed, "requested_steps": steps,
                "actual_steps": len(denoising_steps),
                "mode": "text_to_image" if initial_image is None else "image_to_image",
                "nsfw_content_detected": result.nsfw_content_detected}

    def synchronize(self):
        """CPU execution is synchronous; no accelerator barrier is required."""

    def identity(self):
        return {"backend": "frozen_pretrained_local", "device": "cpu", "dtype": "bfloat16",
                "threads": self.threads, "residency": "one_model_family_at_a_time",
                "image_preprocessing": {"longest_edge": 512, "do_image_splitting": False},
                "independent_semantic_scorer": False, "models": self.manifests,
                "reviewed_model_pins": {key: {"model": spec[0], "revision": spec[1]}
                                        for key, spec in MODELS.items()},
                "loads": list(self.loads), "versions": {name: importlib.metadata.version(name)
                    for name in ("torch", "torchvision", "transformers", "diffusers", "accelerate", "safetensors", "num2words")}}
