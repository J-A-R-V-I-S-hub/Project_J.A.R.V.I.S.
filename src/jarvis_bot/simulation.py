from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .attachments import load_table
from .schemas import ChartSeries, ChartSpec

TOTAL_HINTS = ("total", "totale", "somma", "sum")


@dataclass(slots=True)
class SimulationResult:
    source: str
    column: str
    baseline: float
    scenarios: list[dict] = field(default_factory=list)
    spec: ChartSpec | None = None
    summary: str = ""


def _pick_column(frame: pd.DataFrame, requested: str | None) -> str:
    if requested:
        if requested not in frame.columns:
            raise ValueError(f"Colonna '{requested}' non trovata. Colonne: {list(frame.columns)}")
        return requested
    numeric = [str(column) for column in frame.columns if pd.api.types.is_numeric_dtype(frame[column])]
    if not numeric:
        raise ValueError("Nessuna colonna numerica da simulare.")
    non_total = [column for column in numeric if not any(hint in column.lower() for hint in TOTAL_HINTS)]
    return (non_total or numeric)[0]


def simulate_file(
    path: str | Path,
    value_column: str | None = None,
    scenarios: list[dict] | None = None,
) -> SimulationResult:
    file_path = Path(path)
    frame = load_table(file_path)
    column = _pick_column(frame, value_column)
    series = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    baseline = float(series.sum())

    scenario_list = scenarios or [
        {"name": "Pessimistico -10%", "change_pct": -10},
        {"name": "Base", "change_pct": 0},
        {"name": "Ottimistico +10%", "change_pct": 10},
    ]

    results: list[dict] = []
    for scenario in scenario_list:
        change = float(scenario.get("change_pct", 0))
        factor = 1 + change / 100
        if "multiplier" in scenario:
            factor = float(scenario["multiplier"])
        total = baseline * factor
        results.append(
            {
                "name": str(scenario.get("name", f"{change:+.0f}%")),
                "change_pct": change,
                "total": total,
                "delta": total - baseline,
                "delta_pct": ((total - baseline) / baseline * 100) if baseline else 0.0,
            }
        )

    labels = ["Attuale"] + [item["name"] for item in results]
    values = [baseline] + [item["total"] for item in results]
    spec = ChartSpec(
        title=f"Simulazione — {file_path.name}",
        labels=labels,
        series=[ChartSeries(label=column, values=values)],
        chart_type="bar",
        y_label=column,
        x_label="Scenario",
    )

    lines = [
        f"Simulazione su '{column}' di {file_path.name}.",
        f"Valore attuale: {baseline:.2f}.",
        "",
        "Scenari:",
    ]
    for item in results:
        lines.append(
            f"• {item['name']}: {item['total']:.2f} "
            f"({item['delta']:+.2f}, {item['delta_pct']:+.1f}%)"
        )
    return SimulationResult(
        source=file_path.name,
        column=column,
        baseline=baseline,
        scenarios=results,
        spec=spec,
        summary="\n".join(lines),
    )


def scenarios_from_json(raw: str) -> list[dict] | None:
    if not raw.strip():
        return None
    decoded = json.loads(raw)
    if not isinstance(decoded, list) or not decoded:
        raise ValueError("scenarios_json deve essere una lista non vuota.")
    return decoded
