from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .attachments import load_table
from .reporting import build_pdf_report, render_chart, slugify_filename
from .schemas import ChartSeries, ChartSpec

TOTAL_HINTS = ("total", "totale", "somma", "sum")
TABLE_SUFFIXES = {".csv", ".xlsx", ".xls"}


@dataclass(slots=True)
class QualityReport:
    source: str
    products: list[str]
    categories: list[str]
    matrix: list[list[float]]
    product_totals: list[tuple[str, float]]
    category_totals: list[tuple[str, float]]
    grand_total: float
    grouped_spec: ChartSpec
    pareto_spec: ChartSpec
    category_spec: ChartSpec
    summary: str


def _pick_product_column(frame: pd.DataFrame, requested: str | None) -> str:
    if requested:
        if requested not in frame.columns:
            raise ValueError(f"Colonna prodotto '{requested}' non trovata. Colonne: {list(frame.columns)}")
        return requested
    non_numeric = [column for column in frame.columns if not pd.api.types.is_numeric_dtype(frame[column])]
    return str(non_numeric[0]) if non_numeric else str(frame.columns[0])


def _pick_category_columns(frame: pd.DataFrame, product_column: str, requested: str | None) -> list[str]:
    numeric = [
        str(column)
        for column in frame.columns
        if str(column) != product_column and pd.api.types.is_numeric_dtype(frame[column])
    ]
    if requested:
        wanted = [item.strip() for item in requested.split(",") if item.strip()]
        missing = [item for item in wanted if item not in numeric]
        if missing:
            raise ValueError(f"Colonne categoria non numeriche o mancanti: {missing}. Disponibili: {numeric}")
        return wanted
    without_totals = [column for column in numeric if not any(hint in column.lower() for hint in TOTAL_HINTS)]
    return without_totals or numeric


def analyse_defects(
    frame: pd.DataFrame,
    source: str = "tabella",
    product_column: str | None = None,
    category_columns: str | None = None,
) -> QualityReport:
    if frame.empty:
        raise ValueError("La tabella è vuota.")

    product_col = _pick_product_column(frame, product_column)
    categories = _pick_category_columns(frame, product_col, category_columns)
    if not categories:
        raise ValueError("Nessuna colonna numerica da analizzare.")

    work = frame[[product_col, *categories]].copy()
    work[product_col] = work[product_col].fillna("(senza nome)").astype(str)
    for column in categories:
        work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0.0)

    grouped = work.groupby(product_col, sort=False, as_index=False)[categories].sum()
    products = [str(value) for value in grouped[product_col].tolist()]
    matrix = [[float(value) for value in row] for row in grouped[categories].to_numpy().tolist()]

    product_totals = sorted(
        ((product, float(sum(row))) for product, row in zip(products, matrix)),
        key=lambda item: item[1],
        reverse=True,
    )
    category_totals = sorted(
        ((category, float(grouped[category].sum())) for category in categories),
        key=lambda item: item[1],
        reverse=True,
    )
    grand_total = float(sum(value for _, value in product_totals))

    grouped_spec = ChartSpec(
        title=f"Difetti per prodotto e categoria — {source}",
        labels=products,
        series=[
            ChartSeries(label=category, values=[row[index] for row in matrix])
            for index, category in enumerate(categories)
        ],
        chart_type="grouped_bar",
        x_label="Prodotto",
        y_label="Difetti",
    )
    pareto_spec = ChartSpec(
        title="Pareto — difetti per prodotto",
        labels=[product for product, _ in product_totals],
        series=[ChartSeries(label="Difetti", values=[value for _, value in product_totals])],
        chart_type="pareto",
        x_label="Prodotto",
        y_label="Difetti",
    )
    category_spec = ChartSpec(
        title="Pareto — difetti per categoria",
        labels=[category for category, _ in category_totals],
        series=[ChartSeries(label="Difetti", values=[value for _, value in category_totals])],
        chart_type="pareto",
        x_label="Categoria",
        y_label="Difetti",
    )

    lines = [f"Totale difetti: {grand_total:g}", "", "Categorie:"]
    for category, total in category_totals:
        share = (total / grand_total * 100) if grand_total else 0.0
        lines.append(f"• {category}: {total:g} ({share:.1f}%)")

    lines.append("")
    lines.append("Prodotti peggiori:")
    for product, total in product_totals[:5]:
        share = (total / grand_total * 100) if grand_total else 0.0
        lines.append(f"• {product}: {total:g} ({share:.1f}%)")

    if grand_total:
        running = 0.0
        covering = 0
        for _, total in product_totals:
            running += total
            covering += 1
            if running / grand_total >= 0.8:
                break
        lines.append("")
        lines.append(f"Il {covering} prodotto/i principali coprono l'80% dei difetti ({covering}/{len(products)}).")

    return QualityReport(
        source=source,
        products=products,
        categories=categories,
        matrix=matrix,
        product_totals=product_totals,
        category_totals=category_totals,
        grand_total=grand_total,
        grouped_spec=grouped_spec,
        pareto_spec=pareto_spec,
        category_spec=category_spec,
        summary="\n".join(lines),
    )


