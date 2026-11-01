import asyncio
import json
import math
import os
import random
import time
import socket
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Hostel Manhunt - Tactical Campus Lockdown")

# Serve static files
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two GPS coordinates."""
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# Models & State
class Player:
    def __init__(self, player_id: str, name: str, avatar: str = "🎯", sector: str = "Campus Grounds"):
        self.id = player_id
        self.name = name
        self.avatar = avatar
        self.sector = sector
        self.role: str = "RUNNER"  # "RUNNER", "HUNTER", "SPECTATOR"
        self.is_original_hunter: bool = False
        self.pin: str = f"{random.randint(1000, 9999)}"  # Secret 4-digit elimination PIN
        self.is_alive: bool = True
        self.tagged_by: Optional[str] = None
        self.tagged_at: Optional[float] = None
        self.kills_count: int = 0
        self.lat: Optional[float] = None
        self.lng: Optional[float] = None
        self.last_pos_time: float = 0.0
        self.is_outside_zone: bool = False
        self.distance_to_center: float = 0.0
        self.is_connected: bool = True
        self.disconnect_time: Optional[float] = None
        self.pending_claim: Optional[dict] = None
        self.last_claim_time: float = 0.0
        self.ws: Optional[WebSocket] = None

    def to_dict(self, viewer_role: str = "RUNNER", is_self: bool = False, pulse_active: bool = False):
        """
        Filters data based on viewer perspective for tactical fog-of-war.
        """
        data = {
            "id": self.id,
            "name": self.name,
            "avatar": self.avatar,
            "sector": self.sector,
            "role": self.role,
            "is_alive": self.is_alive,
            "kills_count": self.kills_count,
            "tagged_by": self.tagged_by,
            "tagged_at": self.tagged_at,
            "is_outside_zone": self.is_outside_zone,
            "distance_to_center": round(self.distance_to_center, 1),
            "is_connected": self.is_connected,
            "pending_claim": self.pending_claim
        }

        # PIN is ONLY visible to the player themself
        if is_self and self.role == "RUNNER":
            data["pin"] = self.pin

        # Geolocation visibility rules:
        # 1. Player always sees their own location
        # 2. Hunters always see fellow hunters
        # 3. Runners always see fellow runners (optional radar sharing)
        # 4. Hunters only see runners during an active RADAR PULSE
        # 5. Out-of-zone runners are exposed to Hunters!
        can_see_location = False
        if is_self:
            can_see_location = True
        elif self.role == "HUNTER" and viewer_role == "HUNTER":
            can_see_location = True
        elif self.role == "RUNNER" and viewer_role == "RUNNER":
            can_see_location = True
        elif self.role == "RUNNER" and viewer_role == "HUNTER" and (pulse_active or self.is_outside_zone):
            can_see_location = True

        if can_see_location and self.lat is not None and self.lng is not None:
            data["lat"] = self.lat
            data["lng"] = self.lng
            data["last_pos_time"] = self.last_pos_time
        else:
            data["lat"] = None
            data["lng"] = None

        return data

class Room:
    def __init__(self, code: str, name: str, host_id: str):
        self.code = code
        self.name = name
        self.host_id = host_id
        self.status = "LOBBY"  # LOBBY, HEAD_START, ACTIVE, PAUSED, ENDED
        self.game_mode = "infection"
        self.duration_seconds = 1800  # 30 mins default
        self.head_start_seconds = 90  # 1.5 mins head start
        self.radar_interval_seconds = 180  # pulse every 3 mins
        self.radar_duration_seconds = 20  # pulse lasts 20s
        self.initial_hunter_count = 1
        
        self.start_time: Optional[float] = None
        self.head_start_end_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.time_remaining: int = 1800
        
        self.radar_pulse_active: bool = False
        self.radar_pulse_expires_at: float = 0.0
        self.next_radar_pulse_at: float = 0.0
        
        self.players: Dict[str, Player] = {}
        self.kill_log: List[dict] = []
        self.safe_zones: List[dict] = [
            {"id": "sz1", "name": "Hostel Canteen / Mess", "sector": "Mess Hall", "lat": None, "lng": None, "radius": 25},
            {"id": "sz2", "name": "Warden Office / Guard Post", "sector": "Main Gate", "lat": None, "lng": None, "radius": 20}
        ]
        # Shrinking Playzone Settings
        self.zone_shrink_enabled: bool = True
        self.zone_center_lat: Optional[float] = None
        self.zone_center_lng: Optional[float] = None
        self.zone_initial_radius: float = 350.0  # meters
        self.zone_min_radius: float = 40.0       # meters final circle
        self.zone_current_radius: float = 350.0  # current shrinking radius
        self.last_shrink_stage: int = 0
        self.disputes: List[dict] = []

        self.winner: Optional[str] = None
        self.lock = asyncio.Lock()

    def get_runners_count(self) -> int:
        return sum(1 for p in self.players.values() if p.role == "RUNNER" and p.is_alive)

    def get_hunters_count(self) -> int:
        return sum(1 for p in self.players.values() if p.role == "HUNTER")

rooms: Dict[str, Room] = {}

def get_local_ip() -> str:
    """Find the local machine IP on hostel Wi-Fi/LAN."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# ----------------- Broadcast Helpers -----------------

