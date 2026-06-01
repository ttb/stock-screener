"""Unit tests for the IBD classification health report + gate (pure, no DB)."""
from app.services.ibd_classification_health import (
    HISTOGRAM_BINS,
    confidence_histogram,
)


def test_confidence_histogram_bins_and_null():
    rows = [
        {"confidence": 0.91},   # -> [0.9,1.0]
        {"confidence": 1.0},    # -> [0.9,1.0] (clamped)
        {"confidence": 0.8},    # -> [0.8,0.9)
        {"confidence": 0.05},   # -> [0.0,0.1)
        {"confidence": None},   # -> null (LLM rows carry no confidence)
    ]
    hist = confidence_histogram(rows)

    assert hist["[0.9,1.0]"] == 2
    assert hist["[0.8,0.9)"] == 1
    assert hist["[0.0,0.1)"] == 1
    assert hist["null"] == 1
    # Every bin is always present (zero-initialised) plus the null bucket.
    assert set(hist) == set(HISTOGRAM_BINS) | {"null"}
    # Counts sum to the row count.
    assert sum(hist.values()) == len(rows)
