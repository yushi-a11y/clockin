#!/usr/bin/env python3
import http.server
import socketserver
import os

PORT = 8766
ROOT = "/Users/lixiaotian/.qoderwork/workspace/mrssl6h69qlreqcf"
os.chdir(ROOT)

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        super().do_GET()

with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
    print(f"Serving at http://127.0.0.1:{PORT}")
    httpd.handle_request()