async def broadcast_room_state(room: Room, event_type: str = "STATE_UPDATE", extra: dict = None):
    """Send personalized tactical state to each connected player in the room."""
    now = time.time()
    
    # Calculate timers
    headstart_remaining = 0
    if room.status == "HEAD_START" and room.head_start_end_time:
        headstart_remaining = max(0, int(room.head_start_end_time - now))
        
    game_remaining = 0
    if room.status in ["ACTIVE", "HEAD_START"] and room.end_time:
        game_remaining = max(0, int(room.end_time - now))
        
    radar_pulse_remaining = 0
    if room.radar_pulse_active and room.radar_pulse_expires_at:
        radar_pulse_remaining = max(0, int(room.radar_pulse_expires_at - now))
        
    next_radar_in = 0
    if room.status == "ACTIVE" and room.next_radar_pulse_at:
        next_radar_in = max(0, int(room.next_radar_pulse_at - now))

    for pid, player in list(room.players.items()):
        if not player.ws:
            continue
        try:
            # Build tactical view filtered for this player
            players_list = [
                p.to_dict(viewer_role=player.role, is_self=(p.id == player.id), pulse_active=room.radar_pulse_active)
                for p in room.players.values()
            ]

            payload = {
                "type": event_type,
                "room": {
                    "code": room.code,
                    "name": room.name,
                    "host_id": room.host_id,
                    "status": room.status,
                    "duration_seconds": room.duration_seconds,
                    "head_start_seconds": room.head_start_seconds,
                    "radar_interval_seconds": room.radar_interval_seconds,
                    "headstart_remaining": headstart_remaining,
                    "game_remaining": game_remaining,
                    "radar_pulse_active": room.radar_pulse_active,
                    "radar_pulse_remaining": radar_pulse_remaining,
                    "next_radar_in": next_radar_in,
                    "runners_count": room.get_runners_count(),
                    "hunters_count": room.get_hunters_count(),
                    "winner": room.winner,
                    "safe_zones": room.safe_zones,
                    "playzone": {
                        "enabled": room.zone_shrink_enabled,
                        "center_lat": room.zone_center_lat,
                        "center_lng": room.zone_center_lng,
                        "current_radius": round(room.zone_current_radius, 1),
                        "initial_radius": room.zone_initial_radius,
                        "min_radius": room.zone_min_radius
                    },
                    "disputes": [d for d in room.disputes if d.get("status") != "RESOLVED"]
                },
                "self": player.to_dict(viewer_role=player.role, is_self=True, pulse_active=room.radar_pulse_active),
                "players": players_list,
                "kill_log": room.kill_log[-20:],  # last 20 events
            }
            if extra:
                payload["event_data"] = extra

            await player.ws.send_text(json.dumps(payload))
        except Exception:
            # Stale connection handled in disconnect
            pass

# ----------------- Game Background Ticker -----------------

