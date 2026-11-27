use super::LegacyFxHasher32;
use super::LegacyFxHasher64;
use super::hash_native;
use super::hash32;
use super::hash64;
use pretty_assertions::assert_eq;
use std::hash::Hasher;

// Little-endian values were captured from the unmodified official fxhash 0.2.1.
// Big-endian values follow the same documented native-word encoding.
#[test]
fn legacy_token_ids_remain_stable() {
    let cases = [
        (
            "",
            (4209543787, 3117886703346944619),
            (4209543787, 3117886703346944619),
        ),
        (
            "a",
            (119947305, 12269146538841877247),
            (119947305, 12269146538841877247),
        ),
        (
            "hello",
            (1057186640, 15654757048971762880),
            (247256634, 16640468440285071246),
        ),
        (
            "Starlark",
            (3152245439, 4310511854222271950),
            (252219743, 12614583908366731069),
        ),
        (
            "BM25",
            (3929934872, 334088225624291054),
            (2985343588, 15759376799711640424),
        ),
        (
            "你好",
            (4154213552, 12293390251361271088),
            (3136699207, 16764501433714779058),
        ),
        (
            "🦀",
            (492493037, 4218355557983257409),
            (2721690143, 12785515252576418866),
        ),
        (
            "foo_bar",
            (3320122051, 7792321159348785617),
            (1143370330, 8315304049923112739),
        ),
        (
            "a b",
            (615527540, 7640928186353388193),
            (615527540, 7640928186353388193),
        ),
        (
            "résumé",
            (1359339066, 10507376329027295107),
            (1045751248, 4040119207703778704),
        ),
    ];
    for (token, little, big) in cases {
        let (expected32, expected64) = if cfg!(target_endian = "little") {
            little
        } else {
            big
        };
        assert_eq!(hash32(token), expected32, "token {token:?}");
        assert_eq!(hash64(token), expected64, "token {token:?}");
        let native = if cfg!(target_pointer_width = "32") {
            u64::from(expected32)
        } else {
            expected64
        };
        assert_eq!(hash_native(token) as u64, native);
    }
}

#[test]
fn raw_bytes_preserve_native_word_boundaries() {
    let cases = [
        (0, (0, 0), (0, 0)),
        (
            1,
            (300829203, 4208978898528913939),
            (300829203, 4208978898528913939),
        ),
        (
            3,
            (2975111577, 138242242097923497),
            (2975111577, 138242242097923497),
        ),
        (
            4,
            (3723947539, 15794058312761667091),
            (1377770438, 15980011621030239174),
        ),
        (
            7,
            (1016527177, 1247768241607437284),
            (3293607468, 7383470231246336956),
        ),
        (
            8,
            (3445552960, 34652972394147347),
            (2478449352, 11653888551857391114),
        ),
        (
            9,
            (2541611182, 4967171286655862971),
            (65075137, 15161216486321866071),
        ),
        (
            12,
            (3513910446, 6194191046671152315),
            (515802324, 13834576076447280362),
        ),
        (
            16,
            (2480900461, 12414691416687326395),
            (3560028029, 5174474634168546294),
        ),
        (
            31,
            (2144183041, 11071802734812241665),
            (2690913886, 2579538268835097511),
        ),
        (
            32,
            (3542316228, 14415403440074801116),
            (2253249310, 15938376599530827383),
        ),
    ];
    for (len, little, big) in cases {
        let bytes: Vec<u8> = (0..len).map(|i| (i * 13 + 7) as u8).collect();
        let mut hash32 = LegacyFxHasher32::default();
        let mut hash64 = LegacyFxHasher64::default();
        hash32.write(&bytes);
        hash64.write(&bytes);
        let (expected32, expected64) = if cfg!(target_endian = "little") {
            little
        } else {
            big
        };
        assert_eq!(hash32.finish(), expected32, "byte length {len}");
        assert_eq!(hash64.finish(), expected64, "byte length {len}");
    }
}

#[test]
fn separate_write_calls_keep_their_legacy_boundaries() {
    let mut whole = LegacyFxHasher64::default();
    let mut split = LegacyFxHasher64::default();
    whole.write(b"abcdefgh");
    split.write(b"abcd");
    split.write(b"efgh");
    let expected = if cfg!(target_endian = "little") {
        (16295004723668454517, 11238867789943620051)
    } else {
        (12931851135848038280, 4670240345872154540)
    };
    assert_eq!((whole.finish(), split.finish()), expected);
    assert_ne!(whole.finish(), split.finish());
}

#[test]
fn fixed_integer_writes_keep_low_word_first_semantics() {
    let mut hash32 = LegacyFxHasher32::default();
    let mut hash64 = LegacyFxHasher64::default();
    hash32.write_u64(0x0102_0304_0506_0708);
    hash64.write_u64(0x0102_0304_0506_0708);
    assert_eq!(hash32.finish(), 3372988305);
    assert_eq!(hash64.finish(), 13840280874292635560);
}
