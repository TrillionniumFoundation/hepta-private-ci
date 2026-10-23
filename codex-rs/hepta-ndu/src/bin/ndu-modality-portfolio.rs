//! Separately versioned MP1 research executable; never a production dispatcher.

#[path = "../modality_portfolio.rs"]
mod modality_portfolio;

fn main() -> std::io::Result<()> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "MP1 state owner only: TSV transport is not installed in this review stage",
    ))
}
