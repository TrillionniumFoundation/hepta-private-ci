"""Evidence-bound assimilation proposals; no service admission or activation."""

from .proposal import (
    AssimilationProposalBundle,
    ProposalError,
    build_assimilation_proposal,
)

__all__ = ["AssimilationProposalBundle", "ProposalError", "build_assimilation_proposal"]
