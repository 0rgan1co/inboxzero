#!/usr/bin/env python3
"""
Sync InboxZero → Obsidian vault. (v2)

Lee del bot:
  - Mensajes 'pending' → notas markdown en _Inbox/ (configurable con INBOXZERO_SUBDIR)
  - Recordatorios no synced → notas markdown en _Inbox/ (configurable con INBOXZERO_REMINDERS_SUBDIR)

Después marca todo como synced en el bot.

Uso:
    INBOXZERO_API_URL=https://tubot.up.railway.app \\
    INBOXZERO_API_KEY=<sync-api-key> \\
    OBSIDIAN_VAULT_PATH=/Users/roldanjorgex/second-brain \\
    python3 sync_to_obsidian.py

También se puede crear un archivo .env con esas vars.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(Path(__file__).parent / ".env")
_load_dotenv(Path.cwd() / ".env")

API_URL = os.environ.get("INBOXZERO_API_URL", "").rstrip("/")
API_KEY = os.environ.get("INBOXZERO_API_KEY", "")
VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH", "")
SUBDIR = os.environ.get("INBOXZERO_SUBDIR", "_Inbox")
REMINDERS_SUBDIR = os.environ.get("INBOXZERO_REMINDERS_SUBDIR", "_Inbox")
TIMEOUT = float(os.environ.get("INBOXZERO_HTTP_TIMEOUT", "30"))


def fail(msg: str, code: int = 1) -> None:
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(code)


def http_request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{API_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-Api-Key", API_KEY)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        fail(f"HTTP {e.code} en {method} {url}: {body_text}")
    except urllib.error.URLError as e:
        fail(f"No pude llegar a {url}: {e.reason}")
    return {}


_SLUG_RE = re.compile(r"[^a-z0-9\-]+")


def slugify(text: str, max_len: int = 60) -> str:
    s = text.lower().strip()
    s = re.sub(r"\s+", "-", s)
    s = _SLUG_RE.sub("", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return (s or "captura")[:max_len]


def _parse_dt(iso: str) -> datetime:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")) if iso else datetime.now()
    except ValueError:
        return datetime.now()


def write_message(item: dict, dest_dir: Path) -> Path:
    dt = _parse_dt(item.get("created_at", ""))
    classification = item.get("classification", "nota")
    text = (item.get("text") or "").strip()

    slug = slugify(text.split("\n", 1)[0], max_len=50)
    filename = f"{dt.strftime('%Y-%m-%d-%H%M%S')}-{classification}-{slug}.md"
    path = dest_dir / filename

    frontmatter = (
        "---\n"
        "source: telegram\n"
        f"type: {classification}\n"
        f"captured_at: {dt.isoformat()}\n"
        f"telegram_msg_id: {item.get('telegram_msg_id')}\n"
        f"chat_id: {item.get('chat_id')}\n"
        f"user_id: {item.get('user_id')}\n"
        f"username: {item.get('username') or ''}\n"
        f"local_id: {item.get('id')}\n"
        "status: new\n"
        "tags: [inbox-zero, captura]\n"
        "---\n\n"
    )
    body = f"# {classification.capitalize()}\n\n{text}\n\n---\n*Capturado vía @ceroinbox_bot*\n"
    path.write_text(frontmatter + body, encoding="utf-8")
    return path


def write_reminder(item: dict, dest_dir: Path) -> Path:
    created = _parse_dt(item.get("created_at", ""))
    fire_at = item.get("fire_at", "")
    fired_at = item.get("fired_at", "")
    rstatus = item.get("status", "pending")
    text = (item.get("text") or "").strip()

    slug = slugify(text.split("\n", 1)[0], max_len=40)
    filename = f"{created.strftime('%Y-%m-%d-%H%M%S')}-recordatorio-{rstatus}-{slug}.md"
    path = dest_dir / filename

    frontmatter = (
        "---\n"
        "source: telegram\n"
        "type: recordatorio\n"
        f"reminder_status: {rstatus}\n"
        f"created_at: {created.isoformat()}\n"
        f"due_at: {fire_at}\n"
        f"fired_at: {fired_at or ''}\n"
        f"chat_id: {item.get('chat_id')}\n"
        f"user_id: {item.get('user_id')}\n"
        f"local_id: {item.get('id')}\n"
        "tags: [inbox-zero, recordatorio]\n"
        "---\n\n"
    )
    body = (
        f"# Recordatorio (#{item.get('id')})\n\n"
        f"**Vence:** `{fire_at}`\n"
        f"**Estado:** `{rstatus}`\n\n"
        f"{text}\n\n---\n*Capturado vía @ceroinbox_bot*\n"
    )
    path.write_text(frontmatter + body, encoding="utf-8")
    return path


def sync_messages(vault: Path) -> int:
    dest_dir = vault / SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"→ GET {API_URL}/pending")
    resp = http_request("GET", "/pending")
    items = resp.get("items", [])
    if not items:
        print("  ✓ Nada nuevo en mensajes.")
        return 0

    print(f"  → {len(items)} mensajes pendientes. Escribiendo en {dest_dir} ...")
    written_ids: list[int] = []
    for item in items:
        try:
            path = write_message(item, dest_dir)
            written_ids.append(item["id"])
            print(f"    ✓ {path.name}")
        except Exception as exc:
            print(f"    ✗ id={item.get('id')} falló: {exc}", file=sys.stderr)

    if not written_ids:
        return 0
    print(f"  → POST /mark-synced ({len(written_ids)} ids)")
    r = http_request("POST", "/mark-synced", {"ids": written_ids})
    print(f"  ✓ {r.get('updated')} marcadas como synced.")
    return len(written_ids)


def sync_reminders(vault: Path) -> int:
    dest_dir = vault / REMINDERS_SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"→ GET {API_URL}/reminders/unsynced")
    resp = http_request("GET", "/reminders/unsynced")
    items = resp.get("items", [])
    if not items:
        print("  ✓ Nada nuevo en recordatorios.")
        return 0

    print(f"  → {len(items)} recordatorios. Escribiendo en {dest_dir} ...")
    written_ids: list[int] = []
    for item in items:
        try:
            path = write_reminder(item, dest_dir)
            written_ids.append(item["id"])
            print(f"    ✓ {path.name}")
        except Exception as exc:
            print(f"    ✗ id={item.get('id')} falló: {exc}", file=sys.stderr)

    if not written_ids:
        return 0
    print(f"  → POST /reminders/mark-synced ({len(written_ids)} ids)")
    r = http_request("POST", "/reminders/mark-synced", {"ids": written_ids})
    print(f"  ✓ {r.get('updated')} marcados como synced.")
    return len(written_ids)


def main() -> int:
    if not API_URL:
        fail("INBOXZERO_API_URL no seteado.")
    if not API_KEY:
        fail("INBOXZERO_API_KEY no seteado.")
    if not VAULT_PATH:
        fail("OBSIDIAN_VAULT_PATH no seteado.")

    vault = Path(VAULT_PATH).expanduser().resolve()
    if not vault.exists() or not vault.is_dir():
        fail(f"Vault no existe o no es un directorio: {vault}")

    n_msgs = sync_messages(vault)
    n_rems = sync_reminders(vault)
    print(f"\n✓ Sync completo: {n_msgs} mensajes + {n_rems} recordatorios.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
