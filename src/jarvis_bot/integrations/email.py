from __future__ import annotations

import imaplib
import smtplib
import ssl
from email import message_from_bytes
from email.header import decode_header
from email.message import EmailMessage


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for chunk, encoding in decode_header(value):
        if isinstance(chunk, bytes):
            try:
                parts.append(chunk.decode(encoding or "utf-8", errors="replace"))
            except LookupError:
                parts.append(chunk.decode("utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts)


class EmailClient:
    def __init__(
        self,
        imap_host: str,
        imap_port: int,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        sender: str | None = None,
    ) -> None:
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.sender = sender or username

    def _imap(self) -> imaplib.IMAP4_SSL:
        client = imaplib.IMAP4_SSL(self.imap_host, self.imap_port, timeout=20)
        client.login(self.username, self.password)
        return client

    def _fetch_headers(self, message_ids: list[bytes], limit: int) -> list[str]:
        lines: list[str] = []
        with self._imap() as client:
            client.select("INBOX")
            for message_id in message_ids[-limit:]:
                status, data = client.fetch(
                    message_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
                )
                if status != "OK" or not data or not isinstance(data[0], tuple):
                    continue
                message = message_from_bytes(data[0][1])
                sender = _decode_header_value(message.get("From"))
                subject = _decode_header_value(message.get("Subject"))
                date = message.get("Date", "")
                lines.append(f"• {subject or '(senza oggetto)'} — {sender} — {date}")
        return lines

    def list_unread(self, limit: int = 10) -> str:
        try:
            with self._imap() as client:
                client.select("INBOX")
                status, data = client.search(None, "UNSEEN")
                if status != "OK":
                    return "Lettura email non riuscita."
                ids = data[0].split()
            if not ids:
                return "Nessuna email non letta. 📭"
            lines = self._fetch_headers(ids, limit)
        except Exception as exc:
            return f"Email non raggiungibile: {exc}"
        header = f"📬 **Email non lette ({len(ids)})**"
        return "\n".join([header, *lines])

    def search(self, query: str, limit: int = 10) -> str:
        try:
            with self._imap() as client:
                client.select("INBOX")
                status, data = client.search(None, "TEXT", f'"{query}"')
                if status != "OK":
                    return "Ricerca email non riuscita."
                ids = data[0].split()
            if not ids:
                return f"Nessuna email per '{query}'."
            lines = self._fetch_headers(ids, limit)
        except Exception as exc:
            return f"Email non raggiungibile: {exc}"
        return "\n".join([f"📬 **Email per '{query}'**", *lines])

    def send(self, to: str, subject: str, body: str) -> str:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(self.username, self.password)
                smtp.send_message(message)
        except Exception as exc:
            return f"Invio email non riuscito: {exc}"
        return f"Email inviata a {to}."
