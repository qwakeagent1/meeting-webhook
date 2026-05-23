#!/usr/bin/env python3
"""Complete meeting transcript webhook with action item extraction + Monday task creation"""

import json
import os
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

MONDAY_TOKEN = os.environ.get("MONDAY_TOKEN", "")
MONDAY_BOARD_ID = "9431876463"


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/webhook/transcript':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            try:
                payload = json.loads(body.decode())
                meeting_title = payload.get("meeting_title", "Meeting")
                transcript = payload.get("transcript", "")

                # Extract action items (simple fallback)
                action_items = self.simple_extract(transcript)

                # Create Monday tasks
                created_count = 0
                for item in action_items:
                    if self.create_monday_task(item):
                        created_count += 1

                response = {
                    "status": "success",
                    "meeting": meeting_title,
                    "action_items_extracted": len(action_items),
                    "tasks_created": created_count,
                    "action_items": action_items
                }

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

                print(f"Meeting: {meeting_title} | Items: {len(action_items)} | Tasks: {created_count}")
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
                print(f"Error: {e}")
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

    def simple_extract(self, transcript):
        """Extract action items from transcript (fallback)"""
        items = []

        if not transcript or len(transcript) < 20:
            return items

        indicators = ["need to", "should", "will", "have to", "must"]
        sentences = transcript.split(". ")

        for sentence in sentences[:5]:
            sentence_lower = sentence.lower()
            if any(ind in sentence_lower for ind in indicators):
                title = sentence.strip()[:50]
                if len(title) > 10:
                    items.append({
                        "title": title,
                        "owner": "Sam",
                        "due": 3,
                        "priority": "medium"
                    })

        return items[:3]

    def create_monday_task(self, item):
        """Create task on Monday.com via API"""
        if not MONDAY_TOKEN:
            print("No Monday token set")
            return False

        title = item.get("title", "Action item").replace('"', '\\"')

        query = f'mutation {{ create_item(board_id: {MONDAY_BOARD_ID}, item_name: "{title}") {{ id }} }}'

        try:
            result = subprocess.run(
                ["curl", "-s",
                 "-H", f"Authorization: {MONDAY_TOKEN}",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({"query": query}),
                 "https://api.monday.com/v2"],
                capture_output=True,
                timeout=10
            )

            response = json.loads(result.stdout.decode())

            if response.get("data", {}).get("create_item"):
                print(f"  Created: {title}")
                return True
            else:
                print(f"  Failed: {response.get('errors', 'Unknown error')}")

        except Exception as e:
            print(f"  Exception: {e}")

        return False

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    server = HTTPServer(('0.0.0.0', port), WebhookHandler)
    print(f"Server running on port {port}")
    server.serve_forever()
