from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
from datetime import UTC, datetime
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Settings
from .protocols import ProtocolStore
from .quality import recent_snapshots
from .reminders import ReminderStore
from .stats import collect_stats


def _system_payload() -> dict:
    payload: dict = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "load": list(os.getloadavg()) if hasattr(os, "getloadavg") else [0.0, 0.0, 0.0],
        "cpu_percent": None,
        "memory": None,
    }
    disk = shutil.disk_usage("/")
    payload["disk"] = {
        "total": disk.total,
        "used": disk.used,
        "free": disk.free,
        "percent": disk.used / disk.total * 100 if disk.total else 0,
    }
    try:
        import psutil

        payload["cpu_percent"] = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        payload["memory"] = {
            "total": memory.total,
            "used": memory.used,
            "percent": memory.percent,
        }
        battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if battery is not None:
            payload["battery"] = {"percent": battery.percent, "plugged": battery.power_plugged}
    except Exception:
        pass
    return payload


def _artifact_payload(settings: Settings, limit: int = 10) -> list[dict]:
    files: list[Path] = []
    for directory in (settings.output_path, settings.reports_path):
        if directory.exists():
            files.extend(path for path in directory.iterdir() if path.is_file() and not path.name.startswith("."))
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [
        {
            "name": path.name,
            "size": path.stat().st_size,
            "modified": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(),
            "directory": path.parent.name,
        }
        for path in files[:limit]
    ]


def build_status(settings: Settings) -> dict:
    stats = collect_stats(settings.db_path)
    timezone_info = ZoneInfo(settings.timezone)

    reminders = []
    try:
        store = ReminderStore(settings.app_db_path_obj, settings.timezone)
        reminders = [
            {
                "id": reminder.id,
                "text": reminder.text,
                "due": reminder.due_local(timezone_info).strftime("%d/%m %H:%M"),
                "recurrence": reminder.recurrence,
            }
            for reminder in store.list(settings.telegram_allowed_user_id)
        ]
    except Exception:
        reminders = []

    try:
        quality = recent_snapshots(settings.app_db_path_obj, 8)
    except Exception:
        quality = []

    try:
        protocols = [protocol.name for protocol in ProtocolStore(settings.app_db_path_obj).list()]
    except Exception:
        protocols = []

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "system": _system_payload(),
        "stats": {
            "sessions": stats.sessions,
            "runs": stats.runs,
            "tokens": stats.total_tokens,
            "input_tokens": stats.input_tokens,
            "output_tokens": stats.output_tokens,
            "duration": stats.duration,
            "models": dict(stats.models),
            "tools": dict(stats.tools),
            "last_activity": stats.last_activity.isoformat() if stats.last_activity else None,
        },
        "reminders": reminders,
        "quality": quality,
        "protocols": protocols,
        "artifacts": _artifact_payload(settings),
    }


