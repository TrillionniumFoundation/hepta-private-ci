/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

use p256::elliptic_curve::rand_core::TryCryptoRng;
use p256::elliptic_curve::rand_core::TryRng;
use rand::RngCore;
use std::convert::Infallible;

/// Bridge the existing, OS-seeded `StdRng` to P-256's newer RNG traits.
/// This forwards every draw without changing the generator or its seeding.
pub(super) struct SigningRng(pub(super) rand::rngs::StdRng);

impl TryRng for SigningRng {
    type Error = Infallible;

    fn try_next_u32(&mut self) -> Result<u32, Self::Error> {
        Ok(self.0.next_u32())
    }

    fn try_next_u64(&mut self) -> Result<u64, Self::Error> {
        Ok(self.0.next_u64())
    }

    fn try_fill_bytes(&mut self, bytes: &mut [u8]) -> Result<(), Self::Error> {
        self.0.fill_bytes(bytes);
        Ok(())
    }
}

// StdRng already implements rand 0.8's CryptoRng; this bridge neither buffers
// output nor substitutes a different entropy source.
impl TryCryptoRng for SigningRng {}
