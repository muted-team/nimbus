# -*- coding: utf-8 -*-
"""Raw uploads return promptly and preserve the HTTP keep-alive stream.

Synthetic files, a temporary directory and a real loopback HTTP server only;
no remote service, credentials, account data or TikTok requests are involved.
Run directly: Run the corresponding check in tests/.
"""
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from http.server import ThreadingHTTPServer  # noqa: E402
from PIL import Image  # noqa: E402

import main  # noqa: E402


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="slots-upload-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name) / "Синтетические фото"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.connection = http.client.HTTPConnection(
            "127.0.0.1", self.httpd.server_port, timeout=2)
        self.addCleanup(self.connection.close)

    def close_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())

    def test_photo_upload_replies_and_next_request_uses_same_socket(self):
        source = io.BytesIO()
        Image.new("RGB", (64, 48), (50, 95, 150)).save(source, "JPEG")
        payload = source.getvalue()
        filename = "синтетическое фото.jpg"
        query = urllib.parse.urlencode({"folder": str(self.folder), "name": filename})
        self.connection.connect()
        original_socket = self.connection.sock
        self.connection.request("POST", "/api/slots/upload?" + query,
                                body=payload, headers={"Content-Type": "image/jpeg"})
        response = self.connection.getresponse()
        result = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertTrue(result["ok"])
        self.assertEqual(result["name"], filename)
        self.assertEqual(result["photos"], 1)
        self.assertEqual(result["videos"], 0)
        self.assertEqual((self.folder / filename).read_bytes(), payload)
        self.assertFalse(any(self.folder.glob("*.part")))
        self.assertIs(self.connection.sock, original_socket)
        # A JSON request immediately after the raw upload must stay synchronized.
        self.connection.request("POST", "/api/slots",
                                body=json.dumps({"folders": [str(self.folder)]}),
                                headers={"Content-Type": "application/json"})
        response = self.connection.getresponse()
        result = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(result["items"][0]["photos"], 1)
        self.assertIs(self.connection.sock, original_socket)


if __name__ == "__main__":
    unittest.main()
