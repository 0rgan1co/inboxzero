"""Web UI mínima para revisar/editar capturas y recordatorios.

Auth: cookie HttpOnly seteada por POST /ui/login con la SYNC_API_KEY.
La cookie expira en 7 días. Cerrar sesión con POST /ui/logout.

Endpoints servidos:
    GET  /ui              → HTML SPA (login si no hay cookie)
    POST /ui/login        → setea cookie
    POST /ui/logout       → borra cookie
    GET  /ui/data         → JSON con messages + reminders (requiere cookie)
    POST /ui/messages/{id}/edit  → body: {text?, classification?}
    POST /ui/messages/{id}/delete
    POST /ui/messages/{id}/sync       → marca synced manualmente
    POST /ui/reminders/{id}/cancel
"""
from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import config, db

router = APIRouter()

COOKIE_NAME = "inboxzero_session"
COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 días

INDEX_HTML = """<!doctype html>
<html lang=\"es\">
<head>
<meta charset=\"utf-8\" />
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
<title>InboxZero</title>
<style>
:root {
  --bg:#0f1115; --card:#151821; --border:#22262f; --text:#e7e9ee;
  --muted:#8a8f9c; --accent:#7aa7ff; --danger:#ff7a7a; --ok:#7aff9a;
}
* { box-sizing: border-box; }
body { background:var(--bg); color:var(--text); font:14px/1.5 -apple-system, system-ui, sans-serif; margin:0; padding:24px; max-width:980px; margin:auto; }
h1 { font-size:20px; margin:0 0 16px; }
h2 { font-size:14px; color:var(--muted); margin:24px 0 8px; text-transform:uppercase; letter-spacing:.05em; }
.row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
button, .btn { background:var(--card); border:1px solid var(--border); color:var(--text); padding:6px 12px; border-radius:6px; cursor:pointer; font-size:13px; }
button:hover { border-color:var(--accent); }
button.danger { color:var(--danger); }
button.primary { background:var(--accent); color:#0f1115; border-color:var(--accent); }
input, select, textarea { background:var(--card); border:1px solid var(--border); color:var(--text); padding:6px 10px; border-radius:6px; font:inherit; }
.card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:12px; margin:8px 0; }
.card .meta { font-size:12px; color:var(--muted); }
.tag { display:inline-block; padding:2px 8px; border-radius:99px; font-size:11px; background:#22262f; color:var(--muted); margin-right:4px; }
.tag.idea { background:#332b14; color:#ffd99a; }
.tag.pedido { background:#142a33; color:#9ad9ff; }
.tag.tarea { background:#143323; color:#9affb6; }
.tag.nota { background:#222630; color:#c9ccd6; }
.tag.fired { background:#332f4a; color:#cbb8ff; }
.tag.cancelled { background:#3a1f1f; color:#ff9a9a; }
.tag.synced { background:#1a2a1a; color:#80c898; }
.empty { color:var(--muted); padding:20px; text-align:center; }
.row > input[type=text] { flex:1; min-width:200px; }
.login { max-width:400px; margin:80px auto; text-align:center; }
.error { color:var(--danger); margin-top:8px; }
.muted { color:var(--muted); }
.spacer { flex:1; }
@media (max-width: 600px) { body { padding:12px; } }
</style>
</head>
<body>
<div id=\"app\"></div>
<script>
const $ = (id) => document.getElementById(id);
const root = $(\"app\");
const fmt = (iso) => iso ? new Date(iso.endsWith(\"Z\") || iso.includes(\"+\") ? iso : iso+\"Z\").toLocaleString(\"es-AR\") : \"-\";

async function api(path, opts={}) {
  const r = await fetch(path, {credentials:\"include\", headers:{\"Content-Type\":\"application/json\"}, ...opts});
  if (r.status === 401) { renderLogin(\"Sesión expirada.\"); throw new Error(\"unauth\"); }
  if (!r.ok) { throw new Error(\"http \"+r.status); }
  return r.json();
}

function renderLogin(err) {
  root.innerHTML = `
    <div class=\"login\">
      <h1>InboxZero</h1>
      <p class=\"muted\">Pegá tu SYNC_API_KEY para entrar.</p>
      <input type=\"password\" id=\"key\" placeholder=\"SYNC_API_KEY\" style=\"width:100%; margin:12px 0;\">
      <button class=\"primary\" id=\"loginBtn\">Entrar</button>
      <div class=\"error\">${err || \"\"}</div>
    </div>`;
  $(\"loginBtn\").onclick = async () => {
    const key = $(\"key\").value;
    const r = await fetch(\"/ui/login\", {method:\"POST\", headers:{\"Content-Type\":\"application/json\"}, body: JSON.stringify({api_key: key}), credentials:\"include\"});
    if (r.ok) { load(); } else { renderLogin(\"Clave incorrecta.\"); }
  };
  $(\"key\").onkeydown = (e) => { if (e.key === \"Enter\") $(\"loginBtn\").click(); };
}

async function load() {
  try {
    const data = await api(\"/ui/data\");
    render(data);
  } catch (e) { /* renderLogin ya manejó 401 */ }
}

function render(data) {
  const stats = data.stats;
  const msgs = data.messages;
  const rems = data.reminders;
  root.innerHTML = `
    <div class=\"row\">
      <h1>InboxZero</h1>
      <span class=\"muted\">${stats.pending} pending · ${stats.synced} synced · ${stats.reminders_pending} reminders</span>
      <div class=\"spacer\"></div>
      <button id=\"refresh\">Refrescar</button>
      <button id=\"logout\">Salir</button>
    </div>
    <h2>Recordatorios pendientes</h2>
    <div id=\"reminders\">${rems.length ? rems.map(remCard).join(\"\") : `<div class=empty>Sin recordatorios pendientes.</div>`}</div>
    <h2>Capturas (últimas 100)</h2>
    <div id=\"messages\">${msgs.length ? msgs.map(msgCard).join(\"\") : `<div class=empty>Sin capturas.</div>`}</div>
  `;
  $(\"refresh\").onclick = load;
  $(\"logout\").onclick = async () => { await fetch(\"/ui/logout\", {method:\"POST\", credentials:\"include\"}); renderLogin(\"\"); };
  document.querySelectorAll(\"[data-action]\").forEach(b => b.onclick = onAction);
}

function msgCard(m) {
  return `
    <div class=\"card\" data-id=\"${m.id}\">
      <div class=\"row\">
        <span class=\"tag ${m.classification}\">${m.classification}</span>
        <span class=\"tag ${m.status}\">${m.status}</span>
        <span class=\"meta\">#${m.id} · ${fmt(m.created_at)}</span>
        <div class=\"spacer\"></div>
        ${m.status === \"pending\" ? `<button data-action=\"sync\" data-id=\"${m.id}\">Marcar synced</button>` : \"\"}
        <button data-action=\"edit\" data-id=\"${m.id}\">Editar</button>
        <button data-action=\"delete\" data-id=\"${m.id}\" class=\"danger\">Borrar</button>
      </div>
      <div style=\"margin-top:8px; white-space:pre-wrap;\">${escapeHtml(m.text)}</div>
    </div>`;
}

function remCard(r) {
  return `
    <div class=\"card\" data-id=\"${r.id}\">
      <div class=\"row\">
        <span class=\"tag\">⏰</span>
        <span class=\"meta\">#${r.id} · dispara ${fmt(r.fire_at)}</span>
        <div class=\"spacer\"></div>
        <button data-action=\"cancel-rem\" data-id=\"${r.id}\" class=\"danger\">Cancelar</button>
      </div>
      <div style=\"margin-top:8px; white-space:pre-wrap;\">${escapeHtml(r.text)}</div>
    </div>`;
}

async function onAction(ev) {
  const id = ev.target.dataset.id;
  const action = ev.target.dataset.action;
  if (action === \"sync\") { await api(`/ui/messages/${id}/sync`, {method:\"POST\"}); load(); }
  else if (action === \"delete\") {
    if (!confirm(\"¿Borrar definitivamente?\")) return;
    await api(`/ui/messages/${id}/delete`, {method:\"POST\"}); load();
  }
  else if (action === \"edit\") {
    const newText = prompt(\"Nuevo texto:\");
    if (newText === null) return;
    const newCat = prompt(\"Nueva clasificación (idea/pedido/tarea/nota), enter para no cambiar:\");
    const body = {};
    if (newText) body.text = newText;
    if (newCat) body.classification = newCat;
    await api(`/ui/messages/${id}/edit`, {method:\"POST\", body: JSON.stringify(body)}); load();
  }
  else if (action === \"cancel-rem\") {
    if (!confirm(\"¿Cancelar recordatorio?\")) return;
    await api(`/ui/reminders/${id}/cancel`, {method:\"POST\"}); load();
  }
}

function escapeHtml(s) {
  return (s||\"\").replace(/[&<>\"']/g, c => ({\"&\":\"&amp;\",\"<\":\"&lt;\",\">\":\"&gt;\",'\"':\"&quot;\",\"'\":\"&#39;\"}[c]));
}

// boot
fetch(\"/ui/data\", {credentials:\"include\"}).then(r => r.ok ? load() : renderLogin(\"\"));
</script>
</body>
</html>
"""


