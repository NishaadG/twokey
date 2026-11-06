#!/usr/bin/env python3
"""Harborline's orders API: quotes a basket using the rules in pricing.json."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RULES = Path(__file__).with_name("pricing.json")


def quote(items: int) -> dict:
    rules = json.loads(RULES.read_text())
    subtotal = items * rules["unit_price"]
    discount = subtotal * rules["bulk_discount_percent"] / 100
    return {"items": items, "total": round(subtotal - discount, 2)}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/health":
            self.reply(200, {"status": "up"})
        elif url.path == "/quote":
            items = int(parse_qs(url.query).get("items", ["3"])[0])
            try:
                self.reply(200, quote(items))
            except Exception as error:
                self.log_error("quote failed: %r", error)
                self.reply(500, {"error": "quote failed"})
        else:
            self.reply(404, {"error": "not found"})

    def reply(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8099), Handler).serve_forever()
