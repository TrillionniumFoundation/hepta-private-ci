fn main() { let values = Vec::from([1_u32, 2, 3, 4]); let total: u32 = values.iter().sum(); assert_eq!(total, 10); println!("rust-toolchain-smoke:{total}"); }
