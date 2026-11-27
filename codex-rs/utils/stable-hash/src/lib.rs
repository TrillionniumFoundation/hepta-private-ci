// Copyright 2015 The Rust Project Developers.
// Legacy Fx algorithm originally distributed under MIT OR Apache-2.0.
// Compatibility implementation maintained in this repository; see ../README.md.

//! Owned compatibility implementation for existing Starlark hashes and BM25 token IDs.
//!
//! These two consumers require the original 32-bit and 64-bit Fx hash outputs.
//! Current `rustc-hash` uses a different algorithm, so replacing it by name would
//! change existing IDs. This crate deliberately retains the original native-endian
//! byte encoding, integer handling, overflow, and per-call chunk boundaries.
//! It is not a general-purpose or cryptographic hasher and does not resist collision
//! attacks. New consumers should choose a maintained hash appropriate to their needs.
//!
//! Algorithm provenance and maintenance obligations are recorded in `README.md`.

use std::hash::Hash;
use std::hash::Hasher;

const MULTIPLIER_64: u64 = 0x517c_c1b7_2722_0a95;
const MULTIPLIER_32: u32 = MULTIPLIER_64 as u32;

/// The legacy 32-bit Fx algorithm, retained for BM25's public `u32` token IDs.
#[derive(Clone, Debug, Default)]
pub struct LegacyFxHasher32 {
    state: u32,
}

impl LegacyFxHasher32 {
    #[inline]
    fn mix(&mut self, word: u32) {
        self.state = (self.state.rotate_left(5) ^ word).wrapping_mul(MULTIPLIER_32);
    }
}

impl Hasher for LegacyFxHasher32 {
    #[inline]
    fn finish(&self) -> u64 {
        u64::from(self.state)
    }

    #[inline]
    fn write(&mut self, mut bytes: &[u8]) {
        while let Some((word, rest)) = bytes.split_first_chunk::<4>() {
            self.mix(u32::from_ne_bytes(*word));
            bytes = rest;
        }
        for byte in bytes {
            self.mix(u32::from(*byte));
        }
    }

    #[inline]
    fn write_u8(&mut self, value: u8) {
        self.mix(u32::from(value));
    }

    #[inline]
    fn write_u16(&mut self, value: u16) {
        self.mix(u32::from(value));
    }

    #[inline]
    fn write_u32(&mut self, value: u32) {
        self.mix(value);
    }

    #[inline]
    fn write_u64(&mut self, value: u64) {
        // Legacy Fx32 consumes the low word first even on big-endian targets.
        self.mix(value as u32);
        self.mix((value >> 32) as u32);
    }

    #[inline]
    fn write_usize(&mut self, value: usize) {
        #[cfg(target_pointer_width = "32")]
        self.write_u32(value as u32);
        #[cfg(target_pointer_width = "64")]
        self.write_u64(value as u64);
    }
}

/// The legacy 64-bit Fx algorithm, retained for Starlark and BM25 `u64` IDs.
#[derive(Clone, Debug, Default)]
pub struct LegacyFxHasher64 {
    state: u64,
}

impl LegacyFxHasher64 {
    #[inline]
    fn mix(&mut self, word: u64) {
        self.state = (self.state.rotate_left(5) ^ word).wrapping_mul(MULTIPLIER_64);
    }
}

impl Hasher for LegacyFxHasher64 {
    #[inline]
    fn finish(&self) -> u64 {
        self.state
    }

    #[inline]
    fn write(&mut self, mut bytes: &[u8]) {
        while let Some((word, rest)) = bytes.split_first_chunk::<8>() {
            self.mix(u64::from_ne_bytes(*word));
            bytes = rest;
        }
        if let Some((word, rest)) = bytes.split_first_chunk::<4>() {
            self.mix(u64::from(u32::from_ne_bytes(*word)));
            bytes = rest;
        }
        for byte in bytes {
            self.mix(u64::from(*byte));
        }
    }

    #[inline]
    fn write_u8(&mut self, value: u8) {
        self.mix(u64::from(value));
    }

    #[inline]
    fn write_u16(&mut self, value: u16) {
        self.mix(u64::from(value));
    }

    #[inline]
    fn write_u32(&mut self, value: u32) {
        self.mix(u64::from(value));
    }

    #[inline]
    fn write_u64(&mut self, value: u64) {
        self.mix(value);
    }

    #[inline]
    fn write_usize(&mut self, value: usize) {
        self.mix(value as u64);
    }
}

/// Hash a value using the legacy BM25 32-bit encoding.
#[inline]
pub fn hash32<T: Hash + ?Sized>(value: &T) -> u32 {
    let mut state = LegacyFxHasher32::default();
    value.hash(&mut state);
    state.finish() as u32
}

/// Hash a value using the legacy Starlark/BM25 64-bit encoding.
#[inline]
pub fn hash64<T: Hash + ?Sized>(value: &T) -> u64 {
    let mut state = LegacyFxHasher64::default();
    value.hash(&mut state);
    state.finish()
}

/// Hash a value using the legacy BM25 native-width encoding.
#[inline]
pub fn hash_native<T: Hash + ?Sized>(value: &T) -> usize {
    #[cfg(target_pointer_width = "32")]
    {
        hash32(value) as usize
    }
    #[cfg(target_pointer_width = "64")]
    {
        hash64(value) as usize
    }
}

#[cfg(test)]
#[path = "stable_hash_tests.rs"]
mod tests;
