#!/usr/bin/env python3

from flask import (
    Flask,
    request,
    send_from_directory,
    render_template,
    redirect,
    url_for,
    abort
)

import os
import socket
import subprocess
import threading
import re
import qrcode
import platform
import shutil
import signal
import sys
import zipfile
import tempfile
from datetime import datetime
from werkzeug.utils import secure_filename

# =========================
# CONFIG
# =========================
UPLOAD_FOLDER = "shared"
PORT = 8000
BIN = "cloudflared"
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500 MB upload limit

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH  # FIX: Enforce upload size limit

cloudflared_proc = None
public_url = None


# =========================
# LOGGING
# =========================
def log(msg):
    print(f"[*] {msg}", flush=True)


def success(msg):
    print(f"[+] {msg}", flush=True)


def error(msg):
    print(f"[-] {msg}", flush=True)


# =========================
# LOCAL IP
# =========================
def local_ip():

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]

    except Exception:
        return "127.0.0.1"

    finally:
        s.close()


# =========================
# QR CODE
# =========================
def generate_qr(url):

    img = qrcode.make(url)

    img.save("share_qr.png")

    success("QR Code saved: share_qr.png")

    try:
        img.show()
    except Exception:
        pass


# =========================
# ARCHITECTURE
# =========================
def arch():

    a = platform.machine().lower()

    if a in ["x86_64", "amd64"]:
        return "amd64"

    if a in ["aarch64", "arm64"]:
        return "arm64"

    if "arm" in a:
        return "arm"

    return None


# =========================
# DOWNLOAD CLOUDFLARED
# =========================
def download_cloudflared():

    if os.path.exists(BIN):
        return

    a = arch()

    if not a:
        error("Unsupported architecture")
        sys.exit(1)

    url = (
        "https://github.com/cloudflare/cloudflared/"
        f"releases/latest/download/cloudflared-linux-{a}"
    )

    log(f"Downloading cloudflared ({a})")

    if shutil.which("wget"):

        subprocess.run([
            "wget",
            "-O",
            BIN,
            url
        ], check=True)

    elif shutil.which("curl"):

        subprocess.run([
            "curl",
            "-L",
            url,
            "-o",
            BIN
        ], check=True)

    else:
        error("wget or curl required")
        sys.exit(1)

    os.chmod(BIN, 0o755)

    success("cloudflared downloaded")


# =========================
# CLOUDFLARE TUNNEL
# =========================
TUNNEL_URL_PATTERN = re.compile(
    r"https://[-0-9a-zA-Z]+\.trycloudflare\.com"
)
TUNNEL_TIMEOUT   = 60   # seconds to wait for URL per attempt
TUNNEL_MAX_RETRY = 5    # maximum restart attempts
TUNNEL_RETRY_DELAY = 5  # seconds between retries


def _run_tunnel_once():
    """
    Start cloudflared once, wait up to TUNNEL_TIMEOUT seconds for the
    public URL to appear in output, then return it (or None on failure).
    Also monitors the process after URL is found and returns when it dies.
    """
    global cloudflared_proc, public_url

    import time

    cmd = [
        f"./{BIN}",
        "tunnel",
        "--url",
        f"http://localhost:{PORT}",
        "--no-autoupdate"
    ]

    log("Starting cloudflared tunnel...")

    cloudflared_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    found_url = None
    start_time = time.time()

    # --- Phase 1: wait for URL in output ---
    for line in cloudflared_proc.stdout:

        line = line.strip()

        # Debug: uncomment to see raw cloudflared output
        # print(f"[DEBUG cloudflared] {line}", flush=True)

        if time.time() - start_time > TUNNEL_TIMEOUT:
            error("Timed out waiting for cloudflared public URL")
            cloudflared_proc.kill()
            return None

        match = TUNNEL_URL_PATTERN.search(line)

        if match:
            found_url = match.group(0)
            public_url = found_url
            success(f"Public URL: {public_url}")
            generate_qr(public_url)
            break

    if not found_url:
        # Process ended before URL was found
        error("cloudflared exited before producing a public URL")
        return None

    # --- Phase 2: keep reading until process dies (detect crashes) ---
    for line in cloudflared_proc.stdout:
        pass  # drain stdout so the process doesn't block

    cloudflared_proc.wait()
    exit_code = cloudflared_proc.returncode
    error(f"cloudflared tunnel died (exit code {exit_code})")

    # Clear stale URL so the UI shows tunnel is down
    public_url = None
    cloudflared_proc = None

    return found_url  # return the URL we had (used to log which tunnel died)


