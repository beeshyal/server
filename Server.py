import http.server
import socketserver
import socket
import subprocess
import threading
import time
import re
import os
import platform
import sys
import shutil

PORT = 8000
BIN = "cloudflared"

cloudflared_proc = None
public_url = None

def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except:
        return "127.0.0.1"
    finally:
        s.close()

def arch():
    m = platform.machine().lower()
    if m in ("aarch64", "arm64"):
        return "arm64"
    if m.startswith("arm"):
        return "arm"
    if m in ("x86_64", "amd64"):
        return "amd64"
    return None

def download_cloudflared():
    if os.path.exists(BIN):
        return

    a = arch()
    if not a:
        print("Error")
        sys.exit(1)

    if shutil.which("wget") is None:
        print("Error")
        sys.exit(1)

    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{a}"
    subprocess.run(["wget", "-q", "-O", BIN, url], check=True)
    subprocess.run(["chmod", "+x", BIN], check=True)

def start_cloudflare():
    global cloudflared_proc, public_url
    cloudflared_proc = subprocess.Popen(
        [f"./{BIN}", "tunnel", "--no-autoupdate", "--url", f"http://localhost:{PORT}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    for line in cloudflared_proc.stdout:
        m = re.search(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com", line)
        if m:
            public_url = m.group(0)
            print(f"Public URL: {public_url}")
            break

def run_server():
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Local URL:  http://{local_ip()}:{PORT}")
        httpd.serve_forever()

def cleanup():
    global cloudflared_proc
    if cloudflared_proc and cloudflared_proc.poll() is None:
        cloudflared_proc.terminate()
    if os.path.exists(BIN):
        os.remove(BIN)
    print("Stopped")

try:
    download_cloudflared()
    threading.Thread(target=start_cloudflare, daemon=True).start()
    run_server()
except KeyboardInterrupt:
    cleanup()
except Exception:
    print("Error")
    cleanup()