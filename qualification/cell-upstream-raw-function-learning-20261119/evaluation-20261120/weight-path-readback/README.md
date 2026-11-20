# A-only training-to-generation parameter-path readback

The read-only checks find no evidence that the 32-update adapters were omitted, swapped, reinitialized instead of loaded, or disabled by the train/eval transition. No new model was instantiated and no forward, generation, training update, or native child ran.

## Byte evidence

Each fitted adapter contains 112 FP32 tensors across 28 Qwen2 layers, totaling 544,768 scalar parameters:

| Projection | LoRA A shape | LoRA B shape | Per-layer parameters |
| --- | --- | --- | ---: |
| q_proj | [4, 1536] | [1536, 4] | 12,288 |
| v_proj | [4, 1536] | [256, 4] | 7,168 |

The raw safetensors files were read with Python's standard library, without importing torch, PEFT, or transformers. Exact tensor names, dtype, shape, payload intervals and bytes were checked. Their state hashes were recomputed using the actual registered-name order and the trainer's canonical hashing definition.

| Identity | Parameter digest |
| --- | --- |
| Original common P | e5da16c3256c27f06f42ecac69880ce8802a0eb3a87c05830d11c09477aa817f |
| document_evidence, after 32 original updates | a4f553815fbe76ab872522d7f8c9059dc470ec91919c3521dfc8ce17a37cfb1b |
| native_feedback, after 32 original updates | 75cf3aeb09dce01e9ae7dbca94abbd2662db80c9e88a720a646ee75db990ad18 |

Both recomputed candidate hashes match the frozen training manifests and the actual A cold-loader receipts. All 112 candidate tensors in each arm differ from the corresponding P tensor. Every one of the 12 actual A OUTPUT records per arm binds the same arm's actual loaded model/manifest/effective policy identity. Both actual cold-load records report all parameters frozen and the original eager inference engine.

## Inspected execution path

The frozen raw_sft trainer enables gradients only on registered lora_ parameters, passes that same model through backward_group, steps AdamW on those parameters, hashes the changed state, and saves its adapter safetensors. A evaluation selects the exact mode's manifest, verifies the frozen manifest/model identity, and invokes the raw-function Predictor.

Predictor loads the immutable Qwen base, wraps it using PEFT from_pretrained with the mode-specific adapter directory, and checks the actual cold-loaded named-parameter hash against the post-training digest. It assigns that PEFT model to predictor.model. CollectionPolicy retains that predictor and directly calls predictor.model.generate under torch.inference_mode; it does not substitute the parent or call a separate base model.

The inspected PEFT 0.18.0 source initializes the default adapter as active, initializes disable_adapters to false, loads the saved adapter state, and sends causal generation through the injected base model. Vanilla LoRA Linear.forward adds B(A(x)) times alpha/r for the active adapter; here alpha/r is 8/4 = 2. No adapter-disable context or adapter switch appears in the inspected Hepta generation path.

The saved inference_mode=true field controls gradient trainability. It does not remove the active adapter's forward contribution. Likewise, init_lora_weights=true in the saved config does not mean the actual evaluation used an untrained adapter: the subsequent saved-state load and exact parameter hash admission prevent that interpretation.

## Dropout and numerical scope

Training explicitly calls model.train after enabling the original LoRA gradients. Cold inference explicitly calls model.eval and requires_grad_(False). The retained Qwen config has attention_dropout=0 and both adapter configs have lora_dropout=0; PEFT constructs an Identity for zero LoRA dropout. Qwen attention therefore receives zero dropout in both modes.

The training checkpointed-softmax implementation and inference eager implementation remain their separately declared original paths. This inspection does not claim all train/eval numerical details are identical; it finds no dropout mismatch explaining the result.

## Evidence boundaries

The actual saved bytes and A loading/output identities are historical execution evidence. The additional installed PEFT source excerpts are a current exact-file readback, not a newly recovered historical per-token active-adapter trace. No such trace was retroactively invented and no inference was added to obtain one.

The main report is A_WEIGHT_PATH_READBACK.json (SHA256 f42145b29141b1c70d8c01c2448f2ce9ce25b60492030d64cc7f3dc2a02425e7). Exact per-tensor byte evidence is A_ADAPTER_TENSOR_READBACK.json (2839db348e338f5d40fc54b2e3d0419e7a675fb9494b0459bc5fcbba6d1e7039). Source excerpts are A_WEIGHT_PATH_SOURCE_EXCERPTS.json (3f3b66f2147e47f380d847aafd3307e9f1e71a0de26c0fb4d7015acb3113cefb) and A_WEIGHT_ADAPTER_ACTIVATION_SOURCES.json (0b1a57abdd847e8fa2eec1aab28606ad3e69d331ac88af7933f9cfca68b6012c).

The main readback owner exited 0 in 0.268124038 wall seconds / 0.255660331 self CPU seconds, with no torch/PEFT/transformers import or model execution. The original 56-call evaluation, frozen candidates, original losses, future results and NoUpdate decision remain unchanged. This readback does not choose a subsequent training representation or configuration.

