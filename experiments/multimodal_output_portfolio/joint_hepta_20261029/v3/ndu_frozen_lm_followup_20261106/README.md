# One frozen model follow-up on disclosed development tasks

The preceding 135M pilot completed 16 actual model requests. Every task response
failed the registered exact-JSON contract; neither arm delivered a correct
answer and no model-selected tool ran. Those outcomes are preserved unchanged.
This follow-up asks whether a larger instruction model can exercise the same
bounded tool pipeline. It is an engineering development study, not confirmation
of an NDU policy, an unbiased model comparison or a net-benefit claim.

## Fixed changes before this model is run

- Use `Qwen/Qwen2.5-0.5B-Instruct` at revision
  `7ae557604adf67be50417f59c2c2f167def9a775` with the exact published file manifest.
- Extend request supervision to 60 seconds, episode supervision to 130 seconds
  and the overall supervision budget to 1800 seconds to allow CPU loading.
- Keep all eight disclosed tasks, both arms, task order, prompts, parser,
  maximum output tokens, parameter checks, tools and verifier unchanged.
- Reuse the existing isolated runtime, recording its full package inventory.
  Attribute the shared installation to the combined development effort once;
  its reuse does not erase acquisition or computation costs.

The upstream model card is
<https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct/blob/7ae557604adf67be50417f59c2c2f167def9a775/README.md>.
The public files are Apache-2.0. No paid model endpoint or credential is used.
Download attempts use the unchanged metered acquisition functions from the
preceding pilot and retain failures. Only this one follow-up model is declared;
additional model selection is outside this protocol.

## Execution contract

Acquire only the registered safe tensors and tokenizer/configuration files.
No repository code or pickle weights run. Save the materialized hashes and
runtime inventory, then publish a source/task freeze before any model forward.
The runner refuses a missing or changed freeze. Run the separate `[1]`
qualification, then every planned task regardless of quality. Strict malformed
outputs remain failures; no extraction, parser repair, task deletion or fallback
answer is permitted. Preserve request intent, terminal records, raw responses,
actual wall/CPU usage and all episode outcomes.

The earlier results motivated the model choice, and the task bank is reused.
Consequently the new results remain disclosed development evidence even if
they improve. A single successful tool sequence would establish execution
capability, not an NDU advantage or generalization. Host monetary cost remains
unknown. POSIX supervision is not a hard real-time scheduling guarantee.