def start_cloudflare():
    """
    Wrapper that retries the tunnel up to TUNNEL_MAX_RETRY times
    with a delay between each attempt.
    """
    import time

    for attempt in range(1, TUNNEL_MAX_RETRY + 1):

        log(f"Tunnel attempt {attempt}/{TUNNEL_MAX_RETRY}")

        result = _run_tunnel_once()

        if attempt < TUNNEL_MAX_RETRY:
            log(f"Retrying in {TUNNEL_RETRY_DELAY}s...")
            time.sleep(TUNNEL_RETRY_DELAY)

    error(f"Cloudflare tunnel failed after {TUNNEL_MAX_RETRY} attempts. "
          f"Only local access available.")


# =========================
# ZIP ALL FILES
# =========================
@app.route("/download-all")
def download_all():

    # FIX: Write zip to a temp file instead of current working directory
    tmp = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".zip",
        prefix="shared_files_"
    )
    zip_path = tmp.name
    tmp.close()

    try:
        with zipfile.ZipFile(zip_path, "w") as zipf:
            for file in os.listdir(UPLOAD_FOLDER):
                path = os.path.join(UPLOAD_FOLDER, file)
                if os.path.isfile(path):  # FIX: Skip subdirectories if any
                    zipf.write(path, arcname=file)

        return send_from_directory(
            os.path.dirname(zip_path),
            os.path.basename(zip_path),
            as_attachment=True,
            download_name="shared_files.zip"
        )
    except Exception as e:
        error(f"Failed to create zip: {e}")
        abort(500)


# =========================
# HOME
# =========================
@app.route("/", methods=["GET", "POST"])
def home():

    if request.method == "POST":

        files = request.files.getlist("file")

        for f in files:

            if f.filename:

                # FIX: Sanitize filename to prevent path traversal
                safe_name = secure_filename(f.filename)

                if not safe_name:
                    continue

                dest = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)

                # FIX: Avoid silent overwrite — append timestamp if file exists
                if os.path.exists(dest):
                    name, ext = os.path.splitext(safe_name)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_name = f"{name}_{timestamp}{ext}"
                    dest = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)

                f.save(dest)

        # FIX: Redirect after POST to follow PRG pattern (prevents re-upload on refresh)
        return redirect(url_for("home"))

    files = []

    for file in os.listdir(UPLOAD_FOLDER):

        path = os.path.join(UPLOAD_FOLDER, file)

        if not os.path.isfile(path):
            continue

        size = round(os.path.getsize(path) / 1024, 2)

        files.append({
            "name": file,
            "size": size,
            "time": datetime.fromtimestamp(
                os.path.getmtime(path)
            ).strftime("%Y-%m-%d %H:%M")
        })

    return render_template(
        "index.html",
        files=files,
        public_url=public_url
    )


# =========================
# DOWNLOAD FILE
# =========================
@app.route("/download/<filename>")
def download(filename):

    # FIX: Sanitize filename to prevent path traversal attack
    safe_name = secure_filename(filename)

    if not safe_name:
        abort(400)

    return send_from_directory(
        UPLOAD_FOLDER,
        safe_name,
        as_attachment=True
    )


# =========================
# DELETE FILE
# =========================
# FIX: Changed to POST method to prevent accidental deletion by browsers/crawlers
@app.route("/delete/<filename>", methods=["POST"])
def delete(filename):

    # FIX: Sanitize filename to prevent path traversal attack
    safe_name = secure_filename(filename)

    if not safe_name:
        abort(400)

    path = os.path.join(UPLOAD_FOLDER, safe_name)

    if os.path.exists(path):
        os.remove(path)

    # FIX: Use redirect instead of calling home() directly
    return redirect(url_for("home"))


# =========================
# CLEANUP
# =========================
def cleanup(*args):

    global cloudflared_proc

    log("Stopping...")

    try:

        if cloudflared_proc:
            cloudflared_proc.kill()

    except Exception:
        pass

    success("Stopped")

    sys.exit(0)


# =========================
# MAIN
# =========================
if __name__ == "__main__":

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    download_cloudflared()

    threading.Thread(
        target=start_cloudflare,
        daemon=True
    ).start()

    success(
        f"Local URL: "
        f"http://{local_ip()}:{PORT}"
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True
    )
