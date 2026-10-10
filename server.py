"""Awaaz server: static files + Ollama proxy (/api/chat) + Urdu voice (/api/tts) + /api/health.
Run: python server.py   then open http://localhost:8000"""
import asyncio, hashlib, io, json, os, urllib.request, urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
CACHE, VOICE = "audio_cache", "ur-PK-UzmaNeural"


def edge(text):
    import edge_tts
    async def run():
        out = b""
        async for ch in edge_tts.Communicate(text, VOICE).stream():
            if ch["type"] == "audio":
                out += ch["data"]
        return out
    return asyncio.run(run())


def gtts(text):
    from gtts import gTTS
    buf = io.BytesIO()
    gTTS(text, lang="ur").write_to_fp(buf)
    return buf.getvalue()


def tts(text):
    path = os.path.join(CACHE, hashlib.sha1(text.encode()).hexdigest() + ".mp3")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    for fn in (edge, gtts):  # online engines; result is cached so it works offline next time
        try:
            data = fn(text)
            if data:
                os.makedirs(CACHE, exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)
                return data
        except Exception:
            pass
    return None


def engine():
    for mod, name in (("edge_tts", "edge-tts"), ("gtts", "gTTS")):
        try:
            __import__(mod)
            return name
        except ImportError:
            pass
    return "browser only"


class H(SimpleHTTPRequestHandler):
    def reply(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/tts":
            text = urllib.parse.parse_qs(u.query).get("text", [""])[0].strip()
            data = tts(text) if text else None
            return self.reply(200, data, "audio/mpeg") if data else self.reply(503, b"{}")
        if u.path == "/api/health":
            info = {"ollama": False, "models": [], "tts": engine()}
            try:
                with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=2) as r:
                    info["ollama"] = True
                    info["models"] = [m["name"] for m in json.load(r).get("models", [])]
            except Exception:
                pass
            return self.reply(200, json.dumps(info).encode())
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/chat":
            return self.reply(404, b"{}")
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            req = urllib.request.Request(OLLAMA + "/api/chat", body, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                self.reply(200, r.read())
        except Exception as e:
            self.reply(502, json.dumps({"error": str(e)}).encode())


if __name__ == "__main__":
    print("Open http://localhost:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), H).serve_forever()
