import httpx
from . import config, store

def _cfg():
    s = store.load()["settings"]; return s["ollama_url"].rstrip("/"), s["model"]
def _headers(): return {"Authorization": f"Bearer {config.OLLAMA_API_KEY}"} if config.OLLAMA_API_KEY else {}
def _err(e):
    if isinstance(e, httpx.HTTPStatusError):
        c = e.response.status_code
        if c == 401: return "Ollama rejected the credentials (401): check OLLAMA_API_KEY"
        if c == 404: return "Model not found (404): check the model name in settings"
        return f"Ollama HTTP {c}: {e.response.text[:150]}"
    if isinstance(e, httpx.ConnectError): return "Cannot connect to the Ollama URL"
    if isinstance(e, httpx.TimeoutException): return "Ollama request timed out"
    return f"{type(e).__name__}: {e}"

async def chat(system, history):
    url, model = _cfg()
    payload = {"model": model, "stream": False, "messages": [{"role": "system", "content": system}, *history]}
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"{url}/api/chat", json=payload, headers=_headers()); r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e: raise RuntimeError(_err(e)) from e

async def test(model_check=False):
    """Connection test (GET /api/tags); with model_check also runs a tiny chat on the configured model."""
    url, model = _cfg()
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{url}/api/tags", headers=_headers()); r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
    except Exception as e: return {"ok": False, "error": _err(e)}
    if not model_check: return {"ok": True, "message": f"Connected to {url}", "models": names[:30]}
    try:
        out = await chat("Reply with the single word OK.", [{"role": "user", "content": "ping"}])
        return {"ok": True, "message": f"Model '{model}' responded: {out[:60]}"}
    except RuntimeError as e: return {"ok": False, "error": str(e)}
