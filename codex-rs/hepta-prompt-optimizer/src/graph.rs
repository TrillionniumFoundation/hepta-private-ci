//! Compatibility graph calculator and its reachable regression tests.

#[path = "graph_impl.rs"]
mod implementation;
pub use implementation::GraphBoundPromptPortfolioReceipt;
pub use implementation::optimize_with_factor_graph;

#[cfg(test)]
#[path = "graph_tests.rs"]
mod tests;