async def game_ticker():
    """Asynchronous background loop managing game rules, timers, and radar sweeps."""
    while True:
        try:
            now = time.time()
            for room_code, room in list(rooms.items()):
                async with room.lock:
                    if room.status == "HEAD_START":
                        if room.head_start_end_time and now >= room.head_start_end_time:
                            # Head start over -> unleash hunters!
                            room.status = "ACTIVE"
                            room.next_radar_pulse_at = now + room.radar_interval_seconds
                            room.kill_log.append({
                                "time": time.strftime("%H:%M:%S"),
                                "type": "ALERT",
                                "message": "🚨 HEAD START OVER! HUNTERS HAVE BEEN UNLEASHED!"
                            })
                            await broadcast_room_state(room, "HUNTERS_RELEASED")

                    elif room.status == "ACTIVE":
                        # Check Game Timer Expiration
                        if room.end_time and now >= room.end_time:
                            room.status = "ENDED"
                            remaining_runners = room.get_runners_count()
                            if remaining_runners > 0:
                                room.winner = "RUNNERS"
                                room.kill_log.append({
                                    "time": time.strftime("%H:%M:%S"),
                                    "type": "VICTORY",
                                    "message": f"🏆 SURVIVORS WIN! {remaining_runners} runner(s) survived the hunt!"
                                })
                            else:
                                room.winner = "HUNTERS"
                                room.kill_log.append({
                                    "time": time.strftime("%H:%M:%S"),
                                    "type": "VICTORY",
                                    "message": "💀 HUNTERS WIN! All targets on campus were eliminated!"
                                })
                            await broadcast_room_state(room, "GAME_OVER")

                        # Manage Shrinking Playzone
                        if room.zone_shrink_enabled and room.zone_center_lat and room.zone_center_lng:
                            active_start = room.head_start_end_time or room.start_time or now
                            total_active = max(60, room.duration_seconds)
                            elapsed = max(0, now - active_start)
                            progress = min(1.0, elapsed / total_active)

                            # Smooth shrinkage
                            new_radius = room.zone_initial_radius - (room.zone_initial_radius - room.zone_min_radius) * progress
                            room.zone_current_radius = max(room.zone_min_radius, new_radius)

                            # Milestone announcement (every 25% shrinkage)
                            stage = int(progress * 4)
                            if stage > room.last_shrink_stage and stage <= 3:
                                room.last_shrink_stage = stage
                                room.kill_log.append({
                                    "time": time.strftime("%H:%M:%S"),
                                    "type": "ALERT",
                                    "message": f"⚠️ ZONE CONSTRICTING! Radius shrunk to {int(room.zone_current_radius)}m! Fall back to playzone!"
                                })
                                await broadcast_room_state(room, "ZONE_SHRUNK")

                            # Check players distance to zone center
                            for p in room.players.values():
                                if p.role == "RUNNER" and p.is_alive and p.lat and p.lng:
                                    dist = haversine_distance(p.lat, p.lng, room.zone_center_lat, room.zone_center_lng)
                                    p.distance_to_center = dist
                                    was_outside = p.is_outside_zone
                                    p.is_outside_zone = dist > room.zone_current_radius
                                    if not was_outside and p.is_outside_zone:
                                        room.kill_log.append({
                                            "time": time.strftime("%H:%M:%S"),
                                            "type": "ALERT",
                                            "message": f"🚨 {p.name} IS OUTSIDE THE PLAYZONE! Location exposed to Hunters!"
                                        })
                                        await broadcast_room_state(room, "RUNNER_OUT_OF_BOUNDS", {"runner_name": p.name})

                        # Anti-Cheat: Check Runner Pending Claims (Auto-Confirm if timer expires)
                        for p in list(room.players.values()):
                            if p.role == "RUNNER" and p.is_alive and p.pending_claim:
                                if now >= p.pending_claim.get("expires_at", 0):
                                    hunter_id = p.pending_claim.get("hunter_id")
                                    hunter_name = p.pending_claim.get("hunter_name", "Hunter")
                                    p.pending_claim = None
                                    p.role = "HUNTER"
                                    p.tagged_by = hunter_name
                                    p.tagged_at = now
                                    hunter_p = room.players.get(hunter_id)
                                    if hunter_p:
                                        hunter_p.kills_count += 1

                                    room.kill_log.append({
                                        "time": time.strftime("%H:%M:%S"),
                                        "type": "TAG",
                                        "message": f"⚖️ {hunter_name}'s tag on {p.name} AUTO-CONFIRMED (timer expired)!"
                                    })
                                    alive_runners = room.get_runners_count()
                                    if alive_runners == 0:
                                        room.status = "ENDED"
                                        room.winner = "HUNTERS"
                                        await broadcast_room_state(room, "GAME_OVER")
                                    else:
                                        await broadcast_room_state(room, "PLAYER_TAGGED", {"runner_name": p.name, "hunter_name": hunter_name})

                            # Check Disconnect / Offline timeout
                            if p.role == "RUNNER" and p.is_alive and not p.is_connected and p.disconnect_time:
                                if now - p.disconnect_time > 90:
                                    p.role = "HUNTER"
                                    p.tagged_by = "Offline Forfeiture"
                                    p.tagged_at = now
                                    room.kill_log.append({
                                        "time": time.strftime("%H:%M:%S"),
                                        "type": "TAG",
                                        "message": f"🔌 {p.name} was offline for >90s! Forfeited and converted to Hunter!"
                                    })
                                    await broadcast_room_state(room, "PLAYER_TAGGED", {"runner_name": p.name, "hunter_name": "System"})

                        # Manage Radar Pulses
                        if not room.radar_pulse_active and now >= room.next_radar_pulse_at:
                            # Trigger Radar Sweep
                            room.radar_pulse_active = True
                            room.radar_pulse_expires_at = now + room.radar_duration_seconds
                            room.next_radar_pulse_at = room.radar_pulse_expires_at + room.radar_interval_seconds
                            room.kill_log.append({
                                "time": time.strftime("%H:%M:%S"),
                                "type": "RADAR",
                                "message": f"📡 SATELLITE RADAR SWEEP ACTIVE for {room.radar_duration_seconds}s! Runner positions revealed!"
                            })
                            await broadcast_room_state(room, "RADAR_PULSE_START")

                        elif room.radar_pulse_active and now >= room.radar_pulse_expires_at:
                            # End Radar Sweep
                            room.radar_pulse_active = False
                            room.kill_log.append({
                                "time": time.strftime("%H:%M:%S"),
                                "type": "RADAR_END",
                                "message": "📡 Radar sweep ended. Stealth cloak restored."
                            })
                            await broadcast_room_state(room, "RADAR_PULSE_END")

            await asyncio.sleep(1)
        except Exception as e:
            await asyncio.sleep(1)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(game_ticker())

