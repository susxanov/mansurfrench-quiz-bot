import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from config import settings


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"status": "ok"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        return


def start_health_server():
    server = ThreadingHTTPServer(("0.0.0.0", settings().port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="health").start()