def _check_cookie(session_cookie: str | None) -> None:
    if not config.WEB_UI_ENABLED:
        raise HTTPException(status_code=404, detail="Web UI deshabilitada.")
    if not config.SYNC_API_KEY:
        raise HTTPException(status_code=503, detail="SYNC_API_KEY no configurado.")
    if session_cookie != config.SYNC_API_KEY:
        raise HTTPException(status_code=401, detail="Sesión inválida.")


class LoginBody(BaseModel):
    api_key: str


class EditBody(BaseModel):
    text: str | None = None
    classification: str | None = None


@router.get("/ui", response_class=HTMLResponse)
def ui_index() -> HTMLResponse:
    if not config.WEB_UI_ENABLED:
        return HTMLResponse("Web UI deshabilitada.", status_code=404)
    return HTMLResponse(INDEX_HTML)


@router.post("/ui/login")
def ui_login(body: LoginBody, request: Request) -> JSONResponse:
    if not config.WEB_UI_ENABLED:
        raise HTTPException(status_code=404, detail="Web UI deshabilitada.")
    if not config.SYNC_API_KEY:
        raise HTTPException(status_code=503, detail="SYNC_API_KEY no configurado.")
    if body.api_key != config.SYNC_API_KEY:
        raise HTTPException(status_code=401, detail="API key inválida.")
    secure = request.url.scheme == "https"
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        COOKIE_NAME, config.SYNC_API_KEY,
        max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax", secure=secure,
    )
    return resp


