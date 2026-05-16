#!/usr/bin/env python3

from flask import (
    Flask,
    request,
    send_from_directory,
    render_template
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
from datetime import datetime

# =========================
# CONFIG
# =========================
UPLOAD_FOLDER = "shared"
PORT = 8000
BIN = "cloudflared"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

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

    except:
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
    except:
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
def start_cloudflare():

    global cloudflared_proc
    global public_url

    cmd = [
        f"./{BIN}",
        "tunnel",
        "--url",
        f"http://localhost:{PORT}",
        "--no-autoupdate"
    ]

    cloudflared_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    for line in cloudflared_proc.stdout:

        match = re.search(
            r"https://[-0-9a-zA-Z]+\.trycloudflare\.com",
            line
        )

        if match:

            public_url = match.group(0)

            success(f"Public URL: {public_url}")

            generate_qr(public_url)

            break


# =========================
# ZIP ALL FILES
# =========================
@app.route("/download-all")
def download_all():

    zip_name = "shared_files.zip"

    with zipfile.ZipFile(zip_name, "w") as zipf:

        for file in os.listdir(UPLOAD_FOLDER):

            path = os.path.join(UPLOAD_FOLDER, file)

            zipf.write(path, arcname=file)

    return send_from_directory(
        ".",
        zip_name,
        as_attachment=True
    )


# =========================
# HOME
# =========================
@app.route("/", methods=["GET", "POST"])
def home():

    if request.method == "POST":

        files = request.files.getlist("file")

        for f in files:

            if f.filename:

                path = os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    f.filename
                )

                f.save(path)

    files = []

    for file in os.listdir(UPLOAD_FOLDER):

        path = os.path.join(UPLOAD_FOLDER, file)

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

    return send_from_directory(
        UPLOAD_FOLDER,
        filename,
        as_attachment=True
    )


# =========================
# DELETE FILE
# =========================
@app.route("/delete/<filename>")
def delete(filename):

    path = os.path.join(
        UPLOAD_FOLDER,
        filename
    )

    if os.path.exists(path):
        os.remove(path)

    return home()


# =========================
# CLEANUP
# =========================
def cleanup(*args):

    global cloudflared_proc

    log("Stopping...")

    try:

        if cloudflared_proc:
            cloudflared_proc.kill()

    except:
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