HUD_HTML = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>J.A.R.V.I.S. // HUD</title>
<style>
  :root { --bg:#04070d; --panel:#08111c; --cyan:#39d5ff; --cyan-dim:#1a7f9e; --orange:#ffb347; --text:#cfe9f5; --muted:#5f7f90; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font-family:"SF Mono",Menlo,Consolas,monospace; min-height:100vh; overflow-x:hidden; }
  body::after { content:""; position:fixed; inset:0; pointer-events:none; background:repeating-linear-gradient(0deg, rgba(57,213,255,.035) 0 1px, transparent 1px 3px); }
  .wrap { max-width:1200px; margin:0 auto; padding:28px 22px 60px; }
  header { display:flex; align-items:baseline; justify-content:space-between; gap:16px; border-bottom:1px solid rgba(57,213,255,.25); padding-bottom:14px; margin-bottom:22px; }
  h1 { font-size:26px; letter-spacing:8px; margin:0; color:var(--cyan); text-shadow:0 0 18px rgba(57,213,255,.55); font-weight:600; }
  .sub { color:var(--muted); font-size:11px; letter-spacing:2px; }
  #clock { color:var(--orange); font-size:20px; letter-spacing:3px; text-shadow:0 0 14px rgba(255,179,71,.4); }
  .grid { display:grid; grid-template-columns:repeat(12,1fr); gap:14px; }
  .card { background:linear-gradient(180deg, rgba(12,26,40,.92), rgba(5,12,20,.92)); border:1px solid rgba(57,213,255,.22); border-radius:10px; padding:16px; position:relative; overflow:hidden; }
  .card::before { content:""; position:absolute; top:0; left:0; width:100%; height:1px; background:linear-gradient(90deg, transparent, var(--cyan), transparent); opacity:.5; }
  .card h2 { margin:0 0 12px; font-size:11px; letter-spacing:3px; color:var(--cyan); font-weight:600; }
  .span4 { grid-column:span 4; } .span6 { grid-column:span 6; } .span8 { grid-column:span 8; } .span12 { grid-column:span 12; }
  .row { display:flex; justify-content:space-between; gap:12px; padding:5px 0; border-bottom:1px dashed rgba(57,213,255,.08); font-size:13px; }
  .row:last-child { border-bottom:none; }
  .label { color:var(--muted); }
  .value { color:var(--text); text-align:right; }
  .big { font-size:30px; color:var(--orange); text-shadow:0 0 16px rgba(255,179,71,.35); }
  .bar { height:6px; background:rgba(57,213,255,.12); border-radius:4px; overflow:hidden; margin-top:7px; }
  .bar > i { display:block; height:100%; background:linear-gradient(90deg,var(--cyan),var(--orange)); box-shadow:0 0 10px rgba(57,213,255,.5); }
  ul { list-style:none; margin:0; padding:0; }
  li { padding:6px 0; border-bottom:1px dashed rgba(57,213,255,.08); font-size:13px; }
  li:last-child { border-bottom:none; }
  .muted { color:var(--muted); }
  .chip { display:inline-block; border:1px solid rgba(57,213,255,.3); color:var(--cyan); border-radius:999px; padding:3px 10px; margin:3px 4px 0 0; font-size:11px; }
  .ok { color:#5dffb0; } .warn { color:var(--orange); }
  footer { margin-top:22px; color:var(--muted); font-size:10px; letter-spacing:2px; text-align:center; }
  @media (max-width:900px){ .span4,.span6,.span8{grid-column:span 12;} h1{font-size:18px;letter-spacing:4px;} }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>J.A.R.V.I.S.</h1>
      <div class="sub">JUST A RATHER VERY INTELLIGENT SYSTEM // LOCAL HUD</div>
    </div>
    <div id="clock">--:--:--</div>
  </header>

  <div class="grid">
    <section class="card span4">
      <h2>SISTEMA</h2>
      <div class="row"><span class="label">Host</span><span class="value" id="sys-host">—</span></div>
      <div class="row"><span class="label">Load</span><span class="value" id="sys-load">—</span></div>
      <div class="row"><span class="label">CPU</span><span class="value" id="sys-cpu">—</span></div>
      <div class="row"><span class="label">RAM</span><span class="value" id="sys-ram">—</span></div>
      <div class="row"><span class="label">Disco</span><span class="value" id="sys-disk">—</span></div>
      <div class="bar"><i id="disk-bar" style="width:0%"></i></div>
    </section>

    <section class="card span4">
      <h2>ATTIVITÀ</h2>
      <div class="row"><span class="label">Sessioni</span><span class="value" id="st-sessions">—</span></div>
      <div class="row"><span class="label">Run</span><span class="value" id="st-runs">—</span></div>
      <div class="row"><span class="label">Token</span><span class="value" id="st-tokens">—</span></div>
      <div class="row"><span class="label">Tempo modello</span><span class="value" id="st-duration">—</span></div>
      <div class="row"><span class="label">Ultima attività</span><span class="value" id="st-last">—</span></div>
    </section>

    <section class="card span4">
      <h2>PROTOCOLLI</h2>
      <div id="protocols"><span class="muted">—</span></div>
    </section>

    <section class="card span8">
      <h2>PROMEMORIA</h2>
      <ul id="reminders"><li class="muted">Nessun promemoria.</li></ul>
    </section>

    <section class="card span4">
      <h2>QUALITÀ</h2>
      <ul id="quality"><li class="muted">Nessuna analisi.</li></ul>
    </section>

    <section class="card span12">
      <h2>ARTEFATTI RECENTI</h2>
      <ul id="artifacts"><li class="muted">Nessun file.</li></ul>
    </section>
  </div>

  <footer>SOLO LOCALE · 127.0.0.1 · AGGIORNAMENTO OGNI 3s</footer>
</div>

<script>
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const gb = (n) => (n / 1073741824).toFixed(1) + ' GB';

function set(id, value){ const el = document.getElementById(id); if (el) el.textContent = value; }

async function refresh(){
  try {
    const response = await fetch('/api/status', {cache:'no-store'});
    const data = await response.json();
    const sys = data.system || {};
    set('sys-host', (sys.machine || '') + ' · ' + (sys.platform || '').split(' ')[0]);
    set('sys-load', (sys.load || []).map(v => Number(v).toFixed(2)).join(' / '));
    set('sys-cpu', sys.cpu_percent == null ? 'n/d' : sys.cpu_percent.toFixed(0) + '%');
    set('sys-ram', sys.memory ? sys.memory.percent.toFixed(0) + '% · ' + gb(sys.memory.used) : 'n/d');
    set('sys-disk', gb(sys.disk.used) + ' / ' + gb(sys.disk.total));
    document.getElementById('disk-bar').style.width = (sys.disk.percent || 0).toFixed(1) + '%';

    const st = data.stats || {};
    set('st-sessions', st.sessions ?? 0);
    set('st-runs', st.runs ?? 0);
    set('st-tokens', (st.tokens ?? 0).toLocaleString('it-IT'));
    set('st-duration', (st.duration ?? 0).toFixed(0) + 's');
    set('st-last', st.last_activity ? new Date(st.last_activity).toLocaleString('it-IT') : '—');

    const protocols = data.protocols || [];
    document.getElementById('protocols').innerHTML = protocols.length
      ? protocols.map(p => '<span class="chip">' + esc(p) + '</span>').join('')
      : '<span class="muted">Nessun protocollo.</span>';

    const reminders = data.reminders || [];
    document.getElementById('reminders').innerHTML = reminders.length
      ? reminders.map(r => '<li><span class="ok">' + esc(r.due) + '</span> — ' + esc(r.text) + (r.recurrence !== 'none' ? ' <span class="muted">(' + esc(r.recurrence) + ')</span>' : '') + '</li>').join('')
      : '<li class="muted">Nessun promemoria.</li>';

    const quality = data.quality || [];
    document.getElementById('quality').innerHTML = quality.length
      ? quality.slice(-5).reverse().map(q => '<li>' + esc(q.source) + ' — <span class="warn">' + esc(q.grand_total) + '</span></li>').join('')
      : '<li class="muted">Nessuna analisi.</li>';

    const artifacts = data.artifacts || [];
    document.getElementById('artifacts').innerHTML = artifacts.length
      ? artifacts.map(a => '<li>' + esc(a.name) + ' <span class="muted">· ' + (a.size/1024).toFixed(0) + ' KB · ' + esc(a.directory) + '</span></li>').join('')
      : '<li class="muted">Nessun file.</li>';
  } catch (error) {
    set('clock', 'OFFLINE');
  }
}

function tick(){
  const now = new Date();
  document.getElementById('clock').textContent = now.toLocaleTimeString('it-IT');
}

tick(); setInterval(tick, 1000);
refresh(); setInterval(refresh, 3000);
</script>
</body>
</html>
"""


class HUDHandler(BaseHTTPRequestHandler):
    settings: Settings

    def __init__(self, *args, settings: Settings, **kwargs) -> None:
        self.settings = settings
        super().__init__(*args, **kwargs)

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        path = self.path.split("?", 1)[0]
        if path in {"/", "/index.html"}:
            self._send(200, "text/html; charset=utf-8", HUD_HTML.encode("utf-8"))
            return
        if path == "/api/status":
            body = json.dumps(build_status(self.settings), ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
            return
        if path == "/health":
            self._send(200, "application/json", b'{"status":"ok"}')
            return
        self._send(404, "text/plain; charset=utf-8", b"Not found")

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        return


def serve(settings: Settings, host: str | None = None, port: int | None = None) -> None:
    settings.ensure_directories()
    server = ThreadingHTTPServer(
        (host or settings.dashboard_host, port or settings.dashboard_port),
        partial(HUDHandler, settings=settings),
    )
    print(f"Jarvis HUD locale: http://{server.server_address[0]}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis HUD locale")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    serve(Settings(), args.host, args.port)


if __name__ == "__main__":
    main()
