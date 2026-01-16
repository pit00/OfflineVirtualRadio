import time
import os
import socket
import datetime
import threading
import json
import random
import vlc

# =========================
# PATHS
# =========================

BASE = os.path.dirname(os.path.abspath(__file__))
RADIOS_DIR = os.path.join(BASE, "Radios")
STATIONS_JSON = os.path.join(BASE, "stations.json")
STATE_FILE = os.path.join(BASE, "CurrentStation.inc")

HOST = "127.0.0.1"
PORT = 9999

# =========================
# HELPERS
# =========================

def get_mp3_length_seconds(path):
    media = vlc.Media(path)
    media.parse()
    d = media.get_duration()
    return max(1, int(d / 1000))

# =========================
# BUILD / LOAD STATIONS
# =========================

def build_stations():
    if os.path.exists(STATIONS_JSON):
        with open(STATIONS_JSON, "r", encoding="utf-8") as f:
            stations = json.load(f)
    else:
        stations = {}

    for file in os.listdir(RADIOS_DIR):
        if not file.lower().endswith(".mp3"):
            continue

        name = os.path.splitext(file)[0]
        if name in stations:
            continue

        mp3_abs = os.path.join(RADIOS_DIR, file)

        stations[name] = {
            "mp3": f"Radios/{file}",     # 🔴 RELATIVE
            "length": get_mp3_length_seconds(mp3_abs),
            "seed": random.randint(10000, 99999),
        }

        print(f"[STATION ADDED] {name}")

    with open(STATIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(stations, f, indent=4)

    return stations

STATIONS = build_stations()
DEFAULT_STATION = next(iter(STATIONS))
STATION_ORDER = list(STATIONS.keys())

# =========================
# CUE PARSER
# =========================

def parse_cue(path):
    tracks = []
    if not os.path.exists(path):
        return tracks

    current = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()

            if line.startswith("PERFORMER"):
                current["artist"] = line.split('"')[1]

            elif line.startswith("TITLE"):
                current["title"] = line.split('"')[1]

            elif line.startswith("INDEX 01"):
                m, s, _ = line.split()[-1].split(":")
                current["time"] = int(m) * 60 + int(s)
                tracks.append(current)
                current = {}

    return tracks

CUE_DATA = {
    name: parse_cue(os.path.join(RADIOS_DIR, f"{name}.cue"))
    for name in STATIONS
}

def current_track(station, offset):
    tracks = CUE_DATA.get(station, [])
    if not tracks:
        return ""

    cur = tracks[0]
    for t in tracks:
        if offset >= t["time"]:
            cur = t
        else:
            break

    return f"{cur.get('artist','')} - {cur.get('title','')}".strip(" -")

# =========================
# STATE
# =========================

CURRENT_STATION = DEFAULT_STATION
PAUSED = True
PLAYING = False

player = vlc.MediaPlayer()

# =========================
# TIME
# =========================

def day_start():
    now = datetime.datetime.now()
    return datetime.datetime(now.year, now.month, now.day).timestamp()

DAY_START = day_start()
SEEK_OFFSET_MS = 0

# def live_offset(station):
#     length = STATIONS[station]["length"]
#     seed = STATIONS[station]["seed"]
#     t = (time.time() - DAY_START + seed) % length
#     return int(t * 1000), length * 1000

def live_offset(station):
    length = STATIONS[station]["length"]
    seed = STATIONS[station]["seed"]
    t = (time.time() - DAY_START + seed) % length
    t = (t * 1000 + SEEK_OFFSET_MS) % (length * 1000)
    return int(t), length * 1000

# =========================
# UI STATE EXPORT
# =========================

# def write_ui_state():
#     offset_ms, _ = live_offset(CURRENT_STATION)

#     with open(STATE_FILE, "w", encoding="utf-8") as f:
#         f.write(
#             "[Variables]\n"
#             f"CurrentStation={CURRENT_STATION}\n"
#             f"StationArt=Radios/{CURRENT_STATION}.png\n"
#             f"Song={current_track(CURRENT_STATION, offset_ms // 1000)}\n"
#             f"Paused={int(PAUSED)}\n"
#         )

def write_ui_state():
    if PAUSED:
        song = ""
    else:
        offset_ms, _ = live_offset(CURRENT_STATION)
        song = current_track(CURRENT_STATION, offset_ms // 1000)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(
            "[Variables]\n"
            f"CurrentStation={CURRENT_STATION}\n"
            f"StationArt=Radios/{CURRENT_STATION}.png\n"
            f"Song={song}\n"
            f"Paused={int(PAUSED)}\n"
        )

# =========================
# PLAYBACK
# =========================

def start_playback():
    global PLAYING

    offset, _ = live_offset(CURRENT_STATION)
    mp3_abs = os.path.join(BASE, STATIONS[CURRENT_STATION]["mp3"])

    media = vlc.Media(mp3_abs)
    player.set_media(media)
    player.play()

    for _ in range(50):
        if player.get_state() == vlc.State.Playing:
            break
        time.sleep(0.02)

    player.set_time(offset)
    PLAYING = True

def stop_playback():
    global PLAYING
    player.stop()
    PLAYING = False

def play_station(name):
    global CURRENT_STATION
    CURRENT_STATION = name
    write_ui_state()

    if PAUSED:
        return

    stop_playback()
    start_playback()

def pause_radio():
    global PAUSED
    if not PAUSED:
        PAUSED = True
        stop_playback()
        write_ui_state()

def resume_radio():
    global PAUSED
    if PAUSED:
        PAUSED = False
        write_ui_state()
        start_playback()

def next_station():
    idx = STATION_ORDER.index(CURRENT_STATION)
    new = STATION_ORDER[(idx + 1) % len(STATION_ORDER)]
    play_station(new)

def prev_station():
    idx = STATION_ORDER.index(CURRENT_STATION)
    new = STATION_ORDER[(idx - 1) % len(STATION_ORDER)]
    play_station(new)

def shuffle_station():
    STATIONS[CURRENT_STATION]["seed"] = random.randint(10000, 99999)
    write_ui_state()

    if not PAUSED:
        stop_playback()
        start_playback()

def toggle_play():
    if PAUSED:
        resume_radio()
    else:
        pause_radio()

# SEEK_STEP = 15000  # 15 seconds in ms

def seek_relative(delta_ms):
    global SEEK_OFFSET_MS
    SEEK_OFFSET_MS += delta_ms
    write_ui_state()

    if not PAUSED:
        stop_playback()
        start_playback()

# =========================
# LOOP GUARD
# =========================

def loop_guard():
    while True:
        time.sleep(1)
        if not PAUSED and PLAYING:
            pos = player.get_time()
            _, max_len = live_offset(CURRENT_STATION)
            if pos >= max_len - 1500:
                start_playback()

def ui_song_updater():
    last_station = None
    last_song = None

    while True:
        time.sleep(1)

        if PAUSED:
            if last_song != "":
                last_song = ""
                write_ui_state()
            continue

        offset_ms, _ = live_offset(CURRENT_STATION)
        song = current_track(CURRENT_STATION, offset_ms // 1000)

        if song != last_song or CURRENT_STATION != last_station:
            last_song = song
            last_station = CURRENT_STATION
            write_ui_state()

# def current_track_index(station, offset_sec):
#     tracks = CUE_DATA.get(station, [])
#     idx = 0
#     for i, t in enumerate(tracks):
#         if offset_sec >= t["time"]:
#             idx = i
#         else:
#             break
#     return idx

# def track_watcher():
#     last_index = -1
#     last_station = None
#     last_paused = None

#     while True:
#         time.sleep(0.5)

#         offset_ms, _ = live_offset(CURRENT_STATION)
#         idx = current_track_index(CURRENT_STATION, offset_ms // 1000)

#         if (
#             idx != last_index
#             or CURRENT_STATION != last_station
#             or PAUSED != last_paused
#         ):
#             last_index = idx
#             last_station = CURRENT_STATION
#             last_paused = PAUSED
#             write_ui_state()

threading.Thread(target=loop_guard, daemon=True).start()
threading.Thread(target=ui_song_updater, daemon=True).start()
# threading.Thread(target=track_watcher, daemon=True).start()

# =========================
# SOCKET SERVER
# =========================

sock = socket.socket()
sock.bind((HOST, PORT))
sock.listen(1)

write_ui_state()
play_station(DEFAULT_STATION)

while True:
    conn, _ = sock.accept()
    cmd = conn.recv(32).decode().strip()
    conn.close()

    if cmd in STATIONS:
        play_station(cmd)

    elif cmd == "NEXT":
        next_station()

    elif cmd == "PREV":
        prev_station()

    elif cmd == "PAUSE":
        pause_radio()

    elif cmd == "PLAY":
        resume_radio()

    elif cmd == "TOGGLE":
        toggle_play()

    elif cmd == "SHUFFLE":
        shuffle_station()

    elif cmd == "SEEKUP":
        seek_relative(+15000)

    elif cmd == "SEEKDOWN":
        seek_relative(-15000)

    elif cmd == "RESTART":
        stop_playback()
        sock.close()
        os._exit(0)
