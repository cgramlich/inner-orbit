"""Tiny static dev server with permissive CORS (local development only).
Lets a cross-origin page (e.g. the sandbox preview) fetch these files for a
JSX compile-check, and serves the PWA for manual viewing. Not for production.
"""
import http.server, socketserver, sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8300


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"orbit dev server on http://localhost:{PORT}")
    httpd.serve_forever()
