# IBD Classification Data-Health Scorecard + Regression Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every weekly IBD classification run emits a per-market health report (coverage, tier mix, confidence histogram, embedding-model fingerprint, week-over-week churn) as a release asset, and a build-time gate blocks publishing a bundle whose churn or coverage breaches configured thresholds.

**Architecture:** A new pure-Python module (`ibd_classification_health.py`) computes the health report from the freshly-built payload plus the *previous* week's bundle (downloaded from the release before the new one is uploaded). The `build_ibd_classification_bundle.py` script writes the report alongside the bundle/manifest. A tiny dependency-free CLI (`check_ibd_classification_gate.py`) evaluates thresholds and exits non-zero in `enforce` mode. The `ibd-classification.yml` workflow downloads the prior bundle, builds, uploads the health report (always, for observability), then runs the gate — a failed gate fails the job *before* the bundle/manifest upload step runs, so last week's good `-latest` manifest stays referenced and static-site's existing `continue-on-error` IBD step falls back to it.

**Tech Stack:** Python 3.11, pytest (sqlite/in-memory + pure functions, no DB needed for the new code), GitHub Actions (`gh` CLI), gzip/JSON bundles.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `backend/app/services/ibd_classification_health.py` | Pure functions: confidence histogram, week-over-week diff, health-report assembly, asset naming + I/O, gate evaluation. No DB, no network. | **Create** |
| `backend/app/scripts/check_ibd_classification_gate.py` | Thin CLI over `evaluate_gate` + `read_health_report`; exits 1 in `enforce` mode on breach. | **Create** |
| `backend/app/scripts/build_ibd_classification_bundle.py` | Add `--prev-bundle`, an embedding-model constant, and a call that writes the health report next to the bundle/manifest. | **Modify** |
| `.github/workflows/ibd-classification.yml` | Add `gate_mode` dispatch input; download prior bundle; pass `--prev-bundle`; upload health report; run gate before the bundle upload. | **Modify** |
| `backend/tests/unit/test_ibd_classification_health.py` | Unit tests for every function in the health module + the gate CLI. | **Create** |

**No change needed to `release-asset-cleanup.yml`** — verified in Self-Review below. The health asset name `ibd-classification-health-{market}.json` matches none of the cleanup's dated patterns (`^ibd-classification-(?P<market>[a-z]{2})-(?P<date>\d{8})-.+\.json\.gz$`), so `asset_market_date()` returns `None` and the asset is preserved as non-dated. It is re-uploaded with `--clobber`, so it never accumulates.

**Setup for every task** (run once per session, from the repo root):
```bash
cd backend
source venv/bin/activate
```

---

### Task 1: Health module — confidence histogram

**Files:**
- Create: `backend/app/services/ibd_classification_health.py`
- Test: `backend/tests/unit/test_ibd_classification_health.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_ibd_classification_health.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ibd_classification_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.ibd_classification_health'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/ibd_classification_health.py`:

```python
"""Health scorecard + regression gate for IBD classification bundles.

Pure functions (no DB, no network): given the freshly-built bundle payload and,
optionally, the previous week's payload, produce a per-market health report —
coverage, tier mix, a confidence histogram, the embedding-model fingerprint, and
a week-over-week churn diff — and evaluate it against configurable thresholds.

The report is published as the ``ibd-classification-health-<market>.json`` release
asset next to the bundle/manifest. The gate runs at build time so a regression is
blocked before the new bundle is uploaded; the prior good ``-latest`` manifest then
stays referenced and the static-site build falls back to it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

HEALTH_REPORT_SCHEMA_VERSION = 1

HISTOGRAM_BINS = [
    "[0.0,0.1)", "[0.1,0.2)", "[0.2,0.3)", "[0.3,0.4)", "[0.4,0.5)",
    "[0.5,0.6)", "[0.6,0.7)", "[0.7,0.8)", "[0.8,0.9)", "[0.9,1.0]",
]


def confidence_histogram(rows: Iterable[dict]) -> dict[str, int]:
    """Bucket assignment confidences into ten 0.1-width bins plus a null bucket.

    crosswalk/embedding rows carry a float confidence; llm rows carry None.
    """
    hist: dict[str, int] = {b: 0 for b in HISTOGRAM_BINS}
    hist["null"] = 0
    for row in rows:
        confidence = row.get("confidence")
        if confidence is None:
            hist["null"] += 1
            continue
        if confidence >= 1.0:
            hist[HISTOGRAM_BINS[-1]] += 1
            continue
        idx = int(confidence * 10)
        idx = max(0, min(idx, 9))
        hist[HISTOGRAM_BINS[idx]] += 1
    return hist
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ibd_classification_health.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ibd_classification_health.py backend/tests/unit/test_ibd_classification_health.py
git commit -m "feat(ibd): add confidence histogram for classification health report"
```