@router.post("/ui/logout")
def ui_logout() -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME)
    return resp


@router.get("/ui/data")
def ui_data(inboxzero_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict:
    _check_cookie(inboxzero_session)
    return {
        "stats": db.stats(),
        "messages": db.list_messages(limit=100),
        "reminders": db.list_reminders_pending(limit=50),
    }


@router.post("/ui/messages/{msg_id}/edit")
def ui_edit(
    msg_id: int,
    body: EditBody,
    inboxzero_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict:
    _check_cookie(inboxzero_session)
    if body.classification and body.classification not in ("idea", "pedido", "tarea", "nota"):
        raise HTTPException(status_code=400, detail="classification inválida.")
    n = db.update_message(msg_id, text=body.text, classification=body.classification)
    return {"updated": n}


@router.post("/ui/messages/{msg_id}/delete")
def ui_delete(
    msg_id: int,
    inboxzero_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict:
    _check_cookie(inboxzero_session)
    n = db.delete_message(msg_id)
    return {"deleted": n}


@router.post("/ui/messages/{msg_id}/sync")
def ui_mark_synced(
    msg_id: int,
    inboxzero_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict:
    _check_cookie(inboxzero_session)
    n = db.mark_synced([msg_id])
    return {"updated": n}


@router.post("/ui/reminders/{reminder_id}/cancel")
def ui_cancel_reminder(
    reminder_id: int,
    inboxzero_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict:
    _check_cookie(inboxzero_session)
    # En la UI el user_id no es trivial (cookie no tiene scope); permitimos cancelación
    # con cookie válida (autoriza el dueño de la API key).
    with db._connect() as conn:
        cur = conn.execute(
            "UPDATE reminders SET status='cancelled' WHERE id = ? AND status='pending'",
            (reminder_id,),
        )
        conn.commit()
        return {"cancelled": cur.rowcount}
