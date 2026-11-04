"""One USB transaction scenario; synthetic credentials, no serial hardware."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import provision_device


class SerialFlow:
    def __init__(self, final):
        self.writes = []
        self.pending = []
        self.replies = [
            [{"type": "network", "status": "status", "configured": False}],
            [{"schema": 1, "type": "sample", "client_state": 0,
              "last_command": "radar_disabled_high_z"}],
            [{"type": "network", "status": "configuring"}, final],
        ]

    def write(self, value):
        if self.pending:
            raise AssertionError("Next command was sent before acknowledgement.")
        self.writes.append(value)
        self.pending = [json.dumps(row).encode() + b"\n"
                        for row in self.replies[len(self.writes) - 1]]
        return len(value)

    def readline(self, _limit):
        return self.pending.pop(0) if self.pending else b""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


class ProvisionFlowTest(unittest.TestCase):
    def test_confirmed_write_and_rejection_hide_secrets(self):
        token = "t" * 43
        password = "synthetic-private-password"
        config = {
            "device_id": "4b9635de-4522-4fd1-8a6b-5eb3e4adba53",
            "binding_id": None, "endpoint": "https://example.test/api/device/v1/telemetry",
            "token": token, "wifi_ssid": "测试网络", "wifi_password": password,
            "ntp_server": "pool.ntp.org",
        }
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "device.json"
            private.write_text(json.dumps(config), encoding="utf-8")
            private.chmod(0o600)
            ca = Path(temporary) / "ca.pem"
            ca.write_text("-----BEGIN CERTIFICATE-----\nsynthetic\n-----END CERTIFICATE-----\n")
            for accepted in (True, False):
                with self.subTest(accepted=accepted):
                    final = {"type": "network", "status": "configured", "restarting": True} if accepted else {
                        "type": "network", "status": "config_error", "reason": token + password}
                    stream = SerialFlow(final)
                    serial = SimpleNamespace(Serial=lambda *_args, **_kwargs: stream, SerialException=OSError)
                    output = io.StringIO()
                    with patch.dict(sys.modules, {"serial": serial}), \
                            contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                        result = provision_device.main(["--port", "synthetic-port", "--config", str(private),
                                                        "--ca", str(ca), "--new-identity"])
                    self.assertEqual(result, 0 if accepted else 1)
                    self.assertEqual(stream.writes[:2], [b"net status\n", b"radar off\n"])
                    self.assertEqual(len(stream.writes), 3)
                    self.assertTrue(stream.writes[2].isascii())
                    payload = json.loads(stream.writes[2].removeprefix(b"net configure "))
                    self.assertEqual(payload["wifi_ssid"], config["wifi_ssid"])
                    self.assertIs(payload["new_identity"], True)
                    self.assertNotIn(token, output.getvalue())
                    self.assertNotIn(password, output.getvalue())
                    self.assertEqual("Firmware confirmed" in output.getvalue(), accepted)


if __name__ == "__main__":
    unittest.main()