---

### Task 2: Health module — week-over-week diff

**Files:**
- Modify: `backend/app/services/ibd_classification_health.py`
- Test: `backend/tests/unit/test_ibd_classification_health.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/test_ibd_classification_health.py`:

```python
from app.services.ibd_classification_health import diff_classifications


def test_diff_classifications_counts_and_churn():
    prev = [
        {"symbol": "A", "industry_group": "G1"},
        {"symbol": "B", "industry_group": "G2"},
        {"symbol": "C", "industry_group": "G3"},  # removed next week
    ]
    new = [
        {"symbol": "A", "industry_group": "G1"},  # unchanged
        {"symbol": "B", "industry_group": "G9"},  # changed group
        {"symbol": "D", "industry_group": "G4"},  # added
    ]

    diff = diff_classifications(prev, new)

    assert diff["compared"] == 2          # A, B present both weeks
    assert diff["changed_group"] == 1     # B
    assert diff["added"] == 1             # D
    assert diff["removed"] == 1           # C
    assert diff["churn_pct"] == 50.0      # 1 changed / 2 compared
    assert {"symbol": "B", "prev": "G2", "new": "G9"} in diff["changed_examples"]


def test_diff_classifications_empty_prev_is_zero_churn():
    diff = diff_classifications([], [{"symbol": "A", "industry_group": "G1"}])
    assert diff["compared"] == 0
    assert diff["added"] == 1
    assert diff["churn_pct"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ibd_classification_health.py -v -k diff`
Expected: FAIL with `ImportError: cannot import name 'diff_classifications'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/services/ibd_classification_health.py`:

```python
def diff_classifications(prev_rows: Iterable[dict], new_rows: Iterable[dict]) -> dict:
    """Compare two weeks of classifications keyed by symbol.

    ``churn_pct`` is the share of symbols *present in both weeks* whose industry
    group changed — the signal for "did classifications shift unexpectedly".
    Symbols added/removed across weeks are reported separately so a normal
    universe refresh isn't mistaken for churn.
    """
    prev = {r["symbol"]: r.get("industry_group") for r in prev_rows}
    new = {r["symbol"]: r.get("industry_group") for r in new_rows}
    prev_keys, new_keys = set(prev), set(new)
    common = prev_keys & new_keys
    changed = sorted(s for s in common if prev[s] != new[s])
    compared = len(common)
    return {
        "compared": compared,
        "added": len(new_keys - prev_keys),
        "removed": len(prev_keys - new_keys),
        "changed_group": len(changed),
        "churn_pct": round(100.0 * len(changed) / compared, 2) if compared else 0.0,
        "changed_examples": [
            {"symbol": s, "prev": prev[s], "new": new[s]} for s in changed[:50]
        ],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ibd_classification_health.py -v -k diff`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ibd_classification_health.py backend/tests/unit/test_ibd_classification_health.py
git commit -m "feat(ibd): add week-over-week classification churn diff"
```

---

### Task 3: Health module — report assembly + asset I/O

**Files:**
- Modify: `backend/app/services/ibd_classification_health.py`
- Test: `backend/tests/unit/test_ibd_classification_health.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/test_ibd_classification_health.py`:

```python
from app.services.ibd_classification_health import (
    HEALTH_REPORT_SCHEMA_VERSION,
    build_health_report,
    health_asset_name,
    read_health_report,
    write_health_report,
)


