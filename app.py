import tkinter as tk
from tkinter import ttk
import math
import json

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

# ══════════════════════════════════════════════════════
#  STATE
# ══════════════════════════════════════════════════════
state = {
    "lux": 0,
    "manual_override": False,
    "lamps": {"lamp1": False, "lamp2": False, "lamp3": False, "lamp4": False},
    "motors": {"motor1": 0, "motor2": 0},
    "connected": False,
}
motor_angles = {"motor1": 0.0, "motor2": 0.0}
lamp_ids = ["lamp1", "lamp2", "lamp3", "lamp4"]

# ── Tema Warna ─────────────────────────────────────────
BG          = "#f0f7f6"
PANEL_L     = "#ffffff"
PANEL_R     = "#e8f4f2"
BORDER      = "#b2d8d2"
ACCENT      = "#1a9e8f"
ACCENT2     = "#148075"
ACCENT_LT   = "#d4f0ec"
TEXT        = "#1a3532"
MUTED       = "#7aada7"
BTN_ON      = "#1a9e8f"
BTN_OFF     = "#e05555"
BTN_AUTO    = "#f0a500"
ROOM_BG     = "#f7fbfa"
ROOM_BORDER = "#c8e6e2"
LAMP_OFF    = "#d0d8d7"
LAMP_WIRE   = "#aabfbc"
STATUS_ON   = "#1a9e8f"
STATUS_OFF  = "#e05555"

def lux_to_lamp(lux, on):
    if not on or lux == 0:
        return LAMP_OFF
    t = min(lux / 1000.0, 1.0)
    r = int(200 + t * 55)
    g = int(170 + t * 70)
    b = int(30  + t * 10)
    return f"#{r:02x}{g:02x}{b:02x}"

def lux_to_halo(lux, on):
    if not on or lux == 0:
        return ROOM_BG
    t = min(lux / 1000.0, 1.0)
    r = int(247 - t * 20)
    g = int(251 - t * 40)
    b = int(250 - t * 120)
    return f"#{r:02x}{g:02x}{b:02x}"

