from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image as ReportImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .schemas import ChartSeries, ChartSpec


def slugify_filename(value: str, default_stem: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-._")
    return cleaned or default_stem


def normalise_histogram_data(raw_data: str | Iterable[tuple[str, float]] | None) -> list[tuple[str, float]]:
    if raw_data is None:
        return []

    if isinstance(raw_data, str):
        raw_data = raw_data.strip()
        if not raw_data:
            return []
        decoded = json.loads(raw_data)
    else:
        decoded = list(raw_data)

    normalised: list[tuple[str, float]] = []
    for item in decoded:
        if isinstance(item, dict):
            label = str(item.get("label", "item"))
            value = float(item.get("value", 0))
        else:
            label, value = item
            label = str(label)
            value = float(value)
        normalised.append((label, value))
    return normalised


def _validate_chart_spec(spec: ChartSpec) -> None:
    if not spec.labels:
        raise ValueError("ChartSpec.labels non può essere vuoto.")
    if not spec.series:
        raise ValueError("ChartSpec.series deve contenere almeno una serie.")
    for series in spec.series:
        if len(series.values) != len(spec.labels):
            raise ValueError(
                f"La serie '{series.label}' ha {len(series.values)} valori ma ci sono "
                f"{len(spec.labels)} etichette: devono coincidere."
            )


def render_chart(output_path: str | Path, spec: ChartSpec) -> Path:
    """Render a typed ChartSpec to a PNG file."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _validate_chart_spec(spec)

    figure, axis = plt.subplots(figsize=(10, 5.5))

    if spec.chart_type == "pie":
        axis.pie(
            spec.series[0].values,
            labels=spec.labels,
            autopct="%1.1f%%",
            startangle=90,
        )
    elif spec.chart_type == "pareto":
        pairs = sorted(zip(spec.labels, spec.series[0].values), key=lambda item: item[1], reverse=True)
        labels = [label for label, _ in pairs]
        values = [value for _, value in pairs]
        total = sum(values) or 1.0
        cumulative: list[float] = []
        running = 0.0
        for value in values:
            running += value
            cumulative.append(running / total * 100)

        axis.bar(labels, values, color="#2563eb")
        axis.set_ylabel(spec.y_label)
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)

        cumulative_axis = axis.twinx()
        cumulative_axis.plot(labels, cumulative, color="#dc2626", marker="o")
        cumulative_axis.set_ylabel("Cumulata %")
        cumulative_axis.set_ylim(0, 105)
        plt.setp(axis.get_xticklabels(), rotation=25, ha="right")
    elif spec.chart_type == "line":
        for series in spec.series:
            axis.plot(spec.labels, series.values, marker="o", label=series.label)
        axis.set_ylabel(spec.y_label)
        axis.legend()
        axis.grid(alpha=0.2)
        axis.set_axisbelow(True)
    elif len(spec.series) > 1:
        positions = list(range(len(spec.labels)))
        width = 0.8 / len(spec.series)
        for index, series in enumerate(spec.series):
            offsets = [position - 0.4 + width / 2 + index * width for position in positions]
            axis.bar(offsets, series.values, width, label=series.label)
        axis.set_xticks(positions)
        axis.set_xticklabels(spec.labels)
        axis.set_ylabel(spec.y_label)
        axis.legend()
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)
        plt.setp(axis.get_xticklabels(), rotation=25, ha="right")
    else:
        axis.bar(spec.labels, spec.series[0].values, color="#2563eb")
        axis.set_ylabel(spec.y_label)
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)
        plt.setp(axis.get_xticklabels(), rotation=25, ha="right")

    axis.set_title(spec.title)
    if spec.x_label:
        axis.set_xlabel(spec.x_label)
    figure.tight_layout()
    figure.savefig(output, dpi=150)
    plt.close(figure)
    return output


def create_histogram_png(output_path: str | Path, title: str, chart_data: str | Iterable[tuple[str, float]]) -> Path:
    bars = normalise_histogram_data(chart_data)
    if not bars:
        raise ValueError("Histogram data is empty")
    spec = ChartSpec(
        title=title,
        labels=[label for label, _ in bars],
        series=[ChartSeries(label="Valore", values=[value for _, value in bars])],
        chart_type="bar",
    )
    return render_chart(output_path, spec)


def write_csv_file(output_path: str | Path, rows_json: str) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = json.loads(rows_json)
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows_json must describe a non-empty list")

    fieldnames = sorted({key for row in rows if isinstance(row, dict) for key in row.keys()})
    if not fieldnames:
        raise ValueError("rows_json must contain dictionaries with keys")

    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return output


def build_pdf_report(
    output_path: str | Path,
    title: str,
    summary: str,
    histogram_title: str | None = None,
    histogram_data: str | Iterable[tuple[str, float]] | None = None,
    infographic_descriptions: Iterable[str] | None = None,
    chart_spec: ChartSpec | None = None,
    chart_specs: Iterable[ChartSpec] | None = None,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(title), styles["Title"]), Spacer(1, 6 * mm)]

    for paragraph in summary.split("\n\n"):
        cleaned = escape(paragraph.strip()).replace("\n", "<br/>")
        if cleaned:
            story.append(Paragraph(cleaned, styles["BodyText"]))
            story.append(Spacer(1, 4 * mm))

    specs: list[ChartSpec] = list(chart_specs or [])
    if chart_spec is not None:
        specs.insert(0, chart_spec)

    if not specs and histogram_data:
        bars = normalise_histogram_data(histogram_data)
        if bars:
            specs.append(
                ChartSpec(
                    title=histogram_title or "Istogramma",
                    labels=[label for label, _ in bars],
                    series=[ChartSeries(label="Valore", values=[value for _, value in bars])],
                    chart_type="bar",
                )
            )

    for index, spec in enumerate(specs):
        chart_path = render_chart(output.with_name(f"{output.stem}-chart{index + 1}.png"), spec)
        story.append(Paragraph(escape(spec.title), styles["Heading2"]))
        story.append(Spacer(1, 3 * mm))
        story.append(ReportImage(str(chart_path), width=165 * mm, height=92 * mm))
        story.append(Spacer(1, 4 * mm))

    descriptions = [item.strip() for item in infographic_descriptions or [] if item.strip()]
    if descriptions:
        story.append(Paragraph("Descrizione delle infografiche", styles["Heading2"]))
        story.append(Spacer(1, 3 * mm))
        for description in descriptions:
            story.append(Paragraph(f"• {escape(description)}", styles["BodyText"]))
            story.append(Spacer(1, 2 * mm))

    document = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    document.build(story)
    return output