def _payload(rows, *, as_of, summary):
    return {
        "market": "HK",
        "as_of_date": as_of,
        "generated_at": f"{as_of}T00:00:00Z",
        "source_revision": f"ibd:{as_of}",
        "model_id": "deepseek-chat",
        "summary": summary,
        "classifications": rows,
    }


def test_build_health_report_with_prev():
    new = _payload(
        [{"symbol": "A", "industry_group": "G1", "confidence": 0.9},
         {"symbol": "B", "industry_group": "G9", "confidence": None}],
        as_of="2026-06-02",
        summary={"coverage_pct": 96.0, "by_source": {"embedding": 1, "llm": 1}},
    )
    prev = _payload(
        [{"symbol": "A", "industry_group": "G1", "confidence": 0.9},
         {"symbol": "B", "industry_group": "G2", "confidence": 0.7}],
        as_of="2026-05-26",
        summary={"coverage_pct": 95.0},
    )

    report = build_health_report(
        payload=new, prev_payload=prev, embedding_model="all-MiniLM-L6-v2"
    )

    assert report["schema_version"] == HEALTH_REPORT_SCHEMA_VERSION
    assert report["market"] == "HK"
    assert report["embedding_model"] == "all-MiniLM-L6-v2"
    assert report["summary"]["coverage_pct"] == 96.0
    assert report["confidence_histogram"]["null"] == 1
    assert report["diff"]["changed_group"] == 1          # B changed
    assert report["diff"]["churn_pct"] == 50.0
    assert report["diff"]["prev_as_of_date"] == "2026-05-26"
    assert report["diff"]["prev_source_revision"] == "ibd:2026-05-26"


def test_build_health_report_without_prev_has_null_diff():
    new = _payload(
        [{"symbol": "A", "industry_group": "G1", "confidence": 0.9}],
        as_of="2026-06-02",
        summary={"coverage_pct": 96.0},
    )
    report = build_health_report(payload=new, prev_payload=None, embedding_model="x")
    assert report["diff"] is None


def test_health_asset_name_and_roundtrip(tmp_path):
    assert health_asset_name("SG") == "ibd-classification-health-sg.json"

    report = {"schema_version": 1, "market": "SG", "summary": {"coverage_pct": 90.0}}
    path = tmp_path / health_asset_name("SG")
    write_health_report(path, report)
    assert path.read_text().endswith("\n")
    assert read_health_report(path) == report
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ibd_classification_health.py -v -k "report or asset_name"`
Expected: FAIL with `ImportError: cannot import name 'build_health_report'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/services/ibd_classification_health.py`:

```python
def build_health_report(
    *,
    payload: dict[str, Any],
    prev_payload: dict[str, Any] | None,
    embedding_model: str | None,
) -> dict:
    """Assemble the per-market health report from a fresh payload (+ prior week)."""
    rows = payload.get("classifications", [])
    diff = None
    if prev_payload is not None:
        diff = diff_classifications(prev_payload.get("classifications", []), rows)
        diff["prev_as_of_date"] = prev_payload.get("as_of_date")
        diff["prev_source_revision"] = prev_payload.get("source_revision")
    return {
        "schema_version": HEALTH_REPORT_SCHEMA_VERSION,
        "market": payload.get("market"),
        "as_of_date": payload.get("as_of_date"),
        "generated_at": payload.get("generated_at"),
        "model_id": payload.get("model_id"),
        "embedding_model": embedding_model,
        "summary": payload.get("summary", {}),
        "confidence_histogram": confidence_histogram(rows),
        "diff": diff,
    }


def health_asset_name(market: str) -> str:
    return f"ibd-classification-health-{market.lower()}.json"


