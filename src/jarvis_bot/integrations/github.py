from __future__ import annotations

import httpx


class GitHubClient:
    def __init__(self, token: str, default_repo: str | None = None) -> None:
        self.token = token
        self.default_repo = default_repo
        self.base_url = "https://api.github.com"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _repo(self, repo: str | None) -> str:
        resolved = repo or self.default_repo
        if not resolved or "/" not in resolved:
            raise ValueError("Specifica un repository nel formato 'owner/repo'.")
        return resolved

    def _get(self, path: str, params: dict | None = None):
        response = httpx.get(
            f"{self.base_url}{path}", headers=self._headers, params=params, timeout=20
        )
        response.raise_for_status()
        return response.json()

    def list_issues(self, repo: str | None = None, state: str = "open", limit: int = 10) -> str:
        resolved = self._repo(repo)
        try:
            items = self._get(
                f"/repos/{resolved}/issues",
                {"state": state, "per_page": min(limit * 2, 50)},
            )
        except Exception as exc:
            return f"GitHub non raggiungibile: {exc}"
        issues = [item for item in items if "pull_request" not in item][:limit]
        if not issues:
            return f"Nessuna issue {state} in {resolved}."
        lines = [f"🐙 **Issue {state} — {resolved}**"]
        for issue in issues:
            author = (issue.get("user") or {}).get("login", "?")
            lines.append(f"• #{issue['number']} {issue['title']} — @{author}")
        return "\n".join(lines)

    def list_pull_requests(self, repo: str | None = None, state: str = "open", limit: int = 10) -> str:
        resolved = self._repo(repo)
        try:
            items = self._get(
                f"/repos/{resolved}/pulls",
                {"state": state, "per_page": min(limit, 50)},
            )
        except Exception as exc:
            return f"GitHub non raggiungibile: {exc}"
        if not items:
            return f"Nessuna pull request {state} in {resolved}."
        lines = [f"🐙 **Pull request {state} — {resolved}**"]
        for pull in items[:limit]:
            author = (pull.get("user") or {}).get("login", "?")
            lines.append(f"• #{pull['number']} {pull['title']} — @{author} ({pull.get('head', {}).get('ref', '?')})")
        return "\n".join(lines)

    def repo_summary(self, repo: str | None = None) -> str:
        resolved = self._repo(repo)
        try:
            data = self._get(f"/repos/{resolved}")
        except Exception as exc:
            return f"GitHub non raggiungibile: {exc}"
        return (
            f"🐙 **{data.get('full_name', resolved)}**\n"
            f"{data.get('description') or 'Nessuna descrizione.'}\n"
            f"⭐ {data.get('stargazers_count', 0)} · 🍴 {data.get('forks_count', 0)} · "
            f"issue aperte: {data.get('open_issues_count', 0)}\n"
            f"Linguaggio: {data.get('language') or 'n/d'} · Branch: {data.get('default_branch', 'main')}"
        )

    def create_issue(self, title: str, body: str = "", repo: str | None = None) -> str:
        resolved = self._repo(repo)
        response = httpx.post(
            f"{self.base_url}/repos/{resolved}/issues",
            headers=self._headers,
            json={"title": title, "body": body},
            timeout=20,
        )
        if response.status_code >= 400:
            return f"Creazione issue non riuscita: {response.status_code} {response.text[:200]}"
        data = response.json()
        return f"Issue creata: #{data['number']} {data['title']} ({data['html_url']})"

    def count_notifications(self) -> int:
        try:
            response = httpx.get(
                f"{self.base_url}/notifications",
                headers=self._headers,
                params={"all": "false", "per_page": 100},
                timeout=20,
            )
            response.raise_for_status()
            return len(response.json())
        except Exception:
            return 0

    def search_issues(self, query: str, repo: str | None = None, limit: int = 5) -> str:
        resolved = self._repo(repo)
        try:
            data = self._get(
                "/search/issues",
                {"q": f"repo:{resolved} {query}", "per_page": limit},
            )
        except Exception as exc:
            return f"Ricerca GitHub non riuscita: {exc}"
        items = data.get("items") or []
        if not items:
            return f"Nessun risultato per '{query}' in {resolved}."
        lines = [f"🐙 **Ricerca: {query} — {resolved}**"]
        for item in items:
            kind = "PR" if item.get("pull_request") else "issue"
            lines.append(f"• [{kind}] #{item['number']} {item['title']}")
        return "\n".join(lines)
