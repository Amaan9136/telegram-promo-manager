import asyncio, glob, logging, os, re, time
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from . import config, store, llm
log = logging.getLogger("tg")
clients: dict[str, TelegramClient] = {}
pending: dict[str, tuple] = {}  # account -> (phone, phone_code_hash)
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
hits: dict[str, list] = {}
mute: dict[str, float] = {}

def _client(name):
    if name not in clients:
        if not config.API_ID or not config.API_HASH: raise RuntimeError("Set TG_API_ID and TG_API_HASH in .env")
        os.makedirs(config.SESSIONS_DIR, exist_ok=True)
        clients[name] = TelegramClient(os.path.join(config.SESSIONS_DIR, name), config.API_ID, config.API_HASH)
    return clients[name]

# ---------- accounts ----------
async def send_code(name, phone):
    c = _client(name)
    if not c.is_connected(): await c.connect()
    r = await c.send_code_request(phone); pending[name] = (phone, r.phone_code_hash)

async def verify(name, code, password=None):
    if name not in pending: raise RuntimeError("Request a login code first")
    c = _client(name); phone, h = pending[name]
    try: await c.sign_in(phone=phone, code=code, phone_code_hash=h)
    except SessionPasswordNeededError:
        if not password: raise RuntimeError("2FA password required")
        await c.sign_in(password=password)
    pending.pop(name, None); await connect(name)

async def connect(name):
    """Connect/reconnect. Returns False if the session is missing, invalid or expired."""
    c = _client(name)
    if not c.is_connected(): await c.connect()
    if not await c.is_user_authorized():
        store.log_event("error", f"Account '{name}': session invalid/expired or not logged in; log in again"); return False
    if not getattr(c, "_pm_attached", False):  # attach handlers once per client object
        c._pm_attached = True
        c.add_event_handler(lambda ev: on_dm(name, ev), events.NewMessage(incoming=True, func=lambda e: e.is_private))
    me = await c.get_me()
    def f(d):
        for a in d["accounts"]:
            if a["name"] == name:
                a.update(tg_id=me.id, tg_name=" ".join(filter(None, [me.first_name, me.last_name])), username=me.username)
    store.mutate(f); return True

async def disconnect(name):
    c = clients.get(name)
    if c and c.is_connected(): await c.disconnect()

async def remove(name):
    c = clients.pop(name, None)
    if c:
        try:
            if not c.is_connected(): await c.connect()
            if await c.is_user_authorized(): await c.log_out()  # also deletes the session file
        except Exception as e: store.log_event("error", f"Logout of '{name}' failed ({e}); deleting session files anyway")
        finally:
            if c.is_connected(): await c.disconnect()
    for p in glob.glob(os.path.join(config.SESSIONS_DIR, name + ".session*")): os.remove(p)

async def status(name):
    c = clients.get(name)
    if not c or not c.is_connected(): return "disconnected"
    try: return "connected" if await c.is_user_authorized() else "needs_login"
    except Exception: return "error"

async def dialogs(name):
    c = clients.get(name)
    if not c or not c.is_connected(): raise RuntimeError("Account is not connected")
    return [{"id": d.id, "title": d.name} async for d in c.iter_dialogs() if d.is_group or d.is_channel]

async def start_all():
    for a in store.load()["accounts"]:
        try: await connect(a["name"])
        except Exception as e: store.log_event("error", f"Account '{a['name']}' failed to connect: {e}")

async def shutdown():
    for c in list(clients.values()):
        try:
            if c.is_connected(): await c.disconnect()
        except Exception as e: log.warning("disconnect: %s", e)

# ---------- private messages + AI ----------
def _add(key, who, role, text, kind="message"):
    def f(d):
        new = key not in d["conversations"]
        c = d["conversations"].setdefault(key, {"user_id": who["id"], "ai_enabled": True, "messages": []})
        c.update(name=who["name"], username=who["username"], last_activity=time.time())
        c["messages"].append({"t": time.time(), "role": role, "kind": kind, "text": text})
        del c["messages"][:-max(1, d["settings"]["history_limit"])]  # bounded history
        return new, c["ai_enabled"], dict(d["settings"]), list(c["messages"])
    return store.mutate(f)