def write_health_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def read_health_report(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ibd_classification_health.py -v -k "report or asset_name"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ibd_classification_health.py backend/tests/unit/test_ibd_classification_health.py
git commit -m "feat(ibd): assemble classification health report + asset I/O"
```

---

### Task 4: Health module — gate evaluation

**Files:**
- Modify: `backend/app/services/ibd_classification_health.py`
- Test: `backend/tests/unit/test_ibd_classification_health.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/test_ibd_classification_health.py`:

```python
from app.services.ibd_classification_health import GateResult, evaluate_gate

_OK = {"summary": {"coverage_pct": 96.0}, "diff": {"churn_pct": 3.0}}
_HIGH_CHURN = {"summary": {"coverage_pct": 96.0}, "diff": {"churn_pct": 40.0}}
_LOW_COVERAGE = {"summary": {"coverage_pct": 40.0}, "diff": None}


def test_gate_passes_within_thresholds():
    res = evaluate_gate(_OK, max_churn_pct=25, min_coverage_pct=50, mode="enforce")
    assert isinstance(res, GateResult)
    assert res.passed
    assert res.breaches == []


def test_gate_enforce_fails_on_high_churn():
    res = evaluate_gate(_HIGH_CHURN, max_churn_pct=25, min_coverage_pct=50, mode="enforce")
    assert not res.passed
    assert any("churn" in b for b in res.breaches)


def test_gate_enforce_fails_on_low_coverage():
    res = evaluate_gate(_LOW_COVERAGE, max_churn_pct=25, min_coverage_pct=50, mode="enforce")
    assert not res.passed
    assert any("coverage" in b for b in res.breaches)


def test_gate_warn_mode_reports_but_passes():
    res = evaluate_gate(_HIGH_CHURN, max_churn_pct=25, min_coverage_pct=50, mode="warn")
    assert res.passed                 # warn never blocks
    assert res.breaches               # but breaches are still surfaced


def test_gate_off_mode_always_passes_with_no_breaches():
    res = evaluate_gate(_HIGH_CHURN, max_churn_pct=25, min_coverage_pct=50, mode="off")
    assert res.passed
    assert res.breaches == []


def test_gate_null_diff_skips_churn_check():
    res = evaluate_gate(
        {"summary": {"coverage_pct": 96.0}, "diff": None},
        max_churn_pct=25, min_coverage_pct=50, mode="enforce",
    )
    assert res.passed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ibd_classification_health.py -v -k gate`
Expected: FAIL with `ImportError: cannot import name 'GateResult'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/services/ibd_classification_health.py`:

```python
@dataclass
class GateResult:
    passed: bool
    mode: str
    breaches: list[str]


def evaluate_gate(
    report: dict,
    *,
    max_churn_pct: float,
    min_coverage_pct: float,
    mode: str,
) -> GateResult:
    """Evaluate coverage + churn thresholds.

    mode="off"     -> never blocks, no breaches reported.
    mode="warn"    -> breaches reported, but passed is always True.
    mode="enforce" -> passed is False when any threshold is breached.
    """
    if mode == "off":
        return GateResult(passed=True, mode=mode, breaches=[])

    breaches: list[str] = []
    coverage = (report.get("summary") or {}).get("coverage_pct", 0.0)
    if coverage < min_coverage_pct:
        breaches.append(f"coverage {coverage}% < min {min_coverage_pct}%")

    diff = report.get("diff")
    if diff is not None:
        churn = diff.get("churn_pct", 0.0)
        if churn > max_churn_pct:
            breaches.append(f"churn {churn}% > max {max_churn_pct}%")

    passed = (not breaches) if mode == "enforce" else True
    return GateResult(passed=passed, mode=mode, breaches=breaches)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ibd_classification_health.py -v -k gate`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ibd_classification_health.py backend/tests/unit/test_ibd_classification_health.py
git commit -m "feat(ibd): add coverage/churn regression gate evaluation"
```

---

### Task 5: Gate CLI

**Files:**
- Create: `backend/app/scripts/check_ibd_classification_gate.py`
- Test: `backend/tests/unit/test_ibd_classification_health.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/test_ibd_classification_health.py`:

```python
import json

from app.scripts.check_ibd_classification_gate import main as gate_main


def _write_report(tmp_path, report):
    path = tmp_path / "ibd-classification-health-hk.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return str(path)


def test_gate_cli_enforce_returns_1_on_breach(tmp_path, capsys):
    report = {"market": "HK", "summary": {"coverage_pct": 40.0}, "diff": None}
    rc = gate_main([
        "--health", _write_report(tmp_path, report),
        "--max-churn-pct", "25", "--min-coverage-pct", "50", "--mode", "enforce",
    ])
    assert rc == 1
    assert "::error::" in capsys.readouterr().out


def test_gate_cli_warn_returns_0_but_warns(tmp_path, capsys):
    report = {"market": "HK", "summary": {"coverage_pct": 40.0}, "diff": None}
    rc = gate_main([
        "--health", _write_report(tmp_path, report),
        "--max-churn-pct", "25", "--min-coverage-pct", "50", "--mode", "warn",
    ])
    assert rc == 0
    assert "::warning::" in capsys.readouterr().out


def test_gate_cli_ok_returns_0(tmp_path, capsys):
    report = {"market": "HK", "summary": {"coverage_pct": 96.0}, "diff": {"churn_pct": 2.0}}
    rc = gate_main([
        "--health", _write_report(tmp_path, report),
        "--max-churn-pct", "25", "--min-coverage-pct", "50", "--mode", "enforce",
    ])
    assert rc == 0
    assert "gate: OK" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ibd_classification_health.py -v -k cli`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scripts.check_ibd_classification_gate'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/scripts/check_ibd_classification_gate.py`:

```python
"""Evaluate the IBD classification health gate (coverage + week-over-week churn).

Reads an ``ibd-classification-health-<market>.json`` report and applies the
configured thresholds. In ``enforce`` mode a breach exits non-zero so the calling
workflow fails *before* the new bundle is uploaded — the prior good ``-latest``
manifest stays referenced and the static-site build falls back to it. In ``warn``
mode breaches are surfaced as GitHub annotations but the step still succeeds, so
you can observe a few weeks of real churn before gating hard.

Dependency-free (no DB, no network) so it runs fast in CI.

Usage:
    python -m app.scripts.check_ibd_classification_gate \
      --health /tmp/ibd-classification/ibd-classification-health-hk.json \
      --max-churn-pct 25 --min-coverage-pct 50 --mode warn
"""
from __future__ import annotations

import argparse
from pathlib import Path

from app.services.ibd_classification_health import evaluate_gate, read_health_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health", required=True)
    parser.add_argument("--max-churn-pct", type=float, default=25.0)
    parser.add_argument("--min-coverage-pct", type=float, default=50.0)
    parser.add_argument("--mode", choices=("off", "warn", "enforce"), default="warn")
    args = parser.parse_args(argv)

    report = read_health_report(Path(args.health))
    result = evaluate_gate(
        report,
        max_churn_pct=args.max_churn_pct,
        min_coverage_pct=args.min_coverage_pct,
        mode=args.mode,
    )

    market = report.get("market", "?")
    summary = report.get("summary") or {}
    diff = report.get("diff") or {}
    print(
        f"IBD health gate [{market}] mode={result.mode} "
        f"coverage={summary.get('coverage_pct')}% churn={diff.get('churn_pct')}%"
    )

    if not result.breaches:
        print("  gate: OK")
        return 0

    annotation = "::error::" if result.mode == "enforce" else "::warning::"
    for breach in result.breaches:
        print(f"{annotation} IBD health gate [{market}]: {breach}")

    if result.passed:
        print("  gate: passed (non-enforcing mode)")
        return 0
    print("  gate: FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ibd_classification_health.py -v -k cli`
Expected: PASS

- [ ] **Step 5: Run the full new test file**

Run: `pytest tests/unit/test_ibd_classification_health.py -v`
Expected: PASS (all tasks 1–5 green)

- [ ] **Step 6: Commit**

```bash
git add backend/app/scripts/check_ibd_classification_gate.py backend/tests/unit/test_ibd_classification_health.py
git commit -m "feat(ibd): add classification health gate CLI"
```

---

### Task 6: Wire the health report into the build script

**Files:**
- Modify: `backend/app/scripts/build_ibd_classification_bundle.py`

This task has no new unit test — the report assembly is fully covered by Task 3, and the script change is thin CLI glue plus an embedding-model constant. Verification is a real local run in Step 5.

- [ ] **Step 1: Add the embedding-model constant and use it in `_build_engine`**

In `backend/app/scripts/build_ibd_classification_bundle.py`, add a module-level constant after the imports (after line 33, `from app.services.ibd_crosswalk import IBDCrosswalk`):

```python
# Single source of truth for the embedding model id, recorded in the health
# report's `embedding_model` fingerprint so a model swap is visible in the diff.
EMBEDDING_MODEL_ID = "all-MiniLM-L6-v2"
```

Then change `_build_engine` (currently line 53) to use it:

```python
        return ThemeEmbeddingEngine(EMBEDDING_MODEL_ID)
```

- [ ] **Step 2: Add the `--prev-bundle` argument**

In `main()`, after the `--as-of` argument (line 73), add:

```python
    parser.add_argument(
        "--prev-bundle",
        default=None,
        help="Path to the previous week's bundle (.json.gz) for the churn diff. "
        "When omitted, the health report's diff is null (e.g. first run).",
    )
```

- [ ] **Step 3: Import the health helpers and `read_bundle`**

Change the `ibd_classification_bundle` import block (lines 24–31) to also import `read_bundle`:

```python
from app.services.ibd_classification_bundle import (
    bundle_asset_name,
    build_manifest,
    build_payload,
    latest_manifest_name,
    read_bundle,
    write_bundle,
    write_manifest,
)
from app.services.ibd_classification_health import (
    build_health_report,
    health_asset_name,
    write_health_report,
)
```

- [ ] **Step 4: Write the health report after the manifest**

In `main()`, immediately after `write_manifest(manifest_path, manifest)` (line 122) and before the `print("IBD classification bundle complete:")` block, add:

```python
    prev_payload = read_bundle(Path(args.prev_bundle)) if args.prev_bundle else None
    health = build_health_report(
        payload=payload,
        prev_payload=prev_payload,
        embedding_model=EMBEDDING_MODEL_ID,
    )
    health_path = output_dir / health_asset_name(market)
    write_health_report(health_path, health)
```

Then add to the final print block (after the `sha256` line, line 129):

```python
    print(f"  - health:   {health_path}")
    if health.get("diff") is not None:
        print(f"  - churn:    {health['diff']['churn_pct']}%")
```

- [ ] **Step 5: Verify the script imports and wires correctly**

Run (no DB needed — this just confirms the module imports and the CLI parses):

```bash
python -c "import app.scripts.build_ibd_classification_bundle as m; print(m.EMBEDDING_MODEL_ID)"
python -m app.scripts.build_ibd_classification_bundle --help
```

Expected: prints `all-MiniLM-L6-v2`, then the help text showing `--prev-bundle`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/scripts/build_ibd_classification_bundle.py
git commit -m "feat(ibd): emit health report from classification bundle build"
```

---

### Task 7: Wire the workflow — prior bundle, health upload, gate

**Files:**
- Modify: `.github/workflows/ibd-classification.yml`

No unit test (YAML); verification is `actionlint` + a careful manual `gh workflow run` documented in Step 6.

- [ ] **Step 1: Add the `gate_mode` dispatch input**

In `.github/workflows/ibd-classification.yml`, under `on.workflow_dispatch.inputs` (after the `market` input block, which ends at line 35), add:

```yaml
      gate_mode:
        description: "Regression gate mode (off=no checks, warn=log only, enforce=block publish on breach)."
        required: false
        type: choice
        default: warn
        options:
          - warn
          - enforce
          - off
```

- [ ] **Step 2: Add the prior-bundle download step**

Insert this step **before** the existing `- name: Build IBD classification bundle` step (before line 163). It downloads the *current* `-latest` manifest, which still points at last week's bundle until this run uploads the new one:

```yaml
      - name: Download previous IBD bundle (for churn diff)
        id: prev
        if: ${{ steps.seed.outputs.seeded == 'true' }}
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          export MARKET_LOWER="$(echo "${{ matrix.market }}" | tr '[:upper:]' '[:lower:]')"
          mkdir -p /tmp/ibd-prev
          PREV_BUNDLE=""
          if gh release download ibd-classification-data \
            --pattern "ibd-classification-latest-${MARKET_LOWER}.json" \
            --dir /tmp/ibd-prev >/dev/null 2>&1; then
            PREV_ASSET="$(python - <<'PY'
          import json, os
          from pathlib import Path
          market = os.environ["MARKET_LOWER"]
          manifest = json.loads(Path(f"/tmp/ibd-prev/ibd-classification-latest-{market}.json").read_text(encoding="utf-8"))
          print(manifest.get("bundle_asset_name", ""))
          PY
            )"
            if [ -n "$PREV_ASSET" ] && gh release download ibd-classification-data \
              --pattern "$PREV_ASSET" --dir /tmp/ibd-prev >/dev/null 2>&1; then
              PREV_BUNDLE="/tmp/ibd-prev/${PREV_ASSET}"
            fi
          fi
          echo "prev_bundle=${PREV_BUNDLE}" >> "$GITHUB_OUTPUT"
          echo "Previous bundle: ${PREV_BUNDLE:-<none>}"
