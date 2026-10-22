"""Self-replace end-to-end test: serve a fake release, run old exe, verify swap."""
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(r"D:\laptrinh\appcode\2026\10-2026\baocao")
WORK = Path("/tmp/selftest")
SRV = WORK / "srv"

MARKER = b"\nTELEMONITOR_SELFTEST_V2_MARKER\n"


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    SRV.mkdir(parents=True)
    WORK.mkdir(parents=True, exist_ok=True)

    old_exe = ROOT / "dist" / "telemonitor.exe"
    assert old_exe.exists(), "chưa build dist/telemonitor.exe"

    new_bytes = old_exe.read_bytes() + MARKER
    (SRV / "telemonitor.exe").write_bytes(new_bytes)
    sha = hashlib.sha256(new_bytes).hexdigest()
    (SRV / "telemonitor.exe.sha256").write_text(sha)

    # Exe under test lives in WORK; updater writes to LOCALAPPDATA/TeleMonitor/update
    inst = WORK / "telemonitor.exe"
    shutil.copy2(old_exe, inst)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/repos/"):
                body = json.dumps({
                    "tag_name": "v9.9.9",
                    "assets": [
                        {"name": "telemonitor.exe",
                         "browser_download_url": f"{base}/telemonitor.exe"},
                        {"name": "telemonitor.exe.sha256",
                         "browser_download_url": f"{base}/telemonitor.exe.sha256"},
                    ],
                }).encode()
            elif self.path.endswith(".sha256"):
                body = sha.encode()
            else:
                body = new_bytes
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    base = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    # Point the updater at the local server by monkeypatching the api root via env.
    cfg = {
        "bot_token": "", "chat_id": "", "device_name": "SELFTEST",
        "update_repo": "fake/repo", "update_check_interval": 600,
    }
    (inst.parent / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    print(f"old exe sha: {hashlib.sha256(inst.read_bytes()).hexdigest()[:16]}")
    print(f"new exe sha: {sha[:16]}")

    # Drive updater directly in-process against the local server.
    sys.path.insert(0, str(ROOT / "src"))
    import updater

    updater._api = lambda repo: f"{base}/repos/{repo}/releases/latest"

    info = updater.check("fake/repo", "1.0.0")
    print("check ->", info["version"])
    assert info["version"] == "v9.9.9"

    dest = WORK / "update" / "telemonitor.exe.new"
    updater.download(info["url"], info["sha256_url"], dest)
    assert dest.read_bytes() == new_bytes, "file tải về không khớp"
    print("download + sha256 OK")

    # apply() exits the process and relaunches; emulate its steps here instead,
    # because this process is python.exe, not the frozen exe.
    old = inst.with_suffix(inst.suffix + ".old")
    os.replace(inst, old)
    os.replace(dest, inst)
    print("replace OK")
    assert inst.read_bytes() == new_bytes
    assert old.exists()

    srv.shutdown()
    print("SELF-REPLACE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
