"""Unit tests for Vietnamese normalization, abbreviation expansion, Jaro-Winkler, and phonetics."""

from app.core.normalizer import (
    generate_name_variants,
    jaro_winkler_similarity,
    normalize_org_or_location,
    normalize_text,
    phonetic_vietnamese_key,
    string_similarity,
    strip_vietnamese_accents,
)


def test_strip_vietnamese_accents_handles_d_stroke() -> None:
    assert strip_vietnamese_accents("Đặng Nguyễn Minh Tuấn") == "Dang Nguyen Minh Tuan"
    assert strip_vietnamese_accents("đại học bách khoa") == "dai hoc bach khoa"


def test_normalize_text_strips_punctuation_and_spaces() -> None:
    assert normalize_text("  TP.HCM — Việt Nam! ") == "tp hcm viet nam"


def test_normalize_org_or_location_expands_abbreviations() -> None:
    assert normalize_org_or_location("HCMUT") == "dai hoc bach khoa thanh pho ho chi minh"
    assert normalize_org_or_location("ĐHBK HN") == "dai hoc bach khoa ha noi"


def test_generate_name_variants_produces_expected_handles() -> None:
    variants = generate_name_variants("Nguyễn Văn An")
    assert "nguyen van an" in variants
    assert "nguyenvanan" in variants
    assert "nguyen_van_an" in variants
    assert "an nguyen" in variants
    assert "nva" in variants


def test_jaro_winkler_and_phonetic_vietnamese_matching() -> None:
    assert phonetic_vietnamese_key("Nguyễn Ngọc Quý") == phonetic_vietnamese_key("Nguyen Ngoc Qui")
    assert jaro_winkler_similarity("nguyenvanan", "nguyenvanam") > 0.9
    high = string_similarity("Nguyễn Ngọc Quý", "Nguyen Ngoc Qui")
    low = string_similarity("Nguyễn Văn An", "Trần Thị Bình")
    assert high > 0.85
    assert low < 0.4
