"""FastAPI receiver for Crustdata watch notifications (task A11).

    uvicorn clearance.watch.webhook:app --port 8000
    ngrok http 8000        # then export CLEARANCE_WEBHOOK_URL=https://<id>.ngrok.app/webhook/crustdata

Signature check: Crustdata sends `x-crustdata-signature: t=<unix>,v1=<hex>`, an HMAC-SHA256 over
"<t>.<raw body>" keyed with the API key (per docs; verify against a /watch/company/{id}/test delivery).
"""
from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import FastAPI, Header, HTTPException, Request

from clearance import config, store
from clearance.watch import handle_event

app = FastAPI(title="Clearance watcher webhook")


def verify(raw: bytes, header: str | None, secret: str) -> bool:
    if not secret:
        return True  # no key configured (local demo): accept
    if not header:
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    expected = hmac.new(secret.encode(), f"{parts.get('t', '')}.".encode() + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", ""))


@app.post("/webhook/crustdata")
async def crustdata_webhook(request: Request, x_crustdata_signature: str | None = Header(default=None)):
    raw = await request.body()
    if not verify(raw, x_crustdata_signature, config.CRUSTDATA_API_KEY):
        raise HTTPException(status_code=401, detail="bad signature")
    payload = json.loads(raw or b"{}")
    conn = store.connect(config.DB_PATH)
    try:
        updated = handle_event(conn, payload)
    finally:
        conn.close()
    return {"ok": True, "test": bool((payload.get("metadata") or {}).get("test")), "updated": updated}


@app.get("/health")
def health():
    return {"ok": True}
