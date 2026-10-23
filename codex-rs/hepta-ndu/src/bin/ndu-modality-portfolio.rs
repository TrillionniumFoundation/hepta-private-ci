//! Separately versioned MP1 research executable; never a production dispatcher.

#[path = "../modality_portfolio.rs"]
mod modality_portfolio;
#[path = "../modality_portfolio_protocol.rs"]
mod modality_portfolio_protocol;

fn main() -> std::io::Result<()> {
    modality_portfolio_protocol::run(std::io::stdin().lock(), std::io::stdout().lock())
}
