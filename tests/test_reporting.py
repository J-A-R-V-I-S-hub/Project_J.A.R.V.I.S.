from pathlib import Path

import pytest

from jarvis_bot.reporting import build_pdf_report, create_histogram_png, render_chart
from jarvis_bot.schemas import ChartSeries, ChartSpec


def test_create_histogram_png(tmp_path: Path) -> None:
    output = tmp_path / "chart.png"
    created = create_histogram_png(output, "Test Chart", [("A", 1), ("B", 2)])
    assert created.exists()
    assert created.stat().st_size > 0


def test_build_pdf_report(tmp_path: Path) -> None:
    output = tmp_path / "report.pdf"
    created = build_pdf_report(
        output_path=output,
        title="Jarvis Report",
        summary="Sintesi del report.\n\nSecondo paragrafo.",
        histogram_title="Distribuzione",
        histogram_data=[("A", 2), ("B", 4)],
        infographic_descriptions=["Spiega i valori della tabella in modo semplice."],
    )
    assert created.exists()
    assert created.stat().st_size > 0


def test_render_grouped_bar(tmp_path: Path) -> None:
    spec = ChartSpec(
        title="Difetti per prodotto",
        labels=["A4636", "A2524"],
        series=[
            ChartSeries(label="A", values=[37, 20]),
            ChartSeries(label="B", values=[21, 24]),
        ],
        chart_type="grouped_bar",
    )
    created = render_chart(tmp_path / "grouped.png", spec)
    assert created.exists()
    assert created.stat().st_size > 0


def test_render_pareto(tmp_path: Path) -> None:
    spec = ChartSpec(
        title="Pareto difetti",
        labels=["A", "B", "C"],
        series=[ChartSeries(label="Difetti", values=[10, 30, 20])],
        chart_type="pareto",
    )
    created = render_chart(tmp_path / "pareto.png", spec)
    assert created.exists()
    assert created.stat().st_size > 0


def test_chart_spec_length_mismatch(tmp_path: Path) -> None:
    spec = ChartSpec(
        title="Rotto",
        labels=["A", "B"],
        series=[ChartSeries(label="X", values=[1])],
    )
    with pytest.raises(ValueError):
        render_chart(tmp_path / "broken.png", spec)


def test_pdf_report_escapes_markup(tmp_path: Path) -> None:
    created = build_pdf_report(
        output_path=tmp_path / "escaped.pdf",
        title="Report <test>",
        summary="Valori: 1 < 2 & 3 > 2.\n\n- punto uno\n- punto due",
    )
    assert created.exists()
    assert created.stat().st_size > 0
