// Keep the canonical bounded runner at its established module path. The base
// implementation uses the same Agentd coordinator, owner adapters and learning
// writer; it only adds independent worker supervision and owner-backed Prompt
// delivery integrity.
include!("intelligence_product_runner_base.rs");
