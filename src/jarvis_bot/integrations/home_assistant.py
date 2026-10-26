from __future__ import annotations

from typing import Any

import httpx


class HomeAssistantClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    @classmethod
    def from_settings(cls, settings) -> HomeAssistantClient | None:
        if settings.home_assistant_url and settings.home_assistant_token:
            return cls(settings.home_assistant_url, settings.home_assistant_token)
        return None

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str) -> Any:
        response = httpx.get(f"{self.base_url}{path}", headers=self._headers, timeout=15)
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, payload: dict) -> Any:
        response = httpx.post(f"{self.base_url}{path}", headers=self._headers, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _label(state: dict) -> str:
        attributes = state.get("attributes") or {}
        name = attributes.get("friendly_name") or state.get("entity_id", "?")
        unit = attributes.get("unit_of_measurement", "")
        value = state.get("state", "?")
        return f"{name}: {value}{(' ' + unit) if unit else ''}"

    def get_state(self, entity_id: str) -> str:
        try:
            state = self._get(f"/api/states/{entity_id}")
        except Exception as exc:
            return f"Home Assistant non raggiungibile: {exc}"
        return "🏠 " + self._label(state)

    def list_entities(self, domain: str = "") -> str:
        try:
            states = self._get("/api/states")
        except Exception as exc:
            return f"Home Assistant non raggiungibile: {exc}"
        if domain:
            prefix = domain if "." not in domain else domain
            states = [state for state in states if state.get("entity_id", "").startswith(prefix + ".")]
        if not states:
            return "Nessuna entità trovata."
        lines = [f"🏠 **Home Assistant** ({len(states)} entità)"]
        for state in states[:40]:
            lines.append("• " + self._label(state))
        if len(states) > 40:
            lines.append(f"… e altre {len(states) - 40}.")
        return "\n".join(lines)

    def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str = "",
        data: dict | None = None,
    ) -> str:
        payload: dict[str, Any] = dict(data or {})
        if entity_id:
            payload["entity_id"] = entity_id
        try:
            self._post(f"/api/services/{domain}/{service}", payload)
        except Exception as exc:
            return f"Comando Home Assistant non riuscito: {exc}"
        target = f" su {entity_id}" if entity_id else ""
        return f"Home Assistant: eseguito {domain}.{service}{target}."

    def turn_on(self, entity_id: str) -> str:
        domain = entity_id.split(".", 1)[0]
        return self.call_service(domain, "turn_on", entity_id)

    def turn_off(self, entity_id: str) -> str:
        domain = entity_id.split(".", 1)[0]
        return self.call_service(domain, "turn_off", entity_id)

    def toggle(self, entity_id: str) -> str:
        domain = entity_id.split(".", 1)[0]
        return self.call_service(domain, "toggle", entity_id)

    def set_temperature(self, entity_id: str, temperature: float) -> str:
        return self.call_service(
            "climate",
            "set_temperature",
            entity_id,
            {"temperature": float(temperature)},
        )

    def run_scene(self, entity_id: str) -> str:
        return self.call_service("scene", "turn_on", entity_id)

    def summary(self) -> str:
        try:
            states = self._get("/api/states")
        except Exception as exc:
            return f"Home Assistant non raggiungibile: {exc}"
        counts: dict[str, int] = {}
        for state in states:
            domain = state.get("entity_id", "").split(".", 1)[0]
            counts[domain] = counts.get(domain, 0) + 1
        lines = ["🏠 **Home Assistant — riepilogo**"]
        for domain, count in sorted(counts.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"• {domain}: {count}")
        return "\n".join(lines)
