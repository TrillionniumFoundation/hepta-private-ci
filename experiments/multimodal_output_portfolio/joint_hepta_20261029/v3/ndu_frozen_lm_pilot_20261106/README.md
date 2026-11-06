# Pinned local language-model tool pilot

This is a bounded engineering pilot, separate from the failed learned-stateful
study and from any independent scientific confirmation. It supplies an actual
frozen pretrained language model where previous local checks had none. It does
not establish a new RL algorithm, independent quality gain or lifecycle benefit.

The public model is HuggingFaceTB/SmolLM2-135M-Instruct at immutable revision
`12fd25f77366fa6b3b4b768ec3050bf629380bac`, licensed Apache-2.0 by its publisher.
The model card describes CPU use:
https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct/blob/12fd25f77366fa6b3b4b768ec3050bf629380bac/README.md

Acquisition verifies upstream LFS SHA-256 for the safetensors weights and Git
blob identities for small configuration/tokenizer files. Each attempt records a
durable intent before execution and a terminal outcome, including failures.
Original partial downloads and install logs are retained. No model repository
Python code or pickle weights are executed. The inference stage will use local
files only, frozen parameters and deterministic decoding.

Dependencies are installed in an isolated environment. Installation, downloading,
model hashing/loading, tokenization, generation, tools and verification are
resource costs. The ledger records elapsed and CPU time; a zero external model
API bill does not make host computation free. Actual host currency cost remains
unknown until real allocation/billing material is available.

The eventual pilot uses disclosed engineering tasks. Prompts, methods and limits
must be frozen before model task outputs are inspected. Failures are retained,
and no prompt tuning or task selection follows outcome inspection. This does not
replace an untouched source-cluster confirmation set.