# ----------------- HTTP Routes -----------------

@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/game")
async def game_page():
    return FileResponse(os.path.join(STATIC_DIR, "game.html"))

@app.get("/api/info")
async def server_info(request: Request):
    ip = get_local_ip()
    pub = os.environ.get("PUBLIC_URL", "")
    # In cloud hosting, request.base_url automatically knows the exact https domain
    base_url = str(request.base_url).rstrip("/")
    # If on cloud (non-localhost/127.0.0.1), use base_url as the public join link
    if "localhost" not in base_url and "127.0.0.1" not in base_url:
        join_url = base_url
    else:
        join_url = pub if pub else f"http://{ip}:8000"

    return {
        "status": "online",
        "local_ip": ip,
        "public_url": pub or join_url,
        "port": int(os.environ.get("PORT", 8000)),
        "join_url": join_url
    }

class CreateRoomRequest(BaseModel):
    name: str
    host_name: str
    duration_minutes: int = 30
    head_start_seconds: int = 90
    radar_interval_minutes: int = 3
    initial_hunters: int = 1

@app.post("/api/rooms/create")
async def create_room(req: CreateRoomRequest):
    code = f"HUNT{random.randint(100, 999)}"
    while code in rooms:
        code = f"HUNT{random.randint(100, 999)}"
        
    host_id = f"p_{random.randint(10000, 99999)}"
    room = Room(code=code, name=req.name, host_id=host_id)
    room.duration_seconds = max(300, req.duration_minutes * 60)
    room.head_start_seconds = max(10, req.head_start_seconds)
    room.radar_interval_seconds = max(30, req.radar_interval_minutes * 60)
    room.initial_hunter_count = max(1, req.initial_hunters)
    
    # Create host player
    host = Player(player_id=host_id, name=req.host_name, avatar="👑")
    room.players[host_id] = host
    rooms[code] = room

    return {
        "room_code": code,
        "host_id": host_id,
        "player_name": req.host_name,
        "join_url": f"http://{get_local_ip()}:8000/game?room={code}&pid={host_id}"
    }

class JoinRoomRequest(BaseModel):
    room_code: str
    player_name: str
    avatar: str = "⚡"
    sector: str = "Hostel Quad"

@app.post("/api/rooms/join")
async def join_room(req: JoinRoomRequest):
    code = req.room_code.upper().strip()
    if code not in rooms:
        raise HTTPException(status_code=404, detail="Hunt Room not found. Check the code!")
    
    room = rooms[code]
    if room.status != "LOBBY":
        # Allow rejoin if player name matches or spectator
        for p in room.players.values():
            if p.name.lower() == req.player_name.lower():
                return {"room_code": code, "player_id": p.id, "rejoin": True}
        # If new player during active game, join as infected/spectator
        # But let's allow joining as runner if headstart
    
    player_id = f"p_{random.randint(10000, 99999)}"
    player = Player(player_id=player_id, name=req.player_name, avatar=req.avatar, sector=req.sector)
    
    # If joined after game started, set as hunter
    if room.status in ["ACTIVE", "HEAD_START"]:
        player.role = "HUNTER"
        player.is_alive = True
        
    room.players[player_id] = player
    
    return {
        "room_code": code,
        "player_id": player_id,
        "player_name": req.player_name,
        "rejoin": False
    }

# ----------------- WebSocket Engine -----------------

