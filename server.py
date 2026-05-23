#!/usr/bin/env python3
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/webhook/transcript':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            try:
                payload = json.loads(body.decode())
                response = {
                    "status": "received",
                    "meeting": payload.get("meeting_title", "Unknown"),
                    "transcript_length": len(payload.get("transcript", "")),
                    "message": "Webhook received successfully"
                }

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

                print(f"Received: {payload.get('meeting_title', 'Unknown')}")
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    server = HTTPServer(('0.0.0.0', port), WebhookHandler)
    print(f"Server running on http://0.0.0.0:{port}")
    server.serve_forever()
