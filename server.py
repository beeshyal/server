import http.server
import socketserver
import socket

PORT = 8000

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't need to actually connect
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

Handler = http.server.SimpleHTTPRequestHandler

try:
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as ht>
        ip = get_local_ip()
        print("\n🚀 Server started!")
        print(f"📡 Local:   http://127.0.0.1:{PORT}")
        print(f"🌐 Network: http://{ip}:{PORT}")
        print("🛑 Press CTRL + C to stop the server\n")
        httpd.serve_forever()
except KeyboardInterrupt:
    print("\n🛑 Server stopped safely. Bye 👋")
except Exception as e:
    print(f"⚠️ Error: {e}")

