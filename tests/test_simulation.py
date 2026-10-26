from pathlib import Path

import pytest

from jarvis_bot.simulation import scenarios_from_json, simulate_file


def test_simulate_file_scenarios(tmp_path: Path) -> None:
    csv_path = tmp_path / "vendite.csv"
    csv_path.write_text("mese,valore\ngen,100\nfeb,200\n", encoding="utf-8")

    result = simulate_file(
        csv_path,
        "valore",
        [{"name": "-10%", "change_pct": -10}, {"name": "+10%", "change_pct": 10}],
    )

    assert result.baseline == 300
    assert result.scenarios[0]["total"] == 270
    assert result.scenarios[1]["total"] == 330
    assert result.spec is not None
    assert result.spec.chart_type == "bar"
    assert len(result.spec.labels) == 3


def test_scenarios_from_json() -> None:
    assert scenarios_from_json("") is None
    assert scenarios_from_json('[{"name": "x", "change_pct": 5}]')[0]["name"] == "x"

    with pytest.raises(ValueError):
        scenarios_from_json('{"name": "non lista"}')