```

- [ ] **Step 3: Pass `--prev-bundle` to the build step**

Replace the existing `- name: Build IBD classification bundle` step body (lines 163–169) with:

```yaml
      - name: Build IBD classification bundle
        if: ${{ steps.seed.outputs.seeded == 'true' }}
        run: |
          cd backend
          PREV_ARG=""
          if [ -n "${{ steps.prev.outputs.prev_bundle }}" ]; then
            PREV_ARG="--prev-bundle ${{ steps.prev.outputs.prev_bundle }}"
          fi
          python -m app.scripts.build_ibd_classification_bundle \
            --market "${{ matrix.market }}" \
            --output-dir /tmp/ibd-classification \
            $PREV_ARG
```

- [ ] **Step 4: Upload the health report (always), then run the gate — both before the bundle upload**

Insert these two steps **between** the build step and the existing `- name: Upload IBD classification assets` step (before line 171):

```yaml
      - name: Upload IBD health report
        if: ${{ steps.seed.outputs.seeded == 'true' }}
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          MARKET_LOWER="$(echo "${{ matrix.market }}" | tr '[:upper:]' '[:lower:]')"
          HEALTH_PATH="/tmp/ibd-classification/ibd-classification-health-${MARKET_LOWER}.json"
          if [ ! -f "$HEALTH_PATH" ]; then
            echo "Missing IBD health report at $HEALTH_PATH" >&2
            exit 1
          fi
          gh release upload ibd-classification-data "$HEALTH_PATH" --clobber

      - name: Evaluate classification health gate
        if: ${{ steps.seed.outputs.seeded == 'true' }}
        run: |
          cd backend
          MARKET_LOWER="$(echo "${{ matrix.market }}" | tr '[:upper:]' '[:lower:]')"
          python -m app.scripts.check_ibd_classification_gate \
            --health "/tmp/ibd-classification/ibd-classification-health-${MARKET_LOWER}.json" \
            --max-churn-pct "${{ vars.IBD_GATE_MAX_CHURN_PCT || '25' }}" \
            --min-coverage-pct "${{ vars.IBD_GATE_MIN_COVERAGE_PCT || '50' }}" \
            --mode "${{ github.event.inputs.gate_mode || vars.IBD_GATE_MODE || 'warn' }}"
