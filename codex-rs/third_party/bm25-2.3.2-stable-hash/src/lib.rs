#![warn(missing_docs)]
#![cfg_attr(feature = "language_detection", doc = include_str!("../README.md"))]
// Suppress missing docs warning for this file
//!

#[cfg(test)]
mod test_data_loader;

mod embedder;
mod scorer;
mod search;
mod tokenizer;

#[cfg(feature = "default_tokenizer")]
mod default_tokenizer;

#[cfg(feature = "default_tokenizer")]
pub use default_tokenizer::Language;
#[cfg(feature = "default_tokenizer")]
pub use default_tokenizer::LanguageMode;

pub use embedder::DefaultTokenizer;
pub use embedder::Embedder;
pub use embedder::EmbedderBuilder;
pub use embedder::Embedding;
pub use embedder::TokenEmbedder;
pub use embedder::TokenEmbedding;
pub use scorer::ScoredDocument;
pub use scorer::Scorer;
pub use search::Document;
pub use search::SearchEngine;
pub use search::SearchEngineBuilder;
pub use search::SearchResult;
pub use tokenizer::Tokenizer;