@app.websocket("/ws/{room_code}/{player_id}")
async def websocket_endpoint(websocket: WebSocket, room_code: str, player_id: str):
    await websocket.accept()
    room_code = room_code.upper().strip()
    
    if room_code not in rooms:
        await websocket.send_text(json.dumps({"type": "ERROR", "message": "Room does not exist"}))
        await websocket.close()
        return

    room = rooms[room_code]
    if player_id not in room.players:
        await websocket.send_text(json.dumps({"type": "ERROR", "message": "Player not registered in room"}))
        await websocket.close()
        return

    player = room.players[player_id]
    player.ws = websocket
    player.is_connected = True
    player.disconnect_time = None

    # Announce connection
    await broadcast_room_state(room, "PLAYER_JOINED", {"player_name": player.name})

    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            msg_type = data.get("type")

            async with room.lock:
                now = time.time()

                # --- 1. LOCATION & SECTOR UPDATE ---
                if msg_type == "UPDATE_LOCATION":
                    if "lat" in data and "lng" in data:
                        player.lat = data["lat"]
                        player.lng = data["lng"]
                        player.last_pos_time = now
                    if "sector" in data and data["sector"]:
                        player.sector = str(data["sector"]).strip()
                    # Broadcast location update
                    await broadcast_room_state(room, "LOCATION_UPDATE")

                # --- 2. START HUNT (Host only) ---
                elif msg_type == "START_GAME":
                    if player.id != room.host_id:
                        await websocket.send_text(json.dumps({"type": "ERROR", "message": "Only host can launch the hunt!"}))
                        continue

                    all_pids = list(room.players.keys())
                    if len(all_pids) < 2:
                        await websocket.send_text(json.dumps({"type": "ERROR", "message": "At least 2 players needed to start manhunt!"}))
                        continue

                    # Select initial hunters
                    hunter_count = min(room.initial_hunter_count, len(all_pids) - 1)
                    # Check if players were manually set in lobby
                    existing_hunters = [pid for pid, p in room.players.items() if p.role == "HUNTER"]
                    if len(existing_hunters) == 0:
                        chosen_hunters = random.sample(all_pids, hunter_count)
                        for pid in all_pids:
                            p = room.players[pid]
                            if pid in chosen_hunters:
                                p.role = "HUNTER"
                                p.is_original_hunter = True
                            else:
                                p.role = "RUNNER"
                                p.is_alive = True
                                p.pin = f"{random.randint(1000, 9999)}"
                    else:
                        for pid in all_pids:
                            p = room.players[pid]
                            if p.role != "HUNTER":
                                p.role = "RUNNER"
                                p.is_alive = True
                                p.pin = f"{random.randint(1000, 9999)}"

                    room.status = "HEAD_START"
                    room.start_time = now
                    room.head_start_end_time = now + room.head_start_seconds
                    room.end_time = now + room.head_start_seconds + room.duration_seconds
                    room.radar_pulse_active = False
                    room.winner = None

                    # Set Zone Center if not already configured
                    if not room.zone_center_lat or not room.zone_center_lng:
                        if player.lat and player.lng:
                            room.zone_center_lat = player.lat
                            room.zone_center_lng = player.lng
                        else:
                            for op in room.players.values():
                                if op.lat and op.lng:
                                    room.zone_center_lat = op.lat
                                    room.zone_center_lng = op.lng
                                    break
                        if not room.zone_center_lat:
                            room.zone_center_lat = 22.5726
                            room.zone_center_lng = 88.3639

                    room.zone_current_radius = room.zone_initial_radius
                    room.last_shrink_stage = 0

                    room.kill_log = [{
                        "time": time.strftime("%H:%M:%S"),
                        "type": "START",
                        "message": f"🚀 MANHUNT LAUNCHED! Safe zone: {int(room.zone_initial_radius)}m (shrinks over time). Runners scatter!"
                    }]

                    await broadcast_room_state(room, "GAME_START")

                # --- 2B. SET PLAYZONE CENTER & RADIUS (Host only) ---
                elif msg_type == "SET_ZONE_CENTER":
                    if player.id == room.host_id:
                        if "lat" in data and "lng" in data:
                            room.zone_center_lat = float(data["lat"])
                            room.zone_center_lng = float(data["lng"])
                        if "radius" in data:
                            room.zone_initial_radius = float(data["radius"])
                            room.zone_current_radius = room.zone_initial_radius
                        await broadcast_room_state(room, "ZONE_CENTER_UPDATED")

                # --- 3. SET PLAYER ROLE IN LOBBY (Host only) ---
                elif msg_type == "SET_ROLE":
                    target_pid = data.get("target_player_id")
                    new_role = data.get("role")
                    if player.id == room.host_id and target_pid in room.players and new_role in ["HUNTER", "RUNNER"]:
                        room.players[target_pid].role = new_role
                        await broadcast_room_state(room, "ROLE_CHANGED")

                # --- 4. TAG / ELIMINATION ATTEMPT (Hunter entering Runner PIN) ---
                elif msg_type == "TAG_PIN":
                    if player.role != "HUNTER":
                        await websocket.send_text(json.dumps({"type": "ERROR", "message": "Only active hunters can tag runners!"}))
                        continue

                    pin_entered = str(data.get("pin", "")).strip()
                    found_target: Optional[Player] = None

                    # Check PIN against all living runners in room
                    for target in room.players.values():
                        if target.role == "RUNNER" and target.is_alive and target.pin == pin_entered:
                            found_target = target
                            break

                    if found_target:
                        # VALID ELIMINATION!
                        found_target.is_alive = True  # In Infection mode, they stay in game
                        found_target.role = "HUNTER"  # INFECTED!
                        found_target.tagged_by = player.name
                        found_target.tagged_at = now
                        player.kills_count += 1

                        room.kill_log.append({
                            "time": time.strftime("%H:%M:%S"),
                            "type": "TAG",
                            "hunter": player.name,
                            "runner": found_target.name,
                            "sector": found_target.sector,
                            "message": f"💥 {player.name} INFECTED {found_target.name} near [{found_target.sector}]!"
                        })

                        # Check if any runners remain
                        alive_runners = room.get_runners_count()
                        if alive_runners == 0:
                            room.status = "ENDED"
                            room.winner = "HUNTERS"
                            room.kill_log.append({
                                "time": time.strftime("%H:%M:%S"),
                                "type": "VICTORY",
                                "message": f"💀 ALL RUNNERS INFECTED! The Hunters conquered the campus!"
                            })
                            await broadcast_room_state(room, "GAME_OVER", {
                                "just_tagged": found_target.name,
                                "hunter": player.name
                            })
                        else:
                            await broadcast_room_state(room, "PLAYER_TAGGED", {
                                "runner_id": found_target.id,
                                "runner_name": found_target.name,
                                "hunter_name": player.name,
                                "alive_runners": alive_runners
                            })
                    else:
                        # INVALID PIN
                        await websocket.send_text(json.dumps({
                            "type": "TAG_ERROR",
                            "message": "❌ Invalid PIN! Runner code does not match or already infected."
                        }))

                # --- 4B. HUNTER DIRECT TAG CLAIM (If runner hides screen / refuses QR) ---
                elif msg_type == "CLAIM_TAG":
                    if player.role != "HUNTER":
                        await websocket.send_text(json.dumps({"type": "ERROR", "message": "Only hunters can claim a tag!"}))
                        continue

                    # 1. Anti-Spam: 60s cooldown between claims
                    if player.last_claim_time and (now - player.last_claim_time < 60):
                        rem_cd = int(60 - (now - player.last_claim_time))
                        await websocket.send_text(json.dumps({
                            "type": "TAG_ERROR",
                            "message": f"⏳ False Claim Lockout: Wait {rem_cd}s before filing another tag claim!"
                        }))
                        continue

                    target_pid = data.get("target_player_id")
                    target = room.players.get(target_pid)
                    if not target or target.role != "RUNNER" or not target.is_alive:
                        await websocket.send_text(json.dumps({"type": "ERROR", "message": "Target runner not found or already infected!"}))
                        continue

                    # 2. Strict Physical Proximity Validation (Must be within 20m or exact same sector)
                    has_gps = (player.lat is not None and player.lng is not None and target.lat is not None and target.lng is not None)
                    if has_gps:
                        dist = haversine_distance(player.lat, player.lng, target.lat, target.lng)
                        if dist > 20.0:  # 20 meters physical limit
                            await websocket.send_text(json.dumps({
                                "type": "TAG_ERROR",
                                "message": f"❌ CLAIM BLOCKED (ANTI-CHEAT): You are {int(dist)}m away from {target.name}! You must be in physical touching distance (<20m) to claim a tag!"
                            }))
                            continue
                    else:
                        # Indoor fallback: Both players must be in the exact same sector/floor
                        p_sec = (player.sector or "").strip().lower()
                        t_sec = (target.sector or "").strip().lower()
                        if p_sec != t_sec:
                            await websocket.send_text(json.dumps({
                                "type": "TAG_ERROR",
                                "message": f"❌ CLAIM BLOCKED (SECTOR MISMATCH): You are at [{player.sector}], but {target.name} is at [{target.sector}]!"
                            }))
                            continue

                    player.last_claim_time = now

                    # Attach pending claim with 25-second countdown
                    target.pending_claim = {
                        "hunter_id": player.id,
                        "hunter_name": player.name,
                        "expires_at": now + 25
                    }

                    room.kill_log.append({
                        "time": time.strftime("%H:%M:%S"),
                        "type": "ALERT",
                        "message": f"⚠️ {player.name} FILED A TAG CLAIM ON {target.name}! Auto-confirming in 25s if undisputed!"
                    })

                    await broadcast_room_state(room, "TAG_CLAIMED_ALERT", {
                        "hunter_name": player.name,
                        "runner_name": target.name,
                        "runner_id": target.id
                    })

                # --- 4C. RUNNER ACCEPTS TAG CLAIM ---
                elif msg_type == "ACCEPT_TAG_CLAIM":
                    if player.pending_claim:
                        hunter_id = player.pending_claim.get("hunter_id")
                        hunter_name = player.pending_claim.get("hunter_name", "Hunter")
                        player.pending_claim = None
                        player.role = "HUNTER"
                        player.tagged_by = hunter_name
                        player.tagged_at = now
                        h = room.players.get(hunter_id)
                        if h:
                            h.kills_count += 1

                        room.kill_log.append({
                            "time": time.strftime("%H:%M:%S"),
                            "type": "TAG",
                            "message": f"💥 {player.name} confirmed tag by {hunter_name}! Converted to Hunter!"
                        })
                        alive_runners = room.get_runners_count()
                        if alive_runners == 0:
                            room.status = "ENDED"
                            room.winner = "HUNTERS"
                            await broadcast_room_state(room, "GAME_OVER")
                        else:
                            await broadcast_room_state(room, "PLAYER_TAGGED", {"runner_name": player.name, "hunter_name": hunter_name})

                # --- 4D. RUNNER DISPUTES TAG CLAIM ---
                elif msg_type == "DISPUTE_TAG_CLAIM":
                    if player.pending_claim:
                        hunter_name = player.pending_claim.get("hunter_name", "Hunter")
                        disp_id = f"disp_{random.randint(1000, 9999)}"
                        disp = {
                            "id": disp_id,
                            "runner_id": player.id,
                            "runner_name": player.name,
                            "hunter_id": player.pending_claim.get("hunter_id"),
                            "hunter_name": hunter_name,
                            "time": time.strftime("%H:%M:%S"),
                            "reason": str(data.get("reason", "Disputed tag physical touch")),
                            "status": "PENDING"
                        }
                        player.pending_claim = None
                        room.disputes.append(disp)
                        room.kill_log.append({
                            "time": time.strftime("%H:%M:%S"),
                            "type": "ALERT",
                            "message": f"⚖️ DISPUTE FILED: {player.name} disputes tag by {hunter_name}! Warden summoned for verdict!"
                        })
                        await broadcast_room_state(room, "DISPUTE_FILED", disp)

                # --- 4E. HOST RESOLVES DISPUTE ---
                elif msg_type == "RESOLVE_DISPUTE":
                    if player.id == room.host_id:
                        disp_id = data.get("dispute_id")
                        verdict = data.get("verdict")  # "INFECT" or "DISMISS"
                        for d in room.disputes:
                            if d["id"] == disp_id:
                                d["status"] = "RESOLVED"
                                r_target = room.players.get(d["runner_id"])
                                if verdict == "INFECT" and r_target and r_target.role == "RUNNER":
                                    r_target.role = "HUNTER"
                                    r_target.tagged_by = d["hunter_name"]
                                    r_target.tagged_at = now
                                    h = room.players.get(d["hunter_id"])
                                    if h:
                                        h.kills_count += 1
                                    room.kill_log.append({
                                        "time": time.strftime("%H:%M:%S"),
                                        "type": "TAG",
                                        "message": f"⚖️ WARDEN RULING: Tag upheld! {r_target.name} is INFECTED!"
                                    })
                                    alive_runners = room.get_runners_count()
                                    if alive_runners == 0:
                                        room.status = "ENDED"
                                        room.winner = "HUNTERS"
                                        await broadcast_room_state(room, "GAME_OVER")
                                    else:
                                        await broadcast_room_state(room, "PLAYER_TAGGED", {"runner_name": r_target.name, "hunter_name": d["hunter_name"]})
                                else:
                                    room.kill_log.append({
                                        "time": time.strftime("%H:%M:%S"),
                                        "type": "ALERT",
                                        "message": f"⚖️ WARDEN RULING: Dispute dismissed. {d['runner_name']} remains a Runner."
                                    })
                                    await broadcast_room_state(room, "DISPUTE_DISMISSED")
                                break

                # --- 4F. HOST FORCE-INFECT & AUDIBLE SIREN PING ---
                elif msg_type == "FORCE_INFECT":
                    if player.id == room.host_id:
                        target_pid = data.get("target_player_id")
                        target = room.players.get(target_pid)
                        if target and target.role == "RUNNER":
                            target.role = "HUNTER"
                            target.tagged_by = "Warden Override"
                            target.tagged_at = now
                            room.kill_log.append({
                                "time": time.strftime("%H:%M:%S"),
                                "type": "TAG",
                                "message": f"👑 WARDEN FORCE-INFECTED {target.name}!"
                            })
                            await broadcast_room_state(room, "PLAYER_TAGGED", {"runner_name": target.name, "hunter_name": "Host"})

                elif msg_type == "FORCE_SIREN_PING":
                    if player.id == room.host_id:
                        target_pid = data.get("target_player_id")
                        target = room.players.get(target_pid)
                        if target and target.ws:
                            try:
                                await target.ws.send_text(json.dumps({"type": "TRIGGER_LOUD_SIREN"}))
                            except Exception:
                                pass

                # --- 5. RUNNER SURRENDER / SELF-CONFIRM TAG ---
                elif msg_type == "RUNNER_SURRENDER":
                    if player.role == "RUNNER" and player.is_alive:
                        hunter_name = data.get("hunter_name", "A Hunter")
                        player.role = "HUNTER"
                        player.tagged_by = hunter_name
                        player.tagged_at = now

                        # Award kill to hunter if found
                        for h in room.players.values():
                            if h.name == hunter_name and h.role == "HUNTER":
                                h.kills_count += 1
                                break

                        room.kill_log.append({
                            "time": time.strftime("%H:%M:%S"),
                            "type": "TAG",
                            "hunter": hunter_name,
                            "runner": player.name,
                            "sector": player.sector,
                            "message": f"🏳️ {player.name} surrendered to {hunter_name} near [{player.sector}]!"
                        })

                        alive_runners = room.get_runners_count()
                        if alive_runners == 0:
                            room.status = "ENDED"
                            room.winner = "HUNTERS"
                            await broadcast_room_state(room, "GAME_OVER")
                        else:
                            await broadcast_room_state(room, "PLAYER_TAGGED", {
                                "runner_id": player.id,
                                "runner_name": player.name,
                                "hunter_name": hunter_name,
                                "alive_runners": alive_runners
                            })

                # --- 6. TRIGGER MANUAL RADAR SCAN (Host or Hunter Ability) ---
                elif msg_type == "TRIGGER_RADAR":
                    if (player.id == room.host_id or player.role == "HUNTER") and room.status == "ACTIVE":
                        room.radar_pulse_active = True
                        room.radar_pulse_expires_at = now + room.radar_duration_seconds
                        room.next_radar_pulse_at = room.radar_pulse_expires_at + room.radar_interval_seconds
                        room.kill_log.append({
                            "time": time.strftime("%H:%M:%S"),
                            "type": "RADAR",
                            "message": f"🚨 MANUAL SATELLITE PING triggered by {player.name}! Runner blips visible!"
                        })
                        await broadcast_room_state(room, "RADAR_PULSE_START")

                # --- 7. HOST BROADCAST ALERT MESSAGE ---
                elif msg_type == "BROADCAST_ALERT":
                    if player.id == room.host_id:
                        msg = data.get("message", "CAMPUS ALERT")
                        room.kill_log.append({
                            "time": time.strftime("%H:%M:%S"),
                            "type": "HOST_ALERT",
                            "message": f"📢 WARDEN / HOST BROADCAST: {msg}"
                        })
                        await broadcast_room_state(room, "HOST_BROADCAST", {"alert_text": msg})

                # --- 7B. TEAM RADIO / PRIVATE SQUAD COMMS ---
                elif msg_type == "SEND_RADIO_CHAT":
                    text = str(data.get("message", "")).strip()
                    if text:
                        chat_msg = {
                            "time": time.strftime("%H:%M:%S"),
                            "sender": player.name,
                            "avatar": player.avatar,
                            "role": player.role,
                            "sector": player.sector,
                            "text": text
                        }
                        # Route message: Runners hear Runners, Hunters hear Hunters
                        for p in room.players.values():
                            if p.ws and p.role == player.role:
                                try:
                                    await p.ws.send_text(json.dumps({
                                        "type": "RADIO_MESSAGE",
                                        "chat": chat_msg
                                    }))
                                except Exception:
                                    pass

                # --- 8. RESTART / RESET ROOM ---
                elif msg_type == "RESET_GAME":
                    if player.id == room.host_id:
                        room.status = "LOBBY"
                        room.winner = None
                        room.radar_pulse_active = False
                        for p in room.players.values():
                            p.role = "RUNNER"
                            p.is_alive = True
                            p.kills_count = 0
                            p.tagged_by = None
                            p.tagged_at = None
                            p.pin = f"{random.randint(1000, 9999)}"
                        room.kill_log.append({
                            "time": time.strftime("%H:%M:%S"),
                            "type": "RESET",
                            "message": "🔄 Game reset to Lobby by Host."
                        })
                        await broadcast_room_state(room, "GAME_RESET")

    except WebSocketDisconnect:
        player.ws = None
        player.is_connected = False
        player.disconnect_time = time.time()
        # Notify room of temporary disconnect
        await broadcast_room_state(room, "PLAYER_DISCONNECTED", {"player_name": player.name})
    except Exception as e:
        player.ws = None
        player.is_connected = False
        player.disconnect_time = time.time()
