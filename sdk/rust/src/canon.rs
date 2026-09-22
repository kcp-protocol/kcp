//! Python-compatible canonical JSON encoder.
//!
//! The reference SDK signs `json.dumps(payload, sort_keys=True,
//! separators=(",", ":"))`. Python's `json.dumps` defaults to
//! `ensure_ascii=True`, which means every non-ASCII code point is emitted as a
//! `\uXXXX` escape (surrogate pairs above the BMP) and control characters
//! below `0x20` are escaped as well. `serde_json` does none of that, so a
//! naive `serde_json::to_string` would produce a *different byte string* for
//! any artifact containing accents, emoji or tabs — and therefore a different
//! Ed25519 signature.
//!
//! This module re-implements the exact Python output format:
//!
//! * object keys sorted by code point (UTF-8 byte order is equivalent),
//! * `,` / `:` separators, no whitespace,
//! * strings escaped with `ensure_ascii=True` semantics,
//! * numbers rendered with Python's `repr()` conventions for the common
//!   cases (integers as-is, floats shortest-round-trip, exponent form padded
//!   to two digits and always signed).

use serde_json::Value;

/// Serialize a JSON value exactly like Python's
/// `json.dumps(value, sort_keys=True, separators=(",", ":"))`.
pub fn canonical_json(value: &Value) -> String {
    let mut out = String::new();
    write_value(&mut out, value);
    out
}

/// Convenience wrapper returning the canonical bytes (what gets signed).
pub fn canonical_bytes(value: &Value) -> Vec<u8> {
    canonical_json(value).into_bytes()
}

fn write_value(out: &mut String, value: &Value) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(n) => out.push_str(&format_number(n)),
        Value::String(s) => write_py_string(out, s),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_value(out, item);
            }
            out.push(']');
        }
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            // UTF-8 byte order == Unicode code point order, same as Python's
            // default string comparison.
            keys.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
            out.push('{');
            for (i, key) in keys.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_py_string(out, key);
                out.push(':');
                write_value(out, map.get(*key).expect("key exists"));
            }
            out.push('}');
        }
    }
}

/// Escape a string the way Python's `json.encoder` does with
/// `ensure_ascii=True`.
pub fn write_py_string(out: &mut String, s: &str) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c if (c as u32) <= 0x7e => out.push(c),
            c => {
                let cp = c as u32;
                if cp <= 0xffff {
                    out.push_str(&format!("\\u{:04x}", cp));
                } else {
                    // Encode as a UTF-16 surrogate pair, like Python.
                    let v = cp - 0x1_0000;
                    let hi = 0xd800 + (v >> 10);
                    let lo = 0xdc00 + (v & 0x3ff);
                    out.push_str(&format!("\\u{:04x}\\u{:04x}", hi, lo));
                }
            }
        }
    }
    out.push('"');
}

/// Render a JSON number the way Python's `json.dumps` does for the values the
/// KCP payloads actually contain.
fn format_number(n: &serde_json::Number) -> String {
    if let Some(i) = n.as_i64() {
        return i.to_string();
    }
    if let Some(u) = n.as_u64() {
        return u.to_string();
    }
    match n.as_f64() {
        Some(f) => py_float_repr(f),
        None => n.to_string(),
    }
}

/// `repr()`-compatible float formatting (shortest round-trip + Python's
/// exponent notation `1e+20` / `1e-07`).
pub fn py_float_repr(f: f64) -> String {
    if f.is_nan() {
        return "NaN".to_string();
    }
    if f.is_infinite() {
        return if f > 0.0 { "Infinity" } else { "-Infinity" }.to_string();
    }

    // serde_json/ryu already produce the shortest round-trip representation,
    // but with Rust-style exponents ("1e20" instead of Python's "1e+20").
    let raw = serde_json::Number::from_f64(f)
        .map(|n| n.to_string())
        .unwrap_or_else(|| format!("{}", f));

    let lower = raw.to_ascii_lowercase();
    match lower.find('e') {
        None => {
            // Python always prints a fractional part for floats ("1.0").
            if lower.contains('.') {
                raw
            } else {
                format!("{}.0", raw)
            }
        }
        Some(idx) => {
            let (mantissa, exp) = raw.split_at(idx);
            let exp = &exp[1..];
            let (sign, digits) = match exp.strip_prefix('-') {
                Some(rest) => ("-", rest),
                None => ("+", exp.strip_prefix('+').unwrap_or(exp)),
            };
            let digits = if digits.len() < 2 {
                format!("0{}", digits)
            } else {
                digits.to_string()
            };
            // Python does not pad the mantissa in exponent form (repr(1e20)
            // == '1e+20', not '1.0e+20').
            format!("{}e{}{}", mantissa, sign, digits)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn sorts_keys_and_compacts() {
        let v = json!({"b": 1, "a": 2});
        assert_eq!(canonical_json(&v), r#"{"a":2,"b":1}"#);
    }

    #[test]
    fn empty_containers() {
        assert_eq!(canonical_json(&json!({})), "{}");
        assert_eq!(canonical_json(&json!([])), "[]");
    }

    #[test]
    fn ascii_is_literal() {
        assert_eq!(canonical_json(&json!("~ok")), r#""~ok""#);
    }

    #[test]
    fn non_ascii_is_escaped_like_python() {
        // Python: json.dumps("ção") -> '"\\u00e7\\u00e3o"'
        assert_eq!(canonical_json(&json!("ção")), r#""\u00e7\u00e3o""#);
    }

    #[test]
    fn del_char_is_escaped() {
        // Python escapes 0x7f because ensure_ascii covers > 0x7e
        assert_eq!(canonical_json(&json!("\u{7f}")), r#""\u007f""#);
    }

    #[test]
    fn astral_plane_uses_surrogate_pair() {
        assert_eq!(canonical_json(&json!("🚀")), r#""\ud83d\ude80""#);
    }

    #[test]
    fn control_chars() {
        assert_eq!(
            canonical_json(&json!("a\tb\nc\rd\u{8}\u{c}\u{1}")),
            r#""a\tb\nc\rd\b\f\u0001""#
        );
    }

    #[test]
    fn quotes_and_backslashes() {
        assert_eq!(canonical_json(&json!("a\"b\\c")), r#""a\"b\\c""#);
    }

    #[test]
    fn nested_objects_are_sorted_recursively() {
        assert_eq!(
            canonical_json(&json!({"z": {"b": 1, "a": []}})),
            r#"{"z":{"a":[],"b":1}}"#
        );
    }

    #[test]
    fn integers_and_floats() {
        assert_eq!(canonical_json(&json!(1)), "1");
        assert_eq!(canonical_json(&json!(1.0)), "1.0");
        assert_eq!(canonical_json(&json!(0.5)), "0.5");
        assert_eq!(canonical_json(&json!(-0.125)), "-0.125");
    }

    #[test]
    fn float_exponent_is_python_style() {
        assert_eq!(py_float_repr(1e20), "1e+20");
        assert_eq!(py_float_repr(1e-7), "1e-07");
        assert_eq!(py_float_repr(0.0001), "0.0001");
    }

    #[test]
    fn special_floats() {
        assert_eq!(py_float_repr(f64::NAN), "NaN");
        assert_eq!(py_float_repr(f64::INFINITY), "Infinity");
        assert_eq!(py_float_repr(f64::NEG_INFINITY), "-Infinity");
    }

    #[test]
    fn booleans_and_null() {
        assert_eq!(
            canonical_json(&json!({"a": true, "b": false, "c": null})),
            r#"{"a":true,"b":false,"c":null}"#
        );
    }
}