async def on_dm(name, ev):
    try:
        sender = await ev.get_sender()
        if not sender or getattr(sender, "bot", False) or not ev.raw_text: return
        who = {"id": ev.sender_id, "username": getattr(sender, "username", None),
               "name": " ".join(filter(None, [getattr(sender, "first_name", None), getattr(sender, "last_name", None)]))}
        key = f"{name}:{who['id']}"
        new, conv_ai, s, hist = _add(key, who, "user", ev.raw_text)
        now = time.time()
        if mute.get(key, 0) > now: return
        hits[key] = [t for t in hits.get(key, []) if now - t < 60] + [now]
        if len(hits[key]) > 3:
            mute[key] = now + 120; hits[key] = []; store.log_event("info", f"Rate limit: no replies to {key} for 2 minutes"); return
        if new and s["greeting_enabled"] and s["greeting"]:
            await ev.respond(s["greeting"]); _add(key, who, "assistant", s["greeting"], "greeting")
        if s["ai_enabled"] and conv_ai:
            ctx = [{"role": m["role"], "content": m["text"]} for m in hist if m["role"] in ("user", "assistant") and m["kind"] != "greeting"]
            try: out = await llm.chat(s["system_prompt"], ctx)
            except RuntimeError as e:
                _add(key, who, "system", str(e), "error"); store.log_event("error", f"AI reply for {key} failed: {e}"); return
            if out: await ev.respond(out); _add(key, who, "assistant", out)
    except Exception as e: store.log_event("error", f"DM handler error ({name}): {type(e).__name__}: {e}")

# ---------- single broadcast scheduler ----------
async def send_test(account, group_id, text=None):
    """Independent of the schedule: touches no broadcast fields."""
    c = clients.get(account)
    if not c or not c.is_connected(): raise RuntimeError("Account is not connected")
    msg = text or store.load()["broadcast"]["message"] or "Test message"
    await c.send_message(group_id, msg); store.log_event("info", f"Test message sent to {group_id} via '{account}'")

async def run_cycle():
    d = store.load(); b = d["broadcast"]; msg = b["message"].strip(); ok = fail = 0; errs = []; blocked = set()
    targets = [g for g in d["groups"] if g["enabled"]]
    if not msg or not targets: errs.append("No message or no enabled groups")
    for g in targets if msg else []:
        cur = store.load()["broadcast"]
        if not cur["enabled"] or cur["paused"]: errs.append("Stopped/paused mid-cycle"); break
        if g["account"] in blocked: continue
        err = None; c = clients.get(g["account"])
        try:
            if not c or not c.is_connected(): raise RuntimeError("account not connected")
            await c.send_message(g["id"], msg); ok += 1
        except FloodWaitError as e:
            blocked.add(g["account"]); err = f"FloodWait {e.seconds}s from Telegram; account '{g['account']}' skipped for the rest of this cycle"
        except Exception as e: err = f"{type(e).__name__}: {e}"
        if err:
            fail += 1; errs.append(f"{g['title']}: {err}")
        def f(d, g=g, err=err):
            for x in d["groups"]:
                if x["id"] == g["id"] and x["account"] == g["account"]:
                    x["last_error"] = err or ""; x["last_sent"] = x.get("last_sent") if err else time.time()
            if err: store.event(d, "error", f"Broadcast to '{g['title']}' failed: {err}")
        store.mutate(f)
    def done(d):
        b = d["broadcast"]; now = time.time()
        b.update(last_run=now, last_status=f"{ok} sent, {fail} failed", last_error="; ".join(errs)[:500])
        if b["enabled"]: b["next_run"] = now + b["delay_seconds"]  # delay starts after the cycle finishes
        store.event(d, "info", f"Broadcast cycle: {ok} sent, {fail} failed")
    store.mutate(done)

async def broadcaster():
    """The only scheduler loop. Reads config from store.json every second, so edits apply without restart."""
    while True:
        await asyncio.sleep(1)
        try:
            b = store.load()["broadcast"]
            if b["enabled"] and not b["paused"] and time.time() >= (b["next_run"] or 0): await run_cycle()
        except asyncio.CancelledError: raise
        except Exception as e:
            store.log_event("error", f"Scheduler error: {type(e).__name__}: {e}"); await asyncio.sleep(5)