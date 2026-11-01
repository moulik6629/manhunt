# 🎯 HOSTEL MANHUNT: TACTICAL CAMPUS LOCKDOWN

An adrenaline-fueled, real-time multiplayer hunting web game designed for university & hostel campuses.

> **NO SAME WI-FI NEEDED!**  
> Players can be on **4G / 5G Mobile Data (Jio, Airtel, Vi)**, different hostel Wi-Fi routers, or anywhere on campus! The server automatically generates a secure public HTTPS link that anyone on the planet can join with one click.

---

## ⚡ Key Highlights & Features

- **Play on Any Mobile Network (4G / 5G / Any Wi-Fi)**:
  - Integrated Cloudflare Internet Tunnel gives you an instant, secure `https://xxxx.trycloudflare.com` link.
  - No router port forwarding, no account creation, no subscriptions required.
- **Infection / Manhunt Game Mode**: 
  - Starts with 1 or more designated **Hunters** while everyone else is a **Runner**.
  - As soon as a hunter catches a runner, the runner is infected and turns into a **Hunter**!
  - Hunters win if they eliminate all survivors before time expires; Runners win if at least one survivor survives until the clock reaches 00:00!
- **Anti-Dispute Catch Verification (PIN & QR Code)**:
  - Every runner gets a secret 4-digit **Kill PIN** and a high-contrast **QR Code** on their phone screen.
  - When physically tagged, the hunter enters the 4-digit code into their tactical numpad (or scans the QR code with their camera) to confirm the catch.
  - Eliminates "I tagged you!" vs "No you didn't!" arguments.
- **Satellite Radar Sweeps (Fog-of-War)**:
  - Runners stay stealthy and invisible to hunters on the map.
  - Every few minutes (e.g., every 3 mins), the server triggers a **Satellite Recon Sweep (Radar Pulse)** for 20 seconds!
  - During the pulse, runner GPS coordinates are pinged onto the hunters' tactical map, forcing runners to keep moving.
- **Indoor Sector Pings (No GPS Drift Worries)**:
  - In thick concrete hostel blocks where GPS satellite lock is weak indoors, players can tap quick sector buttons (*"Block A - 1st Floor"*, *"Hostel Mess"*, *"Terrace"*, *"Quad"*, etc.) to update their sector instantly.
- **Zero-Dependency Tactical Audio & Haptics**:
  - Uses the **Web Audio API** to generate procedural sound effects (radar sonar pings, countdown beeps, red alert sirens, heavy kill bass stings, victory fanfares) directly inside the browser. No external MP3 files to load!
  - Uses the **Vibration API** to pulse phones when caught or when a radar sweep begins.
- **Host Tactical Broadcasts**:
  - The match host can broadcast global announcements (*"Rain started - move inside Block B"*, *"Warden approaching Ground!"*).

---

## 🚀 How to Launch and Play (Step-by-Step)

### Step 1: Start the Game Server on Your Laptop
Simply double-click [`start.bat`](file:///c:/Users/MOULIK%20GORAI/Desktop/SAPIENTIA/campus-manhunt/start.bat) or run in terminal:

```bash
cd "campus-manhunt"
python run.py
```

### Step 2: Share the Link with Your Hostel Squad
The console will start the tunnel and print your live link:
```
====================================================================
  🎯 HOSTEL MANHUNT // TACTICAL CAMPUS LOCKDOWN SERVER
====================================================================
  🌐 WORLDWIDE / 4G / 5G MOBILE DATA LINK (ANY NETWORK):
     👉 https://xxxx-xxxx-xxxx.trycloudflare.com
  ------------------------------------------------------------------
     Share this exact link in your hostel WhatsApp group!
     Anyone can open it on Jio, Airtel, Vi, 4G, 5G, or any Wi-Fi.
====================================================================
```

### Step 3: Start the Hunt!
1. Paste that link into your hostel WhatsApp or Discord group.
2. Players tap the link from their phones anywhere across campus (on mobile data or Wi-Fi).
3. **Host**: Click **HOST MATCH**, customize game settings (duration, head start, radar interval), and initialize the lobby.
4. **Players**: Tap **JOIN HUNT**, enter the room code (e.g., `HUNT502`), pick a tactical avatar, and join.
5. In the lobby, the Host can tap player cards to assign starting Hunters, then tap **🚀 LAUNCH MANHUNT** to unleash the game!
