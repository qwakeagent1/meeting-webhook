#!/usr/bin/env python3
"""Meeting transcript webhook with Claude AI extraction + Monday task creation"""

import json
import os
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

MONDAY_TOKEN = os.environ.get("MONDAY_TOKEN", "")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
MONDAY_BOARD_ID = "9431876463"


def _http_post_json(url, headers, payload, timeout):
    """POST JSON via stdlib urllib. Returns (status_code, response_text)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, body


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/webhook/transcript':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            try:
                payload = json.loads(body.decode())
                meeting_title = payload.get("meeting_title", "Meeting")
                transcript = payload.get("transcript", "")

                # Extract action items with Claude
                action_items = self.extract_with_claude(transcript, meeting_title)

                # Fallback if Claude fails
                if not action_items:
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

                print(f"{meeting_title} | {len(action_items)} items | {created_count} tasks")
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

    def extract_with_claude(self, transcript, meeting_title):
        """Extract action items using Claude API"""
        if not CLAUDE_API_KEY or not transcript or len(transcript) < 50:
            return []

        prompt = f"""Extract action items from this meeting transcript.
Meeting: {meeting_title}
Transcript: {transcript}
Return a JSON array of action items. Each item should have:
- title: concise action (10-50 chars)
- owner: person responsible (name or "Sam" if unclear)
- due: estimated days to complete (1-30, or null)
- priority: "high", "medium", or "low"
Example format:
[
  {{"title": "Finalize deck", "owner": "Sam", "due": 2, "priority": "high"}},
  {{"title": "Get budget approval", "owner": "Mary", "due": 1, "priority": "high"}}
]
Return ONLY valid JSON array, no markdown or explanation."""

        try:
            status, body = _http_post_json(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": CLAUDE_API_KEY,
                    "anthropic-version": "2023-06-01",
                },
                payload={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=15,
            )

            if status == 200:
                response = json.loads(body)
                content = response.get("content", [{}])[0].get("text", "")
                if content:
                    import re
                    match = re.search(r'\[.*\]', content, re.DOTALL)
                    if match:
                        items = json.loads(match.group())
                        print(f"  Claude extracted {len(items)} action items")
                        return items[:5]
            else:
                print(f"  Claude API HTTP {status}: {body[:200]}")
        except Exception as e:
            print(f"  Claude API failed: {e}")

        return []

    def simple_extract(self, transcript):
        """Fallback: simple keyword extraction"""
        items = []

        if not transcript or len(transcript) < 20:
            return items

        indicators = ["need to", "should", "will", "have to", "must", "need"]
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
        """Create task on Monday.com"""
        if not MONDAY_TOKEN:
            print("    Skip: MONDAY_TOKEN not set")
            return False

        title = item.get("title", "Action item").replace('"', '\\"')
        query = f'mutation {{ create_item(board_id: {MONDAY_BOARD_ID}, item_name: "{title}") {{ id }} }}'

        try:
            status, body = _http_post_json(
                "https://api.monday.com/v2",
                headers={"Authorization": MONDAY_TOKEN},
                payload={"query": query},
                timeout=10,
            )

            if status == 200:
                response = json.loads(body)
                if response.get("data", {}).get("create_item"):
                    print(f"    Created: {title}")
                    return True
                print(f"    Monday returned no item. Body: {body[:200]}")
            else:
                print(f"    Monday HTTP {status}: {body[:200]}")
        except Exception as e:
            print(f"    Error: {e}")

        return False

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    server = HTTPServer(('0.0.0.0', port), WebhookHandler)
    print(f"Server on port {port}")
    server.serve_forever()
