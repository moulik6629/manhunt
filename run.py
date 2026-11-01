import socket
import sys
import os
import re
import time
import subprocess
import threading
import uvicorn

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLOUDFLARED_BIN = os.path.join(BASE_DIR, "bin", "cloudflared.exe")

def get_local_ip():
    """Detect LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def start_cloudflare_tunnel(port=8000):
    """Launch Cloudflare Quick Tunnel to get a free, secure public HTTPS URL for 4G/5G mobile data play."""
    if not os.path.exists(CLOUDFLARED_BIN):
        return None, None

    cmd = [CLOUDFLARED_BIN, "tunnel", "--url", f"http://127.0.0.1:{port}"]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
    except Exception as e:
        print(f"[-] Could not start cloudflared: {e}")
        return None, None

    public_url = None
    start_time = time.time()
    
    # Read stderr lines until trycloudflare.com URL appears
    while time.time() - start_time < 15:
        line = proc.stderr.readline()
        if not line:
            time.sleep(0.1)
            continue
        match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
        if match:
            public_url = match.group(0)
            break

    return proc, public_url

def print_banner(local_ip, port, public_url):
    print("=" * 68)
    print("  🎯 HOSTEL MANHUNT // TACTICAL CAMPUS LOCKDOWN SERVER")
    print("=" * 68)
    if public_url:
        print("  🌐 WORLDWIDE / 4G / 5G MOBILE DATA LINK (ANY NETWORK):")
        print(f"     👉 {public_url}")
        print("  " + "-" * 66)
        print("     Share this exact link in your hostel WhatsApp group!")
        print("     Anyone can open it on Jio, Airtel, Vi, 4G, 5G, or any Wi-Fi.")
    else:
        print(f"  [+] Local Wi-Fi: http://{local_ip}:{port}")
        
    print("  " + "-" * 66)
    print(f"  💻 Localhost (Laptop):  http://localhost:{port}")
    print("=" * 68)
    print("  Press Ctrl+C anytime to stop the server.\n")

if __name__ == "__main__":
    port = 8000
    local_ip = get_local_ip()
    
    print("[*] Starting secure Cloudflare Internet Tunnel (for mobile data / cross-network play)...")
    tunnel_proc, public_url = start_cloudflare_tunnel(port)
    
    if public_url:
        os.environ["PUBLIC_URL"] = public_url
    else:
        print("[-] Could not establish public tunnel. Falling back to LAN mode.")

    print_banner(local_ip, port, public_url)

    try:
        # Run uvicorn server
        sys.path.insert(0, BASE_DIR)
        uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
    finally:
        if tunnel_proc:
            tunnel_proc.terminate()
            tunnel_proc.wait()
