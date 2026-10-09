import asyncio, logging, math, re, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
from . import config, store, tg, llm
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
UNITS = {"seconds": 1, "minutes": 60, "hours": 3600}

@asynccontextmanager
async def lifespan(app):
    await tg.start_all(); task = asyncio.create_task(tg.broadcaster())  # exactly one scheduler loop
    try: yield
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        await tg.shutdown()

app = FastAPI(title="Telegram Promo Manager", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
tpl = Jinja2Templates(directory="app/templates")

def _name(n):
    if not tg.NAME_RE.match(n or ""): raise HTTPException(400, "Account name: letters, digits, _ or - (max 32)")
    return n
def _guard(coro_fn):
    async def run(*a):
        try: return await coro_fn(*a)
        except HTTPException: raise
        except Exception as e: raise HTTPException(400, f"{type(e).__name__}: {e}")
    return run

@app.get("/")
def index(request: Request): return tpl.TemplateResponse(request, "index.html", {})

@app.get("/api/state")
async def state():
    d = store.load()
    accs = [{**a, "status": await tg.status(a["name"])} for a in d["accounts"]]
    return {"settings": d["settings"], "broadcast": d["broadcast"], "accounts": accs, "groups": d["groups"],
            "events": d["events"][:25], "default_prompt": store.DEFAULT_PROMPT, "ollama_key_set": bool(config.OLLAMA_API_KEY)}

@app.put("/api/settings")
def put_settings(body: dict):
    def f(d):
        s = d["settings"]
        for k in ("greeting", "system_prompt", "model", "ollama_url"):
            if k in body:
                if not isinstance(body[k], str): raise HTTPException(400, f"{k} must be text")
                s[k] = body[k] if k in ("greeting", "system_prompt") else body[k].strip()
        if not s["model"] or not s["ollama_url"].startswith(("http://", "https://")): raise HTTPException(400, "Model and a valid http(s) Ollama URL are required")
        for k in ("ai_enabled", "greeting_enabled"):
            if k in body: s[k] = bool(body[k])
        if "history_limit" in body:
            try: n = int(body["history_limit"])
            except (TypeError, ValueError): raise HTTPException(400, "history_limit must be a whole number")
            if n < 1: raise HTTPException(400, "history_limit must be at least 1")
            s["history_limit"] = n
    store.mutate(f); return {"ok": True}

@app.post("/api/ollama/test")
async def ollama_test(): return await llm.test(False)
@app.post("/api/ollama/test-model")
async def ollama_test_model(): return await llm.test(True)

# ----- accounts -----
@app.post("/api/accounts")
async def add_account(body: dict):
    n = _name(body.get("name")); phone = str(body.get("phone", "")).strip()
    if not phone: raise HTTPException(400, "Phone number required")
    def f(d):
        if not any(a["name"] == n for a in d["accounts"]): d["accounts"].append({"name": n, "phone": phone})
    store.mutate(f); await _guard(tg.send_code)(n, phone); return {"ok": True}
@app.post("/api/accounts/{name}/verify")
async def verify(name: str, body: dict): await _guard(tg.verify)(_name(name), str(body.get("code", "")).strip(), body.get("password")); return {"ok": True}
@app.post("/api/accounts/{name}/reconnect")
async def reconnect(name: str):
    if not await _guard(tg.connect)(_name(name)): raise HTTPException(400, "Session invalid or expired: add the account again to log in")
    return {"ok": True}
@app.post("/api/accounts/{name}/disconnect")
async def disconnect(name: str): await _guard(tg.disconnect)(_name(name)); return {"ok": True}
@app.delete("/api/accounts/{name}")
async def del_account(name: str):
    await _guard(tg.remove)(_name(name))
    def f(d):
        d["accounts"] = [a for a in d["accounts"] if a["name"] != name]; d["groups"] = [g for g in d["groups"] if g["account"] != name]
        store.event(d, "info", f"Account '{name}' removed (session deleted)")
    store.mutate(f); return {"ok": True}
@app.get("/api/accounts/{name}/dialogs")
async def dialogs(name: str): return await _guard(tg.dialogs)(_name(name))

# ----- groups (destinations only) -----
@app.post("/api/groups")
def add_groups(body: dict):
    def f(d):
        for g in body.get("groups", []):
            if not any(x["id"] == g["id"] and x["account"] == body["account"] for x in d["groups"]):
                d["groups"].append({"id": g["id"], "title": g["title"], "account": body["account"], "enabled": True})
    store.mutate(f); return {"ok": True}
@app.put("/api/groups/{account}/{gid}")
def toggle_group(account: str, gid: int, body: dict):
    def f(d):
        for g in d["groups"]:
            if g["id"] == gid and g["account"] == account: g["enabled"] = bool(body.get("enabled"))
    store.mutate(f); return {"ok": True}
@app.delete("/api/groups/{account}/{gid}")
def del_group(account: str, gid: int):
    store.mutate(lambda d: d.update(groups=[g for g in d["groups"] if not (g["id"] == gid and g["account"] == account)])); return {"ok": True}

# ----- broadcast: ONE message, ONE delay -----
@app.put("/api/broadcast")
def put_broadcast(body: dict):
    def f(d):
        b = d["broadcast"]
        if "message" in body: b["message"] = str(body["message"])
        if "delay_value" in body:
            try: secs = float(body["delay_value"]) * UNITS[body.get("delay_unit", "seconds")]
            except (TypeError, ValueError, KeyError): raise HTTPException(400, "Invalid delay")
            if secs <= 0 or not math.isfinite(time.time() + secs): raise HTTPException(400, "Delay must be a positive, finite duration")
            b["delay_seconds"] = secs
            if b["enabled"] and b["last_run"]: b["next_run"] = b["last_run"] + secs
    store.mutate(f); return {"ok": True}

@app.post("/api/broadcast/test")
async def broadcast_test(body: dict):
    try: await tg.send_test(_name(body.get("account")), int(body["group_id"]), body.get("text"))
    except HTTPException: raise
    except Exception as e: raise HTTPException(400, f"{type(e).__name__}: {e}")
    return {"ok": True}

@app.post("/api/broadcast/{action}")
def broadcast_ctl(action: str):
    def f(d):
        b = d["broadcast"]
        if action == "start":
            if not b["message"].strip() or not any(g["enabled"] for g in d["groups"]): raise HTTPException(400, "Set a message and enable at least one group first")
            b.update(enabled=True, paused=False, next_run=None)  # first cycle runs immediately
        elif action == "stop": b.update(enabled=False, paused=False, next_run=None)
        elif action == "pause":
            if not b["enabled"]: raise HTTPException(400, "Scheduler is not running")
            b["paused"] = True
        elif action == "resume": b["paused"] = False
        else: raise HTTPException(404, "Unknown action")
        store.event(d, "info", f"Scheduler: {action}")
    store.mutate(f); return {"ok": True}

# ----- conversations (read-only inbox + per-user AI toggle) -----
@app.get("/api/conversations")
def conversations():
    out = []
    for k, c in store.load()["conversations"].items():
        m = c["messages"]; us = [x for x in m if x["role"] == "user"]; asst = [x for x in m if x["role"] == "assistant" and x["kind"] != "greeting"]
        out.append({"key": k, "user_id": c["user_id"], "name": c.get("name"), "username": c.get("username"), "ai_enabled": c["ai_enabled"],
                    "last_activity": c.get("last_activity"), "latest_message": us[-1]["text"] if us else "", "latest_response": asst[-1]["text"] if asst else ""})
    return sorted(out, key=lambda x: x["last_activity"] or 0, reverse=True)
@app.get("/api/conversations/{key}")
def conversation(key: str):
    c = store.load()["conversations"].get(key)
    if not c: raise HTTPException(404, "Not found")
    return c
@app.put("/api/conversations/{key}")
def conv_ai(key: str, body: dict):
    def f(d):
        if key not in d["conversations"]: raise HTTPException(404, "Not found")
        d["conversations"][key]["ai_enabled"] = bool(body.get("ai_enabled"))
    store.mutate(f); return {"ok": True}

if __name__ == "__main__": uvicorn.run("app.main:app", host=config.HOST, port=config.PORT)