```

Note: the health report is uploaded *before* the gate runs, so it is always available for diagnosis even when the gate fails. A failed gate (enforce mode) fails the job here; GitHub then skips the subsequent `Upload IBD classification assets` step, so the new bundle/manifest is never published and last week's `-latest` stays referenced. No change is needed to the existing upload step — it already guards on `steps.seed.outputs.seeded == 'true'` and is skipped automatically on prior-step failure.

- [ ] **Step 5: Lint the workflow**

Run (install actionlint if absent — `brew install actionlint`):

```bash
actionlint .github/workflows/ibd-classification.yml
```

Expected: no errors. (If `actionlint` is unavailable, instead run `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ibd-classification.yml')); print('yaml ok')"` to at least confirm valid YAML.)

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ibd-classification.yml
git commit -m "ci(ibd): publish health report + regression gate in weekly classification"
```

- [ ] **Step 7: Document the manual verification path (do not run automatically)**

After merge to the default branch, verify end-to-end with a single dispatch run (warn mode is the default, so it cannot block):

```bash
gh workflow run "IBD Classification" -f market=SG -f gate_mode=warn
```

Then confirm the new asset exists and inspect it:

```bash
gh release download ibd-classification-data --pattern "ibd-classification-health-sg.json" --dir /tmp/verify --clobber
cat /tmp/verify/ibd-classification-health-sg.json
```

Expected: a JSON report with `summary.coverage_pct`, `confidence_histogram`, and `diff` (null on the very first run for SG, populated thereafter).

---

## Self-Review

**1. Spec coverage** — checked each element of the spec against a task:

| Spec element | Task |
|---|---|
| Emit `ibd-classification-health-{market}` asset every run | Task 3 (naming/I/O) + Task 6 (write) + Task 7 Step 4 (upload) |
| Coverage % | Reuses `ClassificationResult.summary()["coverage_pct"]` → carried in `report["summary"]` (Task 3) |
| Tier mix (crosswalk/embedding/LLM/unresolved) | Already in `summary()["by_source"]` + `unresolved` → carried in `report["summary"]` (Task 3) |
| Confidence histogram | Task 1 |
| Embedding model hash/fingerprint | Task 6 constant → `report["embedding_model"]` (Task 3). *Note:* this is the model **identifier** string, sufficient to detect a model **swap**; detecting weight changes under the same name is out of scope (follow-up). |
| Diff vs last week's bundle (changed symbols, churn %) | Task 2 + Task 7 Steps 2–3 (download prior + pass `--prev-bundle`) |
| Gate fails build / downgrades when churn or coverage breaches | Task 4 (eval) + Task 5 (CLI exit code) + Task 7 Step 4 (gate before upload → prior `-latest` stays referenced) |
| Generous initial ceiling, observe before gating hard | Default `mode=warn` (Task 4/5/7) — never blocks until a maintainer sets `vars.IBD_GATE_MODE=enforce` |
| Manual-dispatch override for legit 100% churn (e.g. foreign seeding) | `gate_mode` dispatch input (Task 7 Step 1) — dispatch with `warn`/`off` |
| Pure-additive, cannot make anything worse | Health upload is independent; gate defaults to warn; bundle upload step unchanged |

**2. Placeholder scan** — no `TBD`/`TODO`/"add error handling"/"similar to Task N". Every code step contains complete code; every command has expected output.

**3. Type consistency** — verified names match across tasks: `confidence_histogram`, `diff_classifications` (returns `churn_pct`, `changed_group`, `changed_examples`, `compared`, `added`, `removed`), `build_health_report` (kwargs `payload`/`prev_payload`/`embedding_model`), `health_asset_name`, `write_health_report`/`read_health_report`, `GateResult(passed, mode, breaches)`, `evaluate_gate(report, *, max_churn_pct, min_coverage_pct, mode)`, `EMBEDDING_MODEL_ID`. The CLI (`check_ibd_classification_gate.main(argv)`) imports exactly the symbols Task 3/4 define. The build script imports `read_bundle` (confirmed exported by `ibd_classification_bundle.py:46`).

**4. Cleanup-workflow safety** — confirmed `ibd-classification-health-{market}.json` matches none of `release-asset-cleanup.yml`'s dated patterns and contains no date, so `asset_market_date()` returns `None` → preserved; `--clobber` prevents accumulation. No change required.

**5. Out of scope (intentional, for follow-up beads):** surfacing coverage/churn on the frontend "data-health" page; true embedding-weight hashing; applying the gate at static-site consume time (this plan gates at build time, which is strictly stronger).

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-02-ibd-classification-health-scorecard.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
