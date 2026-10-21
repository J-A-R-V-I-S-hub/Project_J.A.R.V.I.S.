from pathlib import Path

import pandas as pd

from jarvis_bot.quality import (
    analyse_defects,
    build_quality_artifacts,
    mark_quality_file,
    pending_quality_files,
    record_snapshot,
    trend_spec,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Prodotto": ["A4636", "A2524", "A3713"],
            "Totale": [10, 20, 5],
            "A": [4, 10, 1],
            "B": [6, 10, 4],
        }
    )


def test_analyse_defects_detects_products_and_categories() -> None:
    report = analyse_defects(_frame(), source="difetti.csv")

    assert report.products == ["A4636", "A2524", "A3713"]
    assert set(report.categories) == {"A", "B"}
    assert report.grand_total == 35
    assert report.product_totals[0][0] == "A2524"
    assert report.grouped_spec.chart_type == "grouped_bar"
    assert "Totale difetti: 35" in report.summary


def test_build_quality_artifacts(tmp_path: Path) -> None:
    csv_path = tmp_path / "difetti.csv"
    _frame().to_csv(csv_path, index=False)

    report, artifacts = build_quality_artifacts(csv_path, tmp_path / "output", tmp_path / "reports")

    assert report.grand_total == 35
    assert len(artifacts) == 4
    assert all(path.exists() and path.stat().st_size > 0 for path in artifacts)
    assert any(path.suffix == ".pdf" for path in artifacts)


def test_trend_requires_two_snapshots(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    assert trend_spec(db_path) is None

    for total in (10, 20):
        report = analyse_defects(pd.DataFrame({"P": ["A"], "C": [total]}), source="test")
        record_snapshot(db_path, report)

    spec = trend_spec(db_path)
    assert spec is not None
    assert spec.chart_type == "line"
    assert len(spec.labels) == 2


def test_pending_quality_files_are_tracked(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    table = watch_dir / "difetti.csv"
    table.write_text("P,C\nA,1\n", encoding="utf-8")

    assert pending_quality_files(watch_dir, db_path) == [table]

    mark_quality_file(db_path, table)
    assert pending_quality_files(watch_dir, db_path) == []