# ══════════════════════════════════════════════════════
#  SCROLLABLE FRAME HELPER
# ══════════════════════════════════════════════════════
class ScrollableFrame(tk.Frame):
    """Frame yang bisa di-scroll vertikal."""
    def __init__(self, parent, bg=BG, **kwargs):
        super().__init__(parent, bg=bg, **kwargs)

        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical",
                                       command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self._win_id = self.canvas.create_window(
            (0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Mouse wheel scroll
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>",   self._on_mousewheel)
        self.canvas.bind("<Button-5>",   self._on_mousewheel)
        self.inner.bind("<MouseWheel>",  self._on_mousewheel)

    def _on_inner_configure(self, e):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, e):
        self.canvas.itemconfig(self._win_id, width=e.width)

    def _on_mousewheel(self, e):
        if e.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif e.num == 5:
            self.canvas.yview_scroll(1, "units")
        else:
            self.canvas.yview_scroll(int(-1*(e.delta/120)), "units")

# ══════════════════════════════════════════════════════
#  APLIKASI
# ══════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SmartRoom MQTT Controller")
        self.configure(bg=BG)
        # Ukuran awal sedang, bisa diubah
        self.geometry("860x620")
        self.minsize(700, 480)
        self.resizable(True, True)

        self.mqtt_client  = None
        self.broker_var   = tk.StringVar(value="192.168.1.8")
        self.port_var     = tk.StringVar(value="1883")
        self.status_var   = tk.StringVar(value="DISCONNECTED")
        self.override_var = tk.BooleanVar(value=False)
        self.lux_var      = tk.IntVar(value=0)

        self._build()
        self._tick()

    # ─── LAYOUT UTAMA ─────────────────────────────────
    def _build(self):
        # Header bar
        hdr = tk.Frame(self, bg=ACCENT, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="  ⌂  SmartRoom MQTT Controller",
                 font=("Segoe UI", 12, "bold"),
                 fg="white", bg=ACCENT).pack(side="left", padx=8, pady=8)
        self.status_dot = tk.Label(hdr, text="● DISCONNECTED",
                                   font=("Segoe UI", 8, "bold"),
                                   fg="#ffcccc", bg=ACCENT)
        self.status_dot.pack(side="right", padx=14)

        # Area utama scrollable
        self.scroll_frame = ScrollableFrame(self, bg=BG)
        self.scroll_frame.pack(fill="both", expand=True, padx=0, pady=0)

        inner = self.scroll_frame.inner

        # Dua kolom: Room Viz (kiri) + Controls (kanan)
        body = tk.Frame(inner, bg=BG)
        body.pack(padx=12, pady=10, fill="both", expand=True)

        self._build_room(body)
        self._build_controls(body)

    # ─── VISUALISASI RUANGAN ──────────────────────────
    def _build_room(self, parent):
        wrap = tk.Frame(parent, bg=PANEL_L,
                        highlightthickness=1, highlightbackground=BORDER)
        wrap.pack(side="left", anchor="n")

        title_bar = tk.Frame(wrap, bg=ACCENT_LT, pady=5)
        title_bar.pack(fill="x")
        tk.Label(title_bar, text="Room Visualization",
                 font=("Segoe UI", 10, "bold"),
                 fg=ACCENT2, bg=ACCENT_LT).pack()

        # Canvas lebih compact: 400x320
        self.cv = tk.Canvas(wrap, width=400, height=310,
                            bg=ROOM_BG, highlightthickness=0)
        self.cv.pack(padx=8, pady=6)

        # Dinding
        self.cv.create_rectangle(10, 10, 390, 300,
                                 outline=ROOM_BORDER, fill=ROOM_BG, width=2)

        # ── 4 Lampu layout 2×2 — lebih kecil
        lamp_pos = {
            "lamp1": (100, 95),
            "lamp2": (300, 95),
            "lamp3": (100, 210),
            "lamp4": (300, 210),
        }
        self.lamp_halo = {}
        self.lamp_body = {}
        R_HALO = 38   # radius halo
        R_LAMP = 14   # radius badan lampu (lebih kecil)

        for lid, (cx, cy) in lamp_pos.items():
            # Kabel dari langit-langit
            self.cv.create_line(cx, 10, cx, cy - R_LAMP - 2,
                                fill=LAMP_WIRE, width=1)
            # Halo
            h = self.cv.create_oval(cx-R_HALO, cy-R_HALO,
                                    cx+R_HALO, cy+R_HALO,
                                    fill=ROOM_BG, outline="")
            self.lamp_halo[lid] = h
            # Badan lampu
            b = self.cv.create_oval(cx-R_LAMP, cy-R_LAMP,
                                    cx+R_LAMP, cy+R_LAMP,
                                    fill=LAMP_OFF, outline=MUTED, width=1)
            self.lamp_body[lid] = b
            # Label
            self.cv.create_text(cx, cy + R_LAMP + 10,
                                text=lid,
                                font=("Segoe UI", 7), fill=MUTED)

        # ── 2 Motor (bawah tengah) — lebih kecil
        motor_pos = {"motor1": (140, 270), "motor2": (260, 270)}
        self.motor_ring  = {}
        self.motor_blade = {}
        R_MOTOR = 20   # radius motor

        for mid, (cx, cy) in motor_pos.items():
            self.cv.create_oval(cx-R_MOTOR, cy-R_MOTOR,
                                cx+R_MOTOR, cy+R_MOTOR,
                                outline=BORDER, fill="#e8f4f2", width=1)
            self.motor_ring[mid] = (cx, cy)
            blades = []
            for angle_offset in [0, 120, 240]:
                a = math.radians(angle_offset)
                ex = cx + (R_MOTOR - 2) * math.cos(a)
                ey = cy + (R_MOTOR - 2) * math.sin(a)
                bl = self.cv.create_line(cx, cy, ex, ey,
                                         fill=ACCENT, width=2,
                                         capstyle="round")
                blades.append(bl)
            self.motor_blade[mid] = blades
            # Hub
            self.cv.create_oval(cx-3, cy-3, cx+3, cy+3,
                                fill=ACCENT2, outline="")
            self.cv.create_text(cx, cy + R_MOTOR + 8,
                                text=f"{mid} 0%",
                                font=("Segoe UI", 7), fill=MUTED,
                                tags=f"mlbl_{mid}")

        # Status bar bawah kanvas
        sbar = tk.Frame(wrap, bg=ACCENT_LT, pady=4)
        sbar.pack(fill="x")
        tk.Label(sbar, text="Lux:", font=("Segoe UI", 8),
                 fg=MUTED, bg=ACCENT_LT).pack(side="left", padx=8)
        self.lux_prog = tk.Canvas(sbar, width=150, height=12,
                                  bg="#d4ebe8", highlightthickness=0)
        self.lux_prog.pack(side="left", padx=3)
        self.lux_fill = self.lux_prog.create_rectangle(
            0, 0, 0, 12, fill=ACCENT, outline="")
        self.lux_lbl = tk.Label(sbar, text="0 lx",
                                font=("Segoe UI", 8, "bold"),
                                fg=ACCENT2, bg=ACCENT_LT, width=6)
        self.lux_lbl.pack(side="left")
        self.override_badge = tk.Label(sbar, text="Auto Mode",
                                       font=("Segoe UI", 7, "bold"),
                                       fg="white", bg=ACCENT,
                                       padx=6, pady=1)
        self.override_badge.pack(side="right", padx=8)

    # ─── PANEL KONTROL ────────────────────────────────
    def _build_controls(self, parent):
        panel = tk.Frame(parent, bg=PANEL_R,
                         highlightthickness=1, highlightbackground=BORDER)
        panel.pack(side="left", fill="both", expand=True,
                   padx=(10, 0), anchor="n")

        def sec_title(text):
            f = tk.Frame(panel, bg=ACCENT_LT, pady=4)
            f.pack(fill="x", pady=(8, 0))
            tk.Label(f, text=text, font=("Segoe UI", 8, "bold"),
                     fg=ACCENT2, bg=ACCENT_LT).pack(padx=10, anchor="w")

        def row():
            f = tk.Frame(panel, bg=PANEL_R)
            f.pack(fill="x", padx=10, pady=2)
            return f

        def entry_row(label, var, w=14):
            r = row()
            tk.Label(r, text=label, width=11, anchor="w",
                     font=("Segoe UI", 8), fg=TEXT, bg=PANEL_R).pack(side="left")
            e = tk.Entry(r, textvariable=var, width=w,
                         bg="white", fg=TEXT, font=("Segoe UI", 8),
                         relief="solid", bd=1)
            e.pack(side="left")
            return e

        # ── MQTT
        sec_title("MQTT Connection")
        entry_row("Broker host", self.broker_var)
        entry_row("Port", self.port_var, 6)

        btn_row = tk.Frame(panel, bg=PANEL_R)
        btn_row.pack(fill="x", padx=10, pady=4)
        self.btn_connect = tk.Button(btn_row, text="Connect",
                                     command=self._connect,
                                     bg=ACCENT, fg="white",
                                     font=("Segoe UI", 8, "bold"),
                                     relief="flat", cursor="hand2",
                                     padx=8, pady=3)
        self.btn_connect.pack(side="left", padx=(0, 5))
        self.btn_disconnect = tk.Button(btn_row, text="Disconnect",
                                        command=self._disconnect,
                                        bg="#cccccc", fg=TEXT,
                                        font=("Segoe UI", 8),
                                        relief="flat", cursor="hand2",
                                        padx=8, pady=3)
        self.btn_disconnect.pack(side="left")

        self.state_lbl = tk.Label(panel, textvariable=self.status_var,
                                  font=("Segoe UI", 7, "bold"),
                                  fg=STATUS_OFF, bg=PANEL_R)
        self.state_lbl.pack(anchor="w", padx=10)

        # ── SENSOR SIMULATION
        sec_title("Sensor Simulation")
        tk.Label(panel, text="Lux value (0–1000)",
                 font=("Segoe UI", 8), fg=TEXT, bg=PANEL_R).pack(
                     anchor="w", padx=10)
        self.lux_slider = tk.Scale(panel, from_=0, to=1000,
                                   orient="horizontal",
                                   variable=self.lux_var,
                                   command=self._on_lux,
                                   bg=PANEL_R, fg=TEXT,
                                   troughcolor="#c8e6e2",
                                   highlightthickness=0,
                                   activebackground=ACCENT,
                                   state="disabled", length=220,
                                   showvalue=True,
                                   font=("Segoe UI", 7))
        self.lux_slider.pack(padx=10)

        # ── ACTUATOR CONTROL
        sec_title("Actuator Control")
        r_ov = row()
        self.ov_chk = tk.Checkbutton(r_ov, text="Manual Override",
                                     variable=self.override_var,
                                     command=self._on_override,
                                     bg=PANEL_R, fg=TEXT,
                                     selectcolor="white",
                                     activebackground=PANEL_R,
                                     font=("Segoe UI", 8),
                                     cursor="hand2")
        self.ov_chk.pack(side="left")

        r_all = row()
        self.btn_all_on = tk.Button(r_all, text="All ON",
                                    command=lambda: self._lamp_all("ON"),
                                    bg=BTN_ON, fg="white",
                                    font=("Segoe UI", 7, "bold"),
                                    relief="flat", cursor="hand2",
                                    padx=6, pady=2, state="disabled")
        self.btn_all_on.pack(side="left", padx=(0, 3))
        self.btn_auto = tk.Button(r_all, text="Auto",
                                  command=lambda: self._lamp_all("AUTO"),
                                  bg=BTN_AUTO, fg="white",
                                  font=("Segoe UI", 7, "bold"),
                                  relief="flat", cursor="hand2",
                                  padx=6, pady=2, state="disabled")
        self.btn_auto.pack(side="left", padx=(0, 3))
        self.btn_all_off = tk.Button(r_all, text="All OFF",
                                     command=lambda: self._lamp_all("OFF"),
                                     bg=BTN_OFF, fg="white",
                                     font=("Segoe UI", 7, "bold"),
                                     relief="flat", cursor="hand2",
                                     padx=6, pady=2, state="disabled")
        self.btn_all_off.pack(side="left")

        # ── Per-Lamp
        sec_title("Per-Lamp Manual")
        self.lamp_btns = {}
        lamp_layout = [("lamp1", "lamp2"), ("lamp3", "lamp4")]
        for pair in lamp_layout:
            r = row()
            for lid in pair:
                b = tk.Button(r, text=f"{lid}: OFF",
                              command=lambda l=lid: self._toggle_lamp(l),
                              bg="#e0e0e0", fg=TEXT,
                              font=("Segoe UI", 7),
                              relief="flat", cursor="hand2",
                              width=10, pady=2, state="disabled")
                b.pack(side="left", padx=2)
                self.lamp_btns[lid] = b

        # ── Motor
        sec_title("Motor Control")
        self.motor_sliders = {}
        for mid in ["motor1", "motor2"]:
            r = row()
            tk.Label(r, text=f"{mid} speed",
                     font=("Segoe UI", 8), fg=TEXT, bg=PANEL_R).pack(
                         anchor="w")
            s = tk.Scale(panel, from_=0, to=100,
                         orient="horizontal",
                         command=lambda v, m=mid: self._on_motor_slider(v, m),
                         bg=PANEL_R, fg=TEXT,
                         troughcolor="#c8e6e2",
                         highlightthickness=0,
                         activebackground=ACCENT,
                         length=220, showvalue=True,
                         font=("Segoe UI", 7))
            s.pack(padx=10)
            self.motor_sliders[mid] = s

        self.motor_stat_lbl = tk.Label(panel,
                                       text="motor1: 0%   motor2: 0%",
                                       font=("Segoe UI", 7), fg=MUTED,
                                       bg=PANEL_R)
        self.motor_stat_lbl.pack(anchor="e", padx=10)

        # ── Topics
        sec_title("Subscribed Topics")
        topics_text = (
            "room/sensors/lux\n"
            "room/control/manual_override\n"
            "room/control/lamp/all\n"
            "room/control/lamp/<lamp_id>\n"
            "room/control/motor/<motor_id>\n"
            "room/control/motor/all\n"
            "room/sensors/json"
        )
        tk.Label(panel, text=topics_text,
                 font=("Consolas", 7), fg=MUTED, bg=PANEL_R,
                 justify="left").pack(anchor="w", padx=12, pady=(3, 10))

    # ─── ANIMASI ──────────────────────────────────────
    def _tick(self):
        self._draw_lamps()
        self._draw_motors()
        self._draw_lux()
        self.after(40, self._tick)

    def _draw_lamps(self):
        lux = state["lux"]
        for lid in lamp_ids:
            on = state["lamps"][lid]
            self.cv.itemconfig(self.lamp_body[lid], fill=lux_to_lamp(lux, on))
            self.cv.itemconfig(self.lamp_halo[lid], fill=lux_to_halo(lux, on))
            if state["manual_override"]:
                txt = f"{lid}: ON " if on else f"{lid}: OFF"
                bg  = BTN_ON if on else "#e0e0e0"
                fg  = "white" if on else TEXT
                self.lamp_btns[lid].config(text=txt, bg=bg, fg=fg)

    def _draw_motors(self):
        for mid, (cx, cy) in self.motor_ring.items():
            spd = state["motors"][mid]
            if spd > 0:
                motor_angles[mid] += spd * 0.05
            base = motor_angles[mid]
            R = 18
            for i, bl in enumerate(self.motor_blade[mid]):
                a  = math.radians(base + i * 120)
                ex = cx + R * math.cos(a)
                ey = cy + R * math.sin(a)
                self.cv.coords(bl, cx, cy, ex, ey)
            self.cv.delete(f"mlbl_{mid}")
            self.cv.create_text(cx, cy + 28,
                                text=f"{mid} {spd}%",
                                font=("Segoe UI", 7), fill=MUTED,
                                tags=f"mlbl_{mid}")
        spd1 = state["motors"]["motor1"]
        spd2 = state["motors"]["motor2"]
        self.motor_stat_lbl.config(
            text=f"motor1: {spd1}%   motor2: {spd2}%")

    def _draw_lux(self):
        lux = state["lux"]
        w   = int(150 * lux / 1000)
        self.lux_prog.coords(self.lux_fill, 0, 0, w, 12)
        self.lux_lbl.config(text=f"{lux} lx")
        if state["manual_override"]:
            self.override_badge.config(text="Manual Override", bg=BTN_AUTO)
        else:
            self.override_badge.config(text="Auto Mode", bg=ACCENT)

    # ─── EVENTS ───────────────────────────────────────
    def _on_override(self):
        val = self.override_var.get()
        state["manual_override"] = val
        s = "normal" if val else "disabled"
        self.lux_slider.config(state=s)
        for b in self.lamp_btns.values():
            b.config(state=s)
        for btn in [self.btn_all_on, self.btn_auto, self.btn_all_off]:
            btn.config(state=s)
        self._publish("room/control/manual_override", "1" if val else "0")

    def _on_lux(self, val):
        state["lux"] = int(val)

    def _on_motor_slider(self, val, mid):
        state["motors"][mid] = int(val)
        self._publish(f"room/control/motor/{mid}", str(int(val)))

    def _lamp_all(self, cmd):
        for lid in lamp_ids:
            state["lamps"][lid] = (cmd == "ON")
        self._publish("room/control/lamp/all", cmd)

    def _toggle_lamp(self, lid):
        state["lamps"][lid] = not state["lamps"][lid]
        cmd = "ON" if state["lamps"][lid] else "OFF"
        self._publish(f"room/control/lamp/{lid}", cmd)

    # ─── MQTT ─────────────────────────────────────────
    def _connect(self):
        if not MQTT_AVAILABLE:
            self.status_var.set("Error: paho-mqtt not installed")
            return
        try:
            self.mqtt_client = mqtt.Client()
            self.mqtt_client.on_connect    = self._on_connect
            self.mqtt_client.on_message    = self._on_message
            self.mqtt_client.on_disconnect = self._on_disconnect
            self.mqtt_client.connect(self.broker_var.get(),
                                     int(self.port_var.get()), 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            self.status_var.set(f"Error: {e}")

    def _disconnect(self):
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        self._set_offline()

    def _set_offline(self):
        state["connected"] = False
        self.status_var.set("State: DISCONNECTED")
        self.state_lbl.config(fg=STATUS_OFF)
        self.status_dot.config(text="● DISCONNECTED", fg="#ffcccc")

    def _on_connect(self, client, ud, flags, rc):
        if rc == 0:
            state["connected"] = True
            self.status_var.set("State: CONNECTED")
            self.state_lbl.config(fg=STATUS_ON)
            self.status_dot.config(text="● CONNECTED", fg="#ccffee")
            for t in ["room/sensors/lux", "room/control/manual_override",
                      "room/control/lamp/all", "room/control/lamp/+",
                      "room/control/motor/all", "room/control/motor/+",
                      "room/sensors/json"]:
                client.subscribe(t)
        else:
            self.status_var.set(f"State: ERROR rc={rc}")

    def _on_disconnect(self, client, ud, rc):
        self._set_offline()

    def _on_message(self, client, ud, msg):
        topic   = msg.topic
        payload = msg.payload.decode().strip()
        ov = state["manual_override"]

        if topic == "room/control/manual_override":
            v = payload == "1"
            state["manual_override"] = v
            self.override_var.set(v)
            s = "normal" if v else "disabled"
            self.lux_slider.config(state=s)
            for b in self.lamp_btns.values():
                b.config(state=s)
            for btn in [self.btn_all_on, self.btn_auto, self.btn_all_off]:
                btn.config(state=s)

        elif topic == "room/sensors/lux" and not ov:
            try:
                state["lux"] = max(0, min(1000, int(payload)))
                self.lux_var.set(state["lux"])
            except: pass

        elif topic == "room/control/lamp/all" and not ov:
            for lid in lamp_ids:
                state["lamps"][lid] = payload == "ON"

        elif topic.startswith("room/control/lamp/") and not ov:
            lid = topic.split("/")[-1]
            if lid in state["lamps"]:
                state["lamps"][lid] = payload == "ON"

        elif topic == "room/control/motor/all":
            try:
                spd = max(0, min(100, int(payload)))
                for m in state["motors"]:
                    state["motors"][m] = spd
                self.motor_sliders["motor1"].set(spd)
                self.motor_sliders["motor2"].set(spd)
            except: pass

        elif topic.startswith("room/control/motor/"):
            mid = topic.split("/")[-1]
            if mid in state["motors"]:
                try:
                    spd = max(0, min(100, int(payload)))
                    state["motors"][mid] = spd
                    self.motor_sliders[mid].set(spd)
                except: pass

        elif topic == "room/sensors/json":
            try:
                data = json.loads(payload)
                if "lux" in data and not ov:
                    state["lux"] = max(0, min(1000, int(data["lux"])))
                    self.lux_var.set(state["lux"])
                if "manual_override" in data:
                    v = bool(data["manual_override"])
                    state["manual_override"] = v
                    self.override_var.set(v)
                for mid in ["motor1", "motor2"]:
                    k = f"{mid}_speed"
                    if k in data:
                        spd = max(0, min(100, int(data[k])))
                        state["motors"][mid] = spd
                        self.motor_sliders[mid].set(spd)
            except: pass

    def _publish(self, topic, payload):
        if self.mqtt_client and state["connected"]:
            self.mqtt_client.publish(topic, payload)

# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    app = App()
    app.mainloop()
