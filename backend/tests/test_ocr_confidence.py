import pytest

from app.services.ocr_service import _confidence_from_tesseract_data


def test_confidence_averages_valid_word_scores():
    ocr_data = {"conf": ["90", "80", "-1", "70"]}  # -1 = non-text region, excluded
    assert _confidence_from_tesseract_data(ocr_data) == 0.8


def test_confidence_defaults_to_full_confidence_when_no_words_detected():
    ocr_data = {"conf": ["-1", "-1"]}
    assert _confidence_from_tesseract_data(ocr_data) == 1.0


def test_confidence_handles_empty_input():
    assert _confidence_from_tesseract_data({}) == 1.0


def test_confidence_low_quality_scan():
    ocr_data = {"conf": ["20", "35", "40"]}
    assert _confidence_from_tesseract_data(ocr_data) == pytest.approx(0.3167, abs=0.001)