def analyse_file(
    path: str | Path,
    product_column: str | None = None,
    category_columns: str | None = None,
) -> QualityReport:
    file_path = Path(path)
    if file_path.suffix.lower() not in TABLE_SUFFIXES:
        raise ValueError(f"Formato non supportato: {file_path.suffix}. Usa CSV o Excel.")
    frame = load_table(file_path)
    return analyse_defects(frame, source=file_path.name, product_column=product_column, category_columns=category_columns)


def build_quality_artifacts(
    path: str | Path,
    output_dir: str | Path,
    reports_dir: str | Path,
    title: str | None = None,
    product_column: str | None = None,
    category_columns: str | None = None,
) -> tuple[QualityReport, list[Path]]:
    file_path = Path(path)
    output = Path(output_dir)
    reports = Path(reports_dir)
    output.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)

    report = analyse_file(file_path, product_column=product_column, category_columns=category_columns)
    stem = slugify_filename(file_path.stem, "quality")

    grouped_png = render_chart(output / f"{stem}-gruppi.png", report.grouped_spec)
    pareto_png = render_chart(output / f"{stem}-pareto.png", report.pareto_spec)
    category_png = render_chart(output / f"{stem}-categorie.png", report.category_spec)

    pdf_path = reports / f"{stem}-report.pdf"
    build_pdf_report(
        pdf_path,
        title=title or f"Report qualità — {file_path.stem}",
        summary=report.summary,
        chart_specs=[report.grouped_spec, report.pareto_spec, report.category_spec],
        infographic_descriptions=[
            "Il primo grafico mostra i difetti per prodotto, suddivisi per categoria.",
            "Il secondo è un diagramma di Pareto: le barre sono ordinate per difetti e la linea mostra la cumulata.",
            "Il terzo confronta le categorie di difetto ordinate per frequenza.",
        ],
    )
    return report, [grouped_png, pareto_png, category_png, pdf_path]


def _connect(db_path: str | Path):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS quality_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            grand_total REAL NOT NULL,
            products INTEGER NOT NULL,
            categories INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS quality_products (
            snapshot_id INTEGER NOT NULL,
            product TEXT NOT NULL,
            total REAL NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS quality_files (
            path TEXT PRIMARY KEY,
            processed_at TEXT NOT NULL
        )
        """
    )
    return connection


def record_snapshot(db_path: str | Path, report: QualityReport) -> int:
    connection = _connect(db_path)
    try:
        cursor = connection.execute(
            "INSERT INTO quality_snapshots (source, grand_total, products, categories, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                report.source,
                report.grand_total,
                len(report.products),
                len(report.categories),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        snapshot_id = int(cursor.lastrowid)
        connection.executemany(
            "INSERT INTO quality_products (snapshot_id, product, total) VALUES (?, ?, ?)",
            [(snapshot_id, product, total) for product, total in report.product_totals],
        )
        connection.commit()
        return snapshot_id
    finally:
        connection.close()


def trend_spec(db_path: str | Path, limit: int = 24) -> ChartSpec | None:
    connection = _connect(db_path)
    try:
        rows = connection.execute(
            "SELECT source, grand_total, created_at FROM quality_snapshots ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        connection.close()
    rows.reverse()
    if len(rows) < 2:
        return None
    labels = [datetime.fromisoformat(row[2]).strftime("%d/%m %H:%M") for row in rows]
    values = [float(row[1]) for row in rows]
    return ChartSpec(
        title="Trend difetti totali",
        labels=labels,
        series=[ChartSeries(label="Difetti totali", values=values)],
        chart_type="line",
        x_label="Analisi",
        y_label="Difetti",
    )


def pending_quality_files(watch_dir: str | Path, db_path: str | Path) -> list[Path]:
    directory = Path(watch_dir)
    if not directory.exists():
        return []
    connection = _connect(db_path)
    try:
        processed = {row[0] for row in connection.execute("SELECT path FROM quality_files")}
    finally:
        connection.close()
    pending: list[Path] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() not in TABLE_SUFFIXES or path.name.startswith("~$"):
            continue
        if str(path.resolve()) not in processed:
            pending.append(path)
    return pending


def mark_quality_file(db_path: str | Path, path: str | Path) -> None:
    connection = _connect(db_path)
    try:
        connection.execute(
            "INSERT OR REPLACE INTO quality_files (path, processed_at) VALUES (?, ?)",
            (str(Path(path).resolve()), datetime.now(timezone.utc).isoformat()),
        )
        connection.commit()
    finally:
        connection.close()
