from __future__ import annotations

import httpx

NOTION_VERSION = "2022-06-28"


def _plain_text(rich_text: list[dict] | None) -> str:
    return "".join(part.get("plain_text", "") for part in rich_text or [])


class NotionClient:
    def __init__(self, token: str, database_id: str | None = None) -> None:
        self.token = token
        self.database_id = database_id
        self.base_url = "https://api.notion.com/v1"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _title_of(self, item: dict) -> str:
        if item.get("object") == "database":
            return _plain_text(item.get("title")) or "(database senza titolo)"
        for prop in (item.get("properties") or {}).values():
            if prop.get("type") == "title":
                return _plain_text(prop.get("title")) or "(senza titolo)"
        return "(senza titolo)"

    def search(self, query: str = "", limit: int = 5) -> str:
        response = httpx.post(
            f"{self.base_url}/search",
            headers=self._headers,
            json={"query": query, "page_size": limit},
            timeout=20,
        )
        if response.status_code >= 400:
            return f"Notion non raggiungibile: {response.status_code} {response.text[:200]}"
        results = response.json().get("results") or []
        if not results:
            return "Nessun risultato su Notion."
        lines = ["📝 **Notion**"]
        for item in results[:limit]:
            kind = "database" if item.get("object") == "database" else "pagina"
            lines.append(f"• [{kind}] {self._title_of(item)}")
        return "\n".join(lines)

    def _database_title_property(self) -> str:
        if not self.database_id:
            raise ValueError("NOTION_DATABASE_ID non configurato.")
        response = httpx.get(
            f"{self.base_url}/databases/{self.database_id}",
            headers=self._headers,
            timeout=20,
        )
        response.raise_for_status()
        properties = response.json().get("properties") or {}
        for name, prop in properties.items():
            if prop.get("type") == "title":
                return name
        raise ValueError("Nessuna proprietà titolo trovata nel database Notion.")

    def add_note(self, title: str, content: str = "") -> str:
        if not self.database_id:
            return "Notion non configurato: imposta NOTION_DATABASE_ID."
        try:
            title_property = self._database_title_property()
        except Exception as exc:
            return f"Configurazione Notion non valida: {exc}"

        children = []
        for paragraph in content.split("\n\n"):
            text = paragraph.strip()
            if text:
                children.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]},
                    }
                )

        payload = {
            "parent": {"database_id": self.database_id},
            "properties": {title_property: {"title": [{"type": "text", "text": {"content": title[:2000]}}]}},
        }
        if children:
            payload["children"] = children[:100]

        response = httpx.post(
            f"{self.base_url}/pages",
            headers=self._headers,
            json=payload,
            timeout=25,
        )
        if response.status_code >= 400:
            return f"Creazione pagina Notion non riuscita: {response.status_code} {response.text[:200]}"
        data = response.json()
        return f"Pagina Notion creata: {title} ({data.get('url', '')})"
