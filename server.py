#!/usr/bin/env python3
"""Meeting summary webhook with Claude AI extraction + Monday task creation

Accepts Zoom AI Companion Meeting Summary payloads via Zapier:
  meeting_title: string
  summary_text:  string (may contain multiple comma-joined sections)
  next_steps:    string (comma-joined list of action items from Zoom)

The combined text is sent to Claude for structured extraction, then each
returned action item is created as a Monday.com task.
"""

import json
import os
import re
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

def build_input_text(summary_text, next_steps):
    """Combine summary and next_steps into a single block for Claude."""
    parts = []
    if summary_text:
        parts.append("Meeting summary:")
        parts.append(summary_text.strip())
    if next_steps:
        parts.append("")
        parts.append("Next steps (from Zoom AI Companion):")
        parts.append(next_steps.strip())
    return "\n".join(parts).strip()

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/webhook/transcript':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            try:
                payload = json.loads(body.decode())
                meeting_title = payload.get("meeting_title", "Meeting")
                summary_text  = payload.get("summary_text", "") or ""
                next_steps    = payload.get("next_steps", "") or ""

                combined = build_input_text(summary_text, next_steps)

                action_items = self.extract_with_claude(combined, meeting_title)

                created_count = 0
                for item in action_items:
                    if self.create_monday_task(item):
                        created_count += 1

                response = {
                    "status": "success",
                    "meeting": meeting_title,
                    "input_chars": len(combined),
                    "action_items_extracted": len(action_items),
                    "tasks_created": created_count,
                    "action_items": action_items,
                }

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

                print(f"{meeting_title} | input={len(combined)} chars | {len(action_items)} items | {created_count} tasks")
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

    def extract_with_claude(self, text, meeting_title):
        """Extract action items using Claude API. Returns [] on any failure."""
        if not CLAUDE_API_KEY or not text or len(text) < 20:
            return []

        prompt = f"""Extract action items from this meeting summary.

Meeting: {meeting_title}

{text}

Return a JSON array of action items. Each item should have:
- title:    concise action (10-80 chars)
- owner:    person responsible (name or "Sam" if unclear)
- due:      estimated days to complete (1-30, or null)
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
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )

            if status == 200:
                response = json.loads(body)
                content = response.get("content", [{}])[0].get("text", "")
                if content:
                    match = re.search(r"\[[\s\S]*?\]", content, re.DOTALL)
                    if match:
                        items = json.loads(match.group())
                        print(f"  Claude extracted {len(items)} action items")
                        return items[:8]
            else:
                print(f"  Claude API HTTP {status}: {body[:200]}")
        except Exception as e:
            print(f"  Claude API failed: {e}")

        return []

    def create_monday_task(self, item):
        """Create task on Monday.com"""
        if not MONDAY_TOKEN:
            print("  Skip: MONDAY_TOKEN not set")
            return False

        title    = item.get("title", "Untitled task")[:100]
        owner    = item.get("owner", "Sam")
        priority = item.get("priority", "medium")

        query = """mutation ($board: ID!, $name: String!, $vals: JSON!) {
            create_item (board_id: $board, item_name: $name, column_values: $vals) { id }
        }"""

        column_values = json.dumps({
            "text":   owner,
            "status": {"label": priority.capitalize()},
        })

        try:
            status, body = _http_post_json(
                "https://api.monday.com/v2",
                headers={"Authorization": MONDAY_TOKEN},
                payload={
                    "query": query,
                    "variables": {
                        "board": MONDAY_BOARD_ID,
                        "name":  title,
                        "vals":  column_values,
                    },
                },
                timeout=10,
            )
            if status == 200 and "errors" not in body:
                print(f"  Created: {title}")
                return True
            print(f"  Monday error: {body[:200]}")
        except Exception as e:
            print(f"  Monday failed: {e}")
        return False

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    print(f"Server on port {port}")
    server.serve_forever()
