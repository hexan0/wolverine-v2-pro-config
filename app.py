import sys
import os
import json
import asyncio
import threading
import customtkinter as ctk
from bleak import BleakClient, BleakScanner

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def load_lang_data():
    lang_file = get_resource_path("lang.json")
    try:
        with open(lang_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading language file: {e}")
        return {"ja": {}, "en": {}}

# ==========================================
# バックエンド
# ==========================================
class RazerWolverineV2Pro:
    UUID = "52401524-f97c-7f90-0e7f-6c6f4e36db1c"
    M_BUTTON = {"M1": 0x10, "M2": 0x11, "M3": 0x12, "M4": 0x13, "M5": 0x14, "M6": 0x15}
    FUNC = {
        "cross": 0x20, "circle": 0x21, "square": 0x22, "triangle": 0x23,
        "l1": 0x24, "r1": 0x25, "l2": 0x26, "r2": 0x27, "l3": 0x28, "r3": 0x29, 
        "up": 0x2c, "down": 0x2d, "left": 0x2e, "right": 0x2f,
        "create": 0x34, "options": 0x35,
        "clutch_dual": 0x36, "clutch_left": 0x37, "clutch_right": 0x38
    }
    STICK = {"LEFT": 0x01, "RIGHT": 0x02}

    def __init__(self):
        self.address = None
        self.client = None
        self.seq_num = 0x01

    @property
    def is_connected(self):
        return self.client is not None and self.client.is_connected

    async def connect(self):
        # 1. 自動スキャンを実行してコントローラーを探す
        devices = await BleakScanner.discover(timeout=3.0)
        for d in devices:
            # デバイス名に "Wolverine V2 Pro BLE" が含まれているかチェック
            if d.name and "Wolverine V2 Pro BLE" in d.name:
                self.address = d.address
                break

        # 見つからなかった場合は失敗として扱う
        if not self.address:
            return False

        # 2. 見つけたアドレスを使って接続処理を行う
        self.client = BleakClient(self.address)
        await self.client.connect()
        return self.is_connected

    async def disconnect(self):
        if self.client is not None:
            await self.client.disconnect()

    async def _send(self, payload):
        if not self.is_connected: return
        full_command = bytearray([self.seq_num]) + payload
        await self.client.write_gatt_char(self.UUID, full_command)
        self.seq_num = (self.seq_num % 255) + 1
        await asyncio.sleep(0.1)

    # UIから直接ID(f_id)を受け取るように変更
    async def set_mapping(self, m_btn_name, f_id):
        m_id = self.M_BUTTON.get(m_btn_name)
        if m_id and f_id:
            await self._send(bytearray([0x0a, 0x00, 0x00, 0x08, 0x04, 0x01, 0x00, 0x01, m_id, 0x00, 0x10, 0x01, f_id, 0x00, 0x00, 0x00, 0x00]))

    async def set_deadzone_raw(self, stick_name, val):
        stick_id = self.STICK.get(stick_name, 0x01)
        await self._send(bytearray([0x01, 0x00, 0x00, 0x09, 0x08, 0x01, stick_id, int(val)]))

    async def set_sensitivity_raw(self, stick_name, val):
        stick_id = self.STICK.get(stick_name, 0x01)
        await self._send(bytearray([0x01, 0x00, 0x00, 0x09, 0x02, 0x01, stick_id, int(val)]))

    async def set_chroma(self, mode_name, r=255, g=255, b=255):
        modes = {"OFF": 0x00, "STATIC": 0x01, "BREATHING": 0x02, "SPECTRUM": 0x03}
        mode_id = modes.get(mode_name.upper(), 0x03)
        if mode_id in [0x00, 0x03]: r, g, b = 0xff, 0xff, 0xff
        await self._send(bytearray([0x0c, 0x00, 0x00, 0x11, 0x03, 0x01, 0x05, 0x01, 0x05, mode_id, 0x00, 0x00, 0x01, int(r), int(g), int(b), 0xff, 0xff, 0xff]))

    async def reset_to_default(self):
        await self.set_mapping("M1", self.FUNC["square"]); await self.set_mapping("M2", self.FUNC["triangle"])
        await self.set_mapping("M3", self.FUNC["cross"]); await self.set_mapping("M4", self.FUNC["circle"])
        await self.set_mapping("M5", self.FUNC["clutch_left"]); await self.set_mapping("M6", self.FUNC["clutch_right"])
        await self.set_sensitivity_raw("LEFT", 55); await self.set_sensitivity_raw("RIGHT", 55)
        await self.set_deadzone_raw("LEFT", 7); await self.set_deadzone_raw("RIGHT", 7)
        await self.set_chroma("SPECTRUM")

_loop = asyncio.new_event_loop()
def start_async_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()
threading.Thread(target=start_async_loop, args=(_loop,), daemon=True).start()
def run_async(coro):
    asyncio.run_coroutine_threadsafe(coro, _loop)

# ==========================================
# フロントエンド
# ==========================================
class GUIApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.lang_data = load_lang_data()
        self.current_lang = "ja"
        self.controller = RazerWolverineV2Pro()
        
        self.geometry("600x650")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")

        self.main_container = None
        self.build_ui()

    @property
    def t(self):
        return self.lang_data.get(self.current_lang, self.lang_data.get("ja", {}))

    def change_language(self, choice):
        self.current_lang = "ja" if choice == "日本語" else "en"
        self.build_ui()

    def update_tip_visibility(self):
        """接続状態に応じてTipsを表示/非表示にする"""
        if self.controller.is_connected:
            self.tip_label.configure(text=self.t.get("tip_connected"))
        else:
            self.tip_label.configure(text=self.t.get("tip_pairing"))

    def build_ui(self):
        if self.main_container:
            self.main_container.destroy()
            
        self.title(self.t.get("title", "Configurator"))
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True)

        # ヘッダー領域
        header_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        header_frame.pack(pady=(10, 0), padx=20, fill="x")
        
        is_conn = self.controller.is_connected
        status_txt = self.t.get("status_connected") if is_conn else self.t.get("status_disconnected")
        btn_txt = self.t.get("btn_disconnect") if is_conn else self.t.get("btn_connect")
        cmd = self.on_disconnect_click if is_conn else self.on_connect_click
        
        self.status_label = ctk.CTkLabel(header_frame, text=status_txt, font=("Arial", 16, "bold"))
        self.status_label.pack(side="left")
        self.connect_btn = ctk.CTkButton(header_frame, text=btn_txt, command=cmd)
        self.connect_btn.pack(side="left", padx=20)
        
        lang_combo = ctk.CTkOptionMenu(header_frame, values=["日本語", "English"], command=self.change_language, width=100)
        lang_combo.set("日本語" if self.current_lang == "ja" else "English")
        lang_combo.pack(side="right")

        # Tips領域
        self.tip_label = ctk.CTkLabel(self.main_container, text="", text_color="#aaaaaa", justify="left")
        self.tip_label.pack(pady=5, padx=20, anchor="w")
        self.update_tip_visibility()

        # タブメニュー
        self.tabview = ctk.CTkTabview(self.main_container)
        self.tabview.pack(padx=20, pady=(0, 10), fill="both", expand=True)
        tab_map = self.tabview.add(self.t.get("tab_map"))
        tab_stick = self.tabview.add(self.t.get("tab_stick"))
        tab_sys = self.tabview.add(self.t.get("tab_sys"))

        # --- タブ1: マッピング ---
        # 内部キーのリストと、翻訳された表示名のリストを作成
        self.internal_funcs = list(self.controller.FUNC.keys())
        display_funcs = [self.t.get(f"func_{k}") for k in self.internal_funcs]

        def on_map_change(display_name, m_btn):
            # 表示名から内部キーを逆引きしてIDを取得
            idx = display_funcs.index(display_name)
            internal_key = self.internal_funcs[idx]
            f_id = self.controller.FUNC[internal_key]
            run_async(self.controller.set_mapping(m_btn, f_id))

        for m_btn in ["M1", "M2", "M3", "M4", "M5", "M6"]:
            f = ctk.CTkFrame(tab_map, fg_color="transparent")
            f.pack(pady=5, fill="x")
            ctk.CTkLabel(f, text=f"{m_btn} {self.t.get('lbl_button')}", width=100).pack(side="left", padx=10)
            combo = ctk.CTkComboBox(f, values=display_funcs, width=200, command=lambda c, b=m_btn: on_map_change(c, b))
            combo.pack(side="left", padx=10)

        # --- タブ2: スティック ---
        self._create_slider(tab_stick, self.t.get("lbl_dz_l"), "LEFT", is_dz=True)
        self._create_slider(tab_stick, self.t.get("lbl_dz_r"), "RIGHT", is_dz=True)
        self._create_slider(tab_stick, self.t.get("lbl_sc_l"), "LEFT", is_dz=False)
        self._create_slider(tab_stick, self.t.get("lbl_sc_r"), "RIGHT", is_dz=False)

        # --- タブ3: システム＆LED ---
        sys_f = ctk.CTkFrame(tab_sys)
        sys_f.pack(pady=10, padx=10, fill="x")
        ctk.CTkLabel(sys_f, text=self.t.get("lbl_chroma"), font=("Arial", 12, "bold")).pack(pady=5)

        mf = ctk.CTkFrame(sys_f, fg_color="transparent")
        mf.pack(fill="x", pady=5)
        ctk.CTkLabel(mf, text=self.t.get("lbl_mode")).pack(side="left", padx=10)
        self.chroma_mode = ctk.CTkComboBox(mf, values=["SPECTRUM", "STATIC", "BREATHING", "OFF"])
        self.chroma_mode.pack(side="left", padx=10)

        cf = ctk.CTkFrame(sys_f, fg_color="transparent")
        cf.pack(fill="x", pady=5)
        ctk.CTkLabel(cf, text=self.t.get("lbl_rgb")).pack(side="left", padx=10)
        self.r_entry = ctk.CTkEntry(cf, width=40); self.r_entry.insert(0, "0"); self.r_entry.pack(side="left", padx=2)
        self.g_entry = ctk.CTkEntry(cf, width=40); self.g_entry.insert(0, "255"); self.g_entry.pack(side="left", padx=2)
        self.b_entry = ctk.CTkEntry(cf, width=40); self.b_entry.insert(0, "0"); self.b_entry.pack(side="left", padx=2)

        ctk.CTkButton(sys_f, text=self.t.get("btn_apply"), command=self.on_apply_chroma).pack(pady=10)

        ctk.CTkButton(tab_sys, text=self.t.get("btn_reset"), fg_color="darkred", hover_color="red", 
                      command=lambda: run_async(self.controller.reset_to_default())).pack(pady=30)

    # UI構築用ヘルパー
    def _create_slider(self, parent, title, stick, is_dz):
        frame = ctk.CTkFrame(parent)
        frame.pack(pady=5, padx=10, fill="x")
        max_val = 50 if is_dz else 99
        min_val = 0 if is_dz else 1
        default_val = 7 if is_dz else 55

        lbl_frame = ctk.CTkFrame(frame, fg_color="transparent")
        lbl_frame.pack(fill="x", padx=10)
        ctk.CTkLabel(lbl_frame, text=title, font=("Arial", 12, "bold")).pack(side="left")
        val_lbl = ctk.CTkLabel(lbl_frame, text=str(default_val))
        val_lbl.pack(side="right")

        def on_slide(value):
            v = int(value)
            val_lbl.configure(text=str(v))
            if is_dz: run_async(self.controller.set_deadzone_raw(stick, v))
            else: run_async(self.controller.set_sensitivity_raw(stick, v))

        slider = ctk.CTkSlider(frame, from_=min_val, to=max_val, number_of_steps=max_val-min_val, command=on_slide)
        slider.set(default_val)
        slider.pack(pady=5, padx=10, fill="x")

    # アクション
    def on_apply_chroma(self):
        try:
            r, g, b = int(self.r_entry.get()), int(self.g_entry.get()), int(self.b_entry.get())
        except ValueError:
            r, g, b = 255, 255, 255
        run_async(self.controller.set_chroma(self.chroma_mode.get(), r, g, b))

    def on_connect_click(self):
        self.connect_btn.configure(state="disabled", text=self.t.get("btn_connecting"))
        run_async(self._connect_task())

    async def _connect_task(self):
        if await self.controller.connect():
            self.status_label.configure(text=self.t.get("status_connected"))
            self.connect_btn.configure(text=self.t.get("btn_disconnect"), command=self.on_disconnect_click, state="normal")
            self.update_tip_visibility() # 接続成功したらTipsを隠す
        else:
            self.connect_btn.configure(state="normal", text=self.t.get("btn_failed"))

    def on_disconnect_click(self):
        run_async(self.controller.disconnect())
        self.status_label.configure(text=self.t.get("status_disconnected"))
        self.connect_btn.configure(text=self.t.get("btn_connect"), command=self.on_connect_click)
        self.update_tip_visibility() # 切断されたらTipsを再表示する

if __name__ == "__main__":
    app = GUIApp()
    app.mainloop()