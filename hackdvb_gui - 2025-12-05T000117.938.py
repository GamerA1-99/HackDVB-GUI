import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
import json
import subprocess
import os
import threading
import re
import queue
import tempfile
import shutil
import webbrowser
from datetime import datetime, timedelta
import xml.sax.saxutils
import xml.etree.ElementTree as ET

class TextContextMenu:
    """A class to add a right-click context menu to Text and Entry widgets."""
    def __init__(self, master):
        self.master = master
        self.menu = tk.Menu(master, tearoff=0)
        self.menu.add_command(label="Cut", command=self.cut)
        self.menu.add_command(label="Copy", command=self.copy)
        self.menu.add_command(label="Paste", command=self.paste)
        self.master.bind("<Button-3>", self.show_menu)

    def show_menu(self, event):
        # Disable Cut/Paste for read-only widgets
        if self.master.cget('state') == 'disabled' or self.master.cget('state') == 'readonly':
            self.menu.entryconfig("Cut", state="disabled")
            self.menu.entryconfig("Paste", state="disabled")
        else:
            self.menu.entryconfig("Cut", state="normal")
            self.menu.entryconfig("Paste", state="normal")

        self.menu.post(event.x_root, event.y_root)

    def cut(self):
        self.master.event_generate("<<Cut>>")

    def copy(self):
        self.master.event_generate("<<Copy>>")

    def paste(self):
        self.master.event_generate("<<Paste>>")

def make_readonly(widget):
    """Makes a text widget read-only but allows selection and copying."""
    widget.bind("<KeyPress>", lambda e: "break")

class ToolTip:
    """
    Create a tooltip for a given widget.
    """
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.id = None
        self.x = self.y = 0
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hidetip()

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(500, self.showtip)

    def unschedule(self):
        id = self.id
        self.id = None
        if id:
            self.widget.after_cancel(id)

    def showtip(self, event=None):
        x = y = 0
        try:
            # For widgets like Entry, Text with an insert cursor
            x, y, cx, cy = self.widget.bbox("insert")
            x += self.widget.winfo_rootx() + 25
            y += self.widget.winfo_rooty() + 20
        except (tk.TclError, TypeError):
            # For other widgets, position relative to the mouse pointer
            x = self.widget.winfo_pointerx() + 15
            y = self.widget.winfo_pointery() + 10
        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify='left',
                       background="#ffffe0", relief='solid', borderwidth=1,
                       font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)

    def hidetip(self):
        tw = self.tooltip_window
        self.tooltip_window = None
        if tw:
            tw.destroy()

class HackDvbGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw() # Hide main window until dependencies are checked

        # --- Executable Paths (must be defined before dependency checks) ---
        self.ffmpeg_path = tk.StringVar(value="ffmpeg")
        self.tsp_path = tk.StringVar(value="tsp")
        self.tdt_path = tk.StringVar(value="tdt.exe")


        self.title("HackDVB GUI")
        self.geometry("900x750")

        self.cuda_supported = False # Will be determined after dependency check
        self.qsv_supported = False  # Will be determined after dependency check
        self.process = None
        self.log_queue = queue.Queue()
        self.tdt_process = None
        self.channels = []
        self.tool_process = None
        self.epg_events = [] # To store EPG event data

        self.subtitle_size_map = {
            "Small": "18",
            "Medium": "24",
            "Large": "36",
            "X-Large": "48"
        }

        # Register validation commands
        self.numeric_validate_cmd = self.register(self._validate_numeric_input)
        self.hex_validate_cmd = self.register(self._validate_hex_input)

        # --- UI Theme and Style ---
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except tk.TclError:
            # 'clam' theme may not be available on all systems
            pass

        # -- Colors --
        BG_COLOR = "#f7f7f7"
        TEXT_COLOR = "#333333"
        HEADER_COLOR = "#005f9e"
        ACCENT_COLOR = "#0078d4"
        SUCCESS_COLOR = "#107c10"
        DISABLED_BG = "#e9e9e9"
        
        self.configure(bg=BG_COLOR)

        style.configure(".", background=BG_COLOR, foreground=TEXT_COLOR, font=("Segoe UI", 9))
        style.configure("TLabel", padding=5)
        style.configure("TButton", padding=6, font=("Segoe UI", 9, "bold"))
        style.configure("TEntry", padding=5)
        style.configure("TCombobox", padding=5)
        style.configure("Success.TButton", foreground="white", background=SUCCESS_COLOR)
        style.map("Success.TButton", background=[('active', '#0d630d')])
        style.configure("TFrame", background=BG_COLOR)
        style.configure("TLabelframe", padding=10, background=BG_COLOR)
        style.configure("Header.TLabel", font=("Segoe UI", 13, "bold"), foreground=HEADER_COLOR)
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"), foreground=TEXT_COLOR)
        style.map("TCombobox", fieldbackground=[('readonly', 'white')])

        style.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=[10, 5])
        style.configure("Action.TFrame", background="#e0e0e0")
        style.configure("Action.TLabel", background="#e0e0e0", font=("Segoe UI", 9, "bold"))

        style.configure("Card.TLabelframe", borderwidth=1, relief="solid", bordercolor="#dcdcdc")
        style.configure("Card.TLabelframe.Label", foreground=TEXT_COLOR)

        style.map("TNotebook.Tab", background=[("selected", BG_COLOR)], foreground=[("selected", ACCENT_COLOR)])
        
        # --- Main Frame ---
        # --- Menu Bar ---
        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Save Configuration", command=self.save_configuration)
        filemenu.add_command(label="Load Configuration", command=self.load_configuration)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=filemenu)

        settingsmenu = tk.Menu(menubar, tearoff=0)
        settingsmenu.add_command(label="Set FFmpeg Path...", command=lambda: self.browse_for_executable(self.ffmpeg_path, "FFmpeg"))
        settingsmenu.add_command(label="Set TSDuck (tsp) Path...", command=lambda: self.browse_for_executable(self.tsp_path, "TSDuck (tsp)"))
        settingsmenu.add_command(label="Set TDT Injector Path...", command=lambda: self.browse_for_executable(self.tdt_path, "TDT Injector"))
        menubar.add_cascade(label="Settings", menu=settingsmenu)

        # --- Help Menu ---
        helpmenu = tk.Menu(menubar, tearoff=0)
        helpmenu.add_command(label="About...", command=self.show_about_dialog)
        helpmenu.add_command(label="Dependencies...", command=self.show_dependencies_dialog)
        menubar.add_cascade(label="Help", menu=helpmenu)

        self.config(menu=menubar)
        main_frame = ttk.Frame(self, padding=(10, 10, 10, 0))
        main_frame.pack(fill=tk.BOTH, expand=True)        
        main_frame.grid_columnconfigure(0, weight=1) # The main paned window will be in column 0
        main_frame.grid_rowconfigure(0, weight=1) # The main paned window will be in row 0

        # --- Main Vertical Paned Window ---
        # This will hold the notebook (top) and the command/log section (bottom)
        main_paned_window = ttk.PanedWindow(main_frame, orient=tk.VERTICAL)
        main_paned_window.grid(row=0, column=0, sticky="nsew")

        # --- Tabbed Interface ---
        # The notebook is now placed inside the main_paned_window instead of main_frame
        notebook_frame = ttk.Frame(main_paned_window) # A container for the notebook
        notebook = ttk.Notebook(notebook_frame)
        notebook.pack(fill=tk.BOTH, expand=True)
        main_paned_window.add(notebook_frame, weight=2) # Give tabs more initial space

        # -- Inputs Tab --
        self.inputs_tab = self._create_tab(notebook, "Inputs")
        self.inputs_tab.grid_rowconfigure(0, weight=1)
        self.inputs_tab.grid_columnconfigure(0, weight=1)

        inputs_canvas_frame = ttk.Frame(self.inputs_tab)
        inputs_canvas_frame.grid(row=0, column=0, sticky='nsew')
        inputs_canvas_frame.grid_rowconfigure(0, weight=1)
        inputs_canvas_frame.grid_columnconfigure(0, weight=1)

        self.inputs_canvas = tk.Canvas(inputs_canvas_frame, borderwidth=0, highlightthickness=0)
        self.inputs_scrollbar = ttk.Scrollbar(inputs_canvas_frame, orient="vertical", command=self.inputs_canvas.yview)
        self.scrollable_inputs_frame = ttk.Frame(self.inputs_canvas, padding=(0,0))

        self.scrollable_inputs_frame.bind("<Configure>", lambda e: self.inputs_canvas.configure(scrollregion=self.inputs_canvas.bbox("all")))
        self.inputs_canvas.create_window((0, 0), window=self.scrollable_inputs_frame, anchor="nw")
        self.inputs_canvas.configure(yscrollcommand=self.inputs_scrollbar.set)

        self.inputs_canvas.grid(row=0, column=0, sticky='nsew')
        self.inputs_scrollbar.grid(row=0, column=1, sticky='ns')

        self.inputs_frame = ttk.Frame(self.scrollable_inputs_frame, padding=(0,0))
        self.inputs_frame.grid(row=0, column=0, sticky='nsew')
        # Configure a 4-column grid for the input cards
        self.inputs_frame.grid_columnconfigure(0, weight=1)
        self.inputs_frame.grid_columnconfigure(1, weight=1)

        eit_frame = ttk.Labelframe(self.scrollable_inputs_frame, text="EIT Data", padding=10, style="Card.TLabelframe")
        eit_frame.grid(row=1, column=0, sticky='ew', pady=(10,0), padx=(0,15))
        eit_frame.grid_columnconfigure(1, weight=1)
        eit_frame.grid_rowconfigure(0, pad=5)

        eit_filetypes = [("XML files", "*.xml"), ("All files", "*.*")]
        _, eit_entry, eit_browse_btn, self.eit_path = self.create_file_input_widgets(eit_frame, "EIT XML File:", 0, filetypes=eit_filetypes)
        # Adjust grid to make space for the new button
        eit_entry.grid(columnspan=1)
        eit_browse_btn.grid(column=2)
        epg_editor_btn = ttk.Button(eit_frame, text="Create/Edit EPG...", command=self.open_epg_editor)
        epg_editor_btn.grid(row=0, column=3, sticky="w", padx=(5, 5))
        ToolTip(eit_frame.winfo_children()[1], "Optional: Path to an XMLTV file for EIT (Event Information Table) data.")
        delete_eit_btn = ttk.Button(eit_frame, text="✖", command=self.delete_eit_file, width=3)
        delete_eit_btn.grid(row=0, column=4, sticky="w")
        ToolTip(delete_eit_btn, "Delete the temporary EPG file and clear the path.")

        # -- Services Tab --
        self.services_tab = self._create_tab(notebook, "Services")
        self.services_tab.grid_rowconfigure(1, weight=1)
        self.services_tab.grid_columnconfigure(0, weight=1)

        add_channel_button = ttk.Button(self.services_tab, text="✚ Add Channel", command=self.add_channel)        
        ToolTip(add_channel_button, "Add a new service (channel) to the multiplex.")
        add_channel_button.grid(row=0, column=0, sticky='w', pady=(0,10))

        # --- Scrollable area for services ---
        canvas_frame = ttk.Frame(self.services_tab)
        canvas_frame.grid(row=1, column=0, columnspan=3, sticky='nsew')
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)

        self.service_canvas = tk.Canvas(canvas_frame, borderwidth=0, highlightthickness=0)
        self.service_scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.service_canvas.yview)
        self.scrollable_service_frame = ttk.Frame(self.service_canvas, padding=(10,0))
        
        # Configure a 2-column grid for the service cards
        self.scrollable_service_frame.grid_columnconfigure(0, weight=1)
        self.scrollable_service_frame.grid_columnconfigure(1, weight=1)
        self.scrollable_service_frame.grid_columnconfigure(2, weight=1)

        self.scrollable_service_frame.bind("<Configure>", lambda e: self.service_canvas.configure(scrollregion=self.service_canvas.bbox("all")))
        self.service_canvas.create_window((0, 0), window=self.scrollable_service_frame, anchor="nw")
        self.service_canvas.configure(yscrollcommand=self.service_scrollbar.set)

        self.service_canvas.grid(row=0, column=0, sticky='nsew')
        self.service_scrollbar.grid(row=0, column=1, sticky='ns')
        self.bind_all("<MouseWheel>", self._on_mousewheel)

        # -- Encoding Tab --
        encoding_tab = self._create_tab(notebook, "Encoding & Muxing")
        encoding_tab.grid_columnconfigure(0, weight=1) # Allow content to expand horizontally

        encoding_frame = ttk.Labelframe(encoding_tab, text="Bitrates", padding=(15, 10), style="Card.TLabelframe")
        encoding_frame.grid(row=0, column=0, sticky='ew', pady=(0, 5))
        encoding_frame.grid_columnconfigure(1, weight=1)

        _, video_bitrate_entry, self.video_bitrate = self.create_text_input_widgets(encoding_frame, "Video Bitrate (k):", 0, "6000", validation_type="numeric")
        ToolTip(video_bitrate_entry, "Target video bitrate in kilobits per second for each service (e.g., 6000 for 6 Mbps).")

        # The audio bitrate input was moved to the new Audio Encoding frame.
        # We can hide the now-empty row to keep the layout clean.
        encoding_frame.grid_rowconfigure(1, pad=0) # Hide the old audio bitrate row

        # --- Audio Encoding Frame ---
        audio_opts_frame = ttk.Labelframe(encoding_tab, text="Audio Encoding", padding=(15, 10))
        audio_opts_frame.grid(row=1, column=0, sticky='ew', pady=5)
        audio_opts_frame.grid_columnconfigure(1, weight=1)

        # --- Data for dynamic audio options ---
        self.audio_options_map = {
            "mp2": {
                "bitrates": ["128", "192", "224", "256", "320", "384"],
                "samplerates": ["48000", "44100", "32000"],
                "default_bitrate": "192"
            },
            "ac3": {
                "bitrates": ["192", "224", "256", "320", "384", "448", "640"],
                "samplerates": ["48000", "44100", "32000"],
                "default_bitrate": "384"
            },
            "aac": {
                "bitrates": ["96", "128", "160", "192", "256", "320"],
                "samplerates": ["48000", "44100", "32000", "24000", "22050"],
                "default_bitrate": "128"
            },
            "eac3": {
                "bitrates": ["192", "224", "256", "384", "448", "640"],
                "samplerates": ["48000"],
                "default_bitrate": "224"
            }
        }
        default_codec = "mp2"
        _, self.audio_codec_combobox, self.audio_codec = self.create_combobox_input_widgets(audio_opts_frame, "Audio Codec:", 0, default_codec, list(self.audio_options_map.keys()))
        self.audio_codec.trace_add("write", self.update_audio_options)
        ToolTip(self.audio_codec_combobox, "The audio compression standard to use for all services.\n- mp2: Standard for DVB-S/T.\n- ac3: Dolby Digital.\n- aac: Advanced Audio Coding.\n- eac3: Dolby Digital Plus.")
        _, self.audio_bitrate_combobox, self.audio_bitrate = self.create_combobox_input_widgets(audio_opts_frame, "Audio Bitrate (k):", 1, "192", [])
        ToolTip(self.audio_bitrate_combobox, "Target audio bitrate in kilobits per second for each service.")
        _, self.audio_samplerate_combobox, self.audio_samplerate = self.create_combobox_input_widgets(audio_opts_frame, "Sample Rate (Hz):", 2, "48000", [])
        ToolTip(self.audio_samplerate_combobox, "The audio sample rate. 48000 Hz is standard for digital video.")
        
        # Call once to populate initial values
        self.update_audio_options()

        self.use_loudnorm_var = tk.BooleanVar(value=True)
        loudnorm_checkbox = ttk.Checkbutton(audio_opts_frame, text="Enable Loudness Normalization (EBU R128)", variable=self.use_loudnorm_var, command=self.update_command_preview)
        loudnorm_checkbox.grid(row=3, column=0, columnspan=3, sticky='w', pady=(5,0))
        ToolTip(loudnorm_checkbox, "Enable to normalize audio loudness to broadcast standards (EBU R128).\nDisable this if you experience lag or stuttering during broadcast, as it can be CPU intensive.")

        self.video_format_map = {
            # --- PAL/25 FPS Based ---
            "720x576i @ 25 fps (PAL SD)": ("720x576", "tt", "25"),
            "720x576p @ 25 fps (PAL SD)": ("720x576", "prog", "25"),
            "1280x720p @ 25 fps (HD)": ("1280x720", "prog", "25"),
            "1920x1080i @ 25 fps (Full HD)": ("1920x1080", "tt", "25"),
            "1920x1080p @ 25 fps (Full HD)": ("1920x1080", "prog", "25"),
            # --- NTSC/29.97 FPS Based ---
            "720x480i @ 29.97 fps (NTSC SD)": ("720x480", "bb", "30000/1001"),
            "720x480p @ 29.97 fps (NTSC SD)": ("720x480", "prog", "30000/1001"),
            "1280x720p @ 29.97 fps (HD)": ("1280x720", "prog", "30000/1001"),
            "1920x1080i @ 29.97 fps (Full HD)": ("1920x1080", "tt", "30000/1001"),
            "1920x1080p @ 29.97 fps (Full HD)": ("1920x1080", "prog", "30000/1001"),
            # --- Film/24 FPS Based ---
            "1920x1080p @ 24 fps (Full HD)": ("1920x1080", "prog", "24"),
            "3840x2160p @ 24 fps (4K UHD)": ("3840x2160", "prog", "24"),
            "4096x2160p @ 24 fps (DCI 4K)": ("4096x2160", "prog", "24"),
            # --- High Frame Rate ---
            "1280x720p @ 50 fps (HD)": ("1280x720", "prog", "50"),
            "1920x1080p @ 50 fps (Full HD)": ("1920x1080", "prog", "50"),
            "1280x720p @ 59.94 fps (HD)": ("1280x720", "prog", "60000/1001"),
            "1920x1080p @ 59.94 fps (Full HD)": ("1920x1080", "prog", "60000/1001"),
            "3840x2160p @ 50 fps (4K UHD)": ("3840x2160", "prog", "50"),
            "3840x2160p @ 59.94 fps (4K UHD)": ("3840x2160", "prog", "60000/1001"),
        }

        self.language_map = {
            # Common European
            "English": "eng", "German": "ger", "French": "fre", "Spanish": "spa",
            "Italian": "ita", "Portuguese": "por", "Dutch": "dut", "Swedish": "swe",
            "Danish": "dan", "Norwegian": "nor", "Finnish": "fin", "Polish": "pol",
            "Russian": "rus", "Greek": "gre", "Czech": "cze", "Slovak": "slo",
            "Hungarian": "hun", "Romanian": "rum", "Bulgarian": "bul", "Croatian": "hrv",
            "Serbian": "srp", "Slovenian": "slv", "Estonian": "est", "Latvian": "lav",
            "Lithuanian": "lit", "Icelandic": "ice", "Irish": "gle", "Welsh": "cym",
            "Basque": "baq", "Catalan": "cat", "Galician": "glg",
            # Common World
            "Arabic": "ara", "Chinese": "chi", "Japanese": "jpn", "Korean": "kor",
            "Hindi": "hin", "Turkish": "tur", "Hebrew": "heb", "Thai": "tha",
            "Vietnamese": "vie", "Indonesian": "ind", "Malay": "msa", "Tagalog": "tgl",
            "Persian": "per", "Urdu": "urd", "Bengali": "ben", "Tamil": "tam",
            "Telugu": "tel", "Marathi": "mar", "Swahili": "swa",
            # Other
            "Ukrainian": "ukr",
            "Undetermined": "und"
        }
        # Sort languages alphabetically but keep "Undetermined" at the end
        sorted_langs = sorted([lang for lang in self.language_map.keys() if lang != "Undetermined"])
        sorted_langs.append("Undetermined")

        video_opts_frame = ttk.Labelframe(encoding_tab, text="Video Encoding", padding=(15, 10), style="Card.TLabelframe")
        video_opts_frame.grid(row=2, column=0, sticky='ew', pady=5)
        video_opts_frame.grid_columnconfigure(1, weight=1)

        hw_accel_frame = ttk.Frame(video_opts_frame)
        hw_accel_frame.grid(row=0, column=0, columnspan=3, sticky='w', pady=(0,10))

        self.use_cuda_var = tk.BooleanVar(value=False)
        self.cuda_checkbox = ttk.Checkbutton(hw_accel_frame, text="Use NVIDIA CUDA", variable=self.use_cuda_var, command=self.update_hw_accel_options)
        self.cuda_checkbox.pack(side=tk.LEFT, padx=(0, 15))

        if self.cuda_supported:
            ToolTip(self.cuda_checkbox, "Enable to use your NVIDIA GPU for video encoding (NVENC).\nThis significantly reduces CPU usage and can improve performance.")
        else:
            self.use_cuda_var.set(False)
            self.cuda_checkbox.config(state=tk.DISABLED)
            ToolTip(self.cuda_checkbox, "Disabled: No compatible NVIDIA GPU/drivers found, or FFmpeg lacks NVENC support.")

        self.use_qsv_var = tk.BooleanVar(value=False)
        self.qsv_checkbox = ttk.Checkbutton(hw_accel_frame, text="Use Intel QSV", variable=self.use_qsv_var, command=self.update_hw_accel_options)
        self.qsv_checkbox.pack(side=tk.LEFT)
        if self.qsv_supported:
            ToolTip(self.qsv_checkbox, "Enable to use your Intel integrated GPU for video encoding (Quick Sync Video).\nThis significantly reduces CPU usage.")
        else:
            self.use_qsv_var.set(False)
            self.qsv_checkbox.config(state=tk.DISABLED)
            ToolTip(self.qsv_checkbox, "Disabled: No compatible Intel CPU/drivers found, or FFmpeg lacks QSV support.")

        self.video_codec_map = {
            "software": [
                "mpeg2video", # DVB Standard
                "libx264",    # High-quality H.264/AVC
                "libx265",    # High-quality H.265/HEVC
                "mpeg4",      # MPEG-4 Part 2
                "libvpx-vp9", # VP9
            ],
            "cuda": [
                "h264_nvenc",  # H.264/AVC
                "hevc_nvenc",  # H.265/HEVC
            ],
            "qsv": [
                "h264_qsv",
                "hevc_qsv",
            ]
        }
        self.preset_map = {
            "software": [
                "ultrafast", "superfast", "veryfast", "faster", "fast",
                "medium", "slow", "slower", "veryslow"
            ],
            "cuda": [
                "p1 (fastest)", "p2", "p3", "p4 (medium)", "p5", "p6", "p7 (slowest)"
            ],
            "qsv": [
                "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"
            ]
        }

        default_video_codec = "mpeg2video"
        _, self.video_codec_combobox, self.video_codec = self.create_combobox_input_widgets(video_opts_frame, "Video Codec:", 1, default_video_codec, self.video_codec_map["software"])
        ToolTip(self.video_codec_combobox, "The video compression standard to use for all services.")

        default_preset = "medium"
        _, self.preset_combobox, self.preset = self.create_combobox_input_widgets(video_opts_frame, "Codec Preset:", 2, default_preset, self.preset_map["software"])
        ToolTip(self.preset_combobox, "Controls the encoding speed vs. compression efficiency.\nFaster presets use less CPU/GPU but have lower quality.\nSlower presets use more CPU/GPU for better quality.")

        # Pixel Format
        self.pix_fmt_options = ["yuv420p", "yuv422p", "yuv420p10le", "yuv422p10le"]
        default_pix_fmt = "yuv420p"
        _, self.pix_fmt_combobox, self.pix_fmt = self.create_combobox_input_widgets(video_opts_frame, "Pixel Format:", 3, default_pix_fmt, self.pix_fmt_options)
        ToolTip(self.pix_fmt_combobox, "The pixel format (chroma subsampling and bit depth).\n- yuv420p: 8-bit, 4:2:0 (Most common)\n- yuv422p: 8-bit, 4:2:2\n- yuv420p10le: 10-bit, 4:2:0 (For HEVC)")

        video_opts_frame.grid_rowconfigure(0, pad=5) # cuda checkbox
        video_opts_frame.grid_rowconfigure(1, pad=5) # codec
        video_opts_frame.grid_rowconfigure(2, pad=5) # preset
        video_opts_frame.grid_rowconfigure(3, pad=5) # pix_fmt
        video_opts_frame.grid_rowconfigure(4, pad=5) # aspect
        video_opts_frame.grid_rowconfigure(5, pad=5) # bframes
        video_opts_frame.grid_rowconfigure(6, pad=5) # format

        _, self.aspect_ratio_combobox, self.aspect_ratio = self.create_combobox_input_widgets(video_opts_frame, "Aspect Ratio:", 4, "16:9", ["16:9", "4:3"])
        ToolTip(self.aspect_ratio_combobox, "The display aspect ratio for the video streams.")

        self.use_bframes_var = tk.BooleanVar(value=True)
        bframes_checkbox = ttk.Checkbutton(video_opts_frame, text="Enable B-Frames", variable=self.use_bframes_var, command=self.update_command_preview)
        bframes_checkbox.grid(row=5, column=0, columnspan=3, sticky='w')
        ToolTip(bframes_checkbox, "Enable B-Frames for video encoding. Disabling this adds '-bf 0' to the command, which can improve compatibility but may reduce quality/efficiency.")

        default_format = "720x576i @ 25 fps (PAL SD)"
        _, self.video_format_combobox, self.video_format_display = self.create_combobox_input_widgets(video_opts_frame, "Video Format:", 6, default_format, list(self.video_format_map.keys()))
        ToolTip(self.video_format_combobox, "Select the output resolution, scan type, and frame rate.")

        # -- Output Tab --
        output_tab = self._create_tab(notebook, "DVB Broadcast")
        output_tab.grid_columnconfigure(0, weight=1) # Allow content to expand horizontally

        dektec_frame = ttk.Labelframe(output_tab, text="DVB-S/S2 Output", padding=(15, 10), style="Card.TLabelframe")
        dektec_frame.grid(row=0, column=0, sticky='ew')
        dektec_frame.grid_columnconfigure(1, weight=1)
        dektec_frame.grid_rowconfigure(0, pad=5)
        dektec_frame.grid_rowconfigure(1, pad=5)
        dektec_frame.grid_rowconfigure(2, pad=5)
        dektec_frame.grid_rowconfigure(3, pad=5)
        dektec_frame.grid_rowconfigure(4, pad=5)
        dektec_frame.grid_rowconfigure(5, pad=5)
        dektec_frame.grid_rowconfigure(6, pad=5)
        dektec_frame.grid_rowconfigure(7, pad=5)
        video_opts_frame.grid_rowconfigure(6, pad=5) # format

        _, dek_device_entry, self.dek_device = self.create_text_input_widgets(dektec_frame, "Device Index:", 0, "0", validation_type="numeric", columnspan=3)
        ToolTip(dek_device_entry, "The index of the DekTec output device (usually 0 or 1).")

        self.dvb_standard_options = ["DVB-S", "DVB-S2"]
        _, dvb_standard_combobox, self.dvb_standard = self.create_combobox_input_widgets(dektec_frame, "Standard:", 1, "DVB-S", self.dvb_standard_options)
        ToolTip(dvb_standard_combobox, "The DVB transmission standard. DVB-S2 offers better efficiency.")
        self.dvb_standard.trace_add("write", self.update_dvb_options)

        self.mod_options = {
            "DVB-S": ["DVB-S-QPSK"],
            "DVB-S2": ["DVB-S2-QPSK", "DVB-S2-8PSK", "DVB-S2-16APSK", "DVB-S2-32APSK"]
        }
        _, self.dek_mod_combobox, self.dek_mod_var = self.create_combobox_input_widgets(dektec_frame, "Modulation:", 2, self.mod_options["DVB-S"][0], self.mod_options["DVB-S"])
        ToolTip(self.dek_mod_combobox, "The modulation scheme. Options depend on the selected standard.")
        
        self.lnb_lo_options = ["10600", "9750"]
        _, lnb_lo_freq_combobox, self.lnb_lo_freq = self.create_combobox_input_widgets(dektec_frame, "LNB LO (MHz):", 3, "10600", self.lnb_lo_options)
        ToolTip(lnb_lo_freq_combobox, "The Local Oscillator frequency of your LNB (e.g., Universal LNB uses 9750 for low band, 10600 for high band).")
        self.lnb_lo_freq.trace_add("write", self._validate_frequency_range)

        dek_freq_label, self.dek_freq_entry, self.dek_freq = self.create_text_input_widgets(dektec_frame, "Frequency (MHz):", 4, "11797", validation_type="numeric")
        self.dek_freq_entry.grid(columnspan=1)
        ToolTip(self.dek_freq_entry, "The target satellite frequency in MHz. The valid range depends on the LNB LO.")
        self.dek_freq.trace_add("write", self._validate_frequency_range)
        self.freq_warning_label = ttk.Label(dektec_frame, text="", foreground="red")
        self.freq_warning_label.grid(row=4, column=2, columnspan=2, sticky="w", padx=(5,0))

        _, dek_symrate_entry, self.dek_symrate = self.create_text_input_widgets(dektec_frame, "Symbol Rate (S/s):", 5, "27500000", validation_type="numeric", columnspan=3)
        ToolTip(dek_symrate_entry, "The symbol rate (baud rate) of the signal in Symbols per second.")

        self.fec_options = {
            "DVB-S": ["1/2", "2/3", "3/4", "5/6", "7/8"],
            "DVB-S2": ["1/4", "1/3", "2/5", "1/2", "3/5", "2/3", "3/4", "4/5", "5/6", "8/9", "9/10"]
        }
        # Default to 3/4 which is valid for DVB-S
        _, self.dek_fec_combobox, self.dek_fec_var = self.create_combobox_input_widgets(dektec_frame, "FEC:", 6, "3/4", self.fec_options["DVB-S"])
        ToolTip(self.dek_fec_combobox, "Forward Error Correction rate. Options depend on the selected standard.")
        
        # Mux Rate with Auto-Calculate
        mux_rate_label = ttk.Label(dektec_frame, text="Mux Rate (bps):")
        mux_rate_label.grid(row=7, column=0, sticky="w")
        self.mux_rate_var = tk.StringVar(value="33790800")
        mux_rate_entry = ttk.Entry(dektec_frame, textvariable=self.mux_rate_var, validate="key", validatecommand=(self.numeric_validate_cmd, '%P'))
        ToolTip(mux_rate_entry, "The total bitrate of the transport stream. Can be auto-calculated.")
        mux_rate_entry.grid(row=7, column=1, sticky="ew")
        calc_button = ttk.Button(dektec_frame, text="Auto-Calculate", command=self.calculate_mux_rate)
        ToolTip(calc_button, "Calculate the theoretical maximum mux rate based on current DVB parameters.")
        calc_button.grid(row=7, column=2, sticky="w", padx=(5,0))
        self.mux_rate_mbps_label = ttk.Label(dektec_frame, text="")
        self.mux_rate_mbps_label.grid(row=7, column=3, sticky="w", padx=(5,0))

        self.calculate_mux_rate() # Initial calculation

        # --- Time Synchronization Frame ---
        time_sync_frame = ttk.Labelframe(output_tab, text="Time Synchronization", padding=(15, 10), style="Card.TLabelframe")
        time_sync_frame.grid(row=1, column=0, sticky='ew', pady=(10, 0))
        time_sync_frame.grid_columnconfigure(1, weight=1)

        tdt_options = ["127.0.0.1:32000", "localhost:32000"]
        _, tdt_source_combobox, self.tdt_source = self.create_combobox_input_widgets(time_sync_frame, "TDT Source:", 0, tdt_options[0], tdt_options)
        ToolTip(tdt_source_combobox, "The source address for the external TDT/TOT injector.\nThis is used by the 'tsp -P datainject' plugin.")

        # -- Tools Tab (Moved to the end) --
        self.tools_tab = self._create_tab(notebook, "Tools")
        self.tools_tab.grid_columnconfigure(0, weight=1)
        self.tools_tab.grid_rowconfigure(0, weight=1)
        self._create_media_tools_ui(self.tools_tab)

        # --- Bottom Pane for Command and Log ---
        # This frame will be the bottom part of the main_paned_window
        bottom_pane_container = ttk.Frame(main_paned_window, padding=(0, 10, 0, 5))
        main_paned_window.add(bottom_pane_container, weight=1)
        bottom_pane_container.grid_columnconfigure(0, weight=1)
        bottom_pane_container.grid_rowconfigure(0, weight=1)

        # This PanedWindow is now inside the bottom_pane_container
        paned_window = ttk.PanedWindow(bottom_pane_container, orient=tk.VERTICAL)
        paned_window.grid(row=0, column=0, sticky="nsew")

        # --- Command Preview Pane ---
        cmd_pane_frame = ttk.Frame(paned_window, padding=0)
        paned_window.add(cmd_pane_frame, weight=1)
        cmd_pane_frame.grid_rowconfigure(1, weight=1)
        cmd_pane_frame.grid_columnconfigure(0, weight=1)

        cmd_header_frame = self.create_section_header(cmd_pane_frame, "Generated Command")
        self.preview_button = ttk.Button(cmd_header_frame, text="Preview Command", command=self.update_command_preview, style="Toolbutton")
        ToolTip(self.preview_button, "Refresh the FFmpeg and TSP command preview below.")
        self.preview_button.pack(side=tk.RIGHT, padx=(10,0))

        self.command_preview = tk.Text(cmd_pane_frame, height=6, wrap=tk.WORD, bg="black", fg="white", relief=tk.SUNKEN, borderwidth=1, insertbackground="white")
        self.command_preview.grid(row=1, column=0, sticky="nsew")
        make_readonly(self.command_preview)
        TextContextMenu(self.command_preview)

        # --- Log Output Pane ---
        log_pane_frame = ttk.Frame(paned_window, padding=0)
        paned_window.add(log_pane_frame, weight=3) # Give log more initial space
        log_pane_frame.grid_rowconfigure(1, weight=1)
        log_pane_frame.grid_columnconfigure(0, weight=1)

        log_header_frame = self.create_section_header(log_pane_frame, "Live Log")
        
        self.clear_log_button = ttk.Button(log_header_frame, text="Clear Log", command=self.clear_log, style="Toolbutton")
        ToolTip(self.clear_log_button, "Clear the log output window.")
        self.clear_log_button.pack(side=tk.RIGHT, padx=(0, 0))
        self.save_log_button = ttk.Button(log_header_frame, text="Save Log", command=self.save_log, style="Toolbutton")
        ToolTip(self.save_log_button, "Save the current log to a text file.")
        self.save_log_button.pack(side=tk.RIGHT, padx=(10, 0))

        self.log_output = ScrolledText(log_pane_frame, height=10, wrap=tk.WORD, bg="black", fg="white", relief=tk.SUNKEN, borderwidth=1, insertbackground="white")
        self.log_output.grid(row=1, column=0, sticky="nsew")
        make_readonly(self.log_output)
        TextContextMenu(self.log_output)

        # --- Action Buttons ---
        button_frame = ttk.Frame(main_frame, padding=(10, 5), style="Action.TFrame")
        button_frame.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        button_frame.grid_columnconfigure(1, weight=1)

        self.start_button = ttk.Button(button_frame, text="Start Broadcast", command=self.start_process, style="Success.TButton")
        ToolTip(self.start_button, "Start the FFmpeg and TSP processes to begin the broadcast.")
        self.start_button.pack(side=tk.LEFT, padx=(5,0))

        self.stop_button = ttk.Button(button_frame, text="Stop Broadcast", command=self.stop_process, state=tk.DISABLED)
        ToolTip(self.stop_button, "Stop all running broadcast processes.")
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        self.status_label = ttk.Label(button_frame, text="Status: Idle", style="Action.TLabel")
        self.status_label.pack(side=tk.RIGHT, padx=5) # This should be inside the button_frame

        self.add_channel() # Add the first channel by default
        self._validate_frequency_range() # Initial validation check
        self.update_command_preview() # Initial preview
        self.after(100, self.process_log_queue) # Start polling the log queue

        # Add a handler to stop processes on window close
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # --- Final Startup Step: Check Dependencies ---
        # This is done after the UI is built but before the window is shown.
        if not self.check_dependencies_on_startup():
            self.destroy() # Abort startup
            return
        
        # Now that dependencies are confirmed, update the UI based on HW support
        self.update_hw_support_ui()

        self.deiconify() # Show the main window

    def _on_mousewheel(self, event):
        # Determine which canvas is under the mouse
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except KeyError:
            # This can happen if the mouse is over a combobox's dropdown list ('popdown')
            return
        if widget is None: return
        
        # Check if the mouse is over the service canvas or one of its children
        if str(widget).startswith(str(self.service_canvas)):
            self.service_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        elif str(widget).startswith(str(self.inputs_canvas)):
            self.inputs_canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    def _validate_numeric_input(self, new_value):
        """Validates if the new_value is an integer or an empty string."""
        if new_value == "" or new_value.isdigit():
            return True
        return False

    def _validate_hex_input(self, new_value):
        """Validates if the new_value is a hexadecimal string (with or without 0x prefix) or an empty string."""
        if new_value == "":
            return True
        # Regex to match optional "0x" prefix followed by one or more hex digits
        # or just one or more hex digits.
        if re.fullmatch(r"(0x)?[0-9a-fA-F]*", new_value):
            return True
        return False

    def _validate_frequency_range(self, *args):
        """Validates that the satellite frequency is in the correct range for the LNB."""
        is_valid = True
        warning_message = ""
        try:
            lo_freq = int(self.lnb_lo_freq.get())
            sat_freq_str = self.dek_freq.get()

            if not sat_freq_str: # Don't validate if empty
                is_valid = True
            else:
                sat_freq = int(sat_freq_str)
                if lo_freq == 9750 and not (10700 <= sat_freq <= 11700):
                    is_valid = False
                    warning_message = "Range: 10700-11700 MHz"
                elif lo_freq == 10600 and not (11700 <= sat_freq <= 12750):
                    is_valid = False
                    warning_message = "Range: 11700-12750 MHz"

        except (ValueError, TclError):
            is_valid = False # Invalid number format
            warning_message = "Invalid number"

        self.freq_warning_label.config(text=warning_message)

        if is_valid:
            self.dek_freq_entry.config(style="TEntry") # Reset to default style
            if self.start_button['state'] == 'disabled' and self.process is None:
                 self.start_button.config(state=tk.NORMAL)
        else:
            self.dek_freq_entry.config(style="Error.TEntry") # Apply error style
            self.start_button.config(state=tk.DISABLED)
        return False

    def create_section_header(self, parent, text):
        row = parent.grid_size()[1]
        header_frame = ttk.Frame(parent, padding=0)
        header_frame.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 2))
        label = ttk.Label(header_frame, text=text.upper(), style="Header.TLabel")
        label.pack(side=tk.LEFT)
        return header_frame

    def _create_tab(self, notebook, text):
        """Creates a tab in the notebook."""
        tab_frame = ttk.Frame(notebook, padding=(10, 15))
        notebook.add(tab_frame, text=text)
        return tab_frame

    def create_file_input_widgets(self, parent, label_text, row, filetypes=None):
        label = ttk.Label(parent, text=label_text)
        label.grid(row=row, column=0, sticky="w")
        entry_var = tk.StringVar()
        entry = ttk.Entry(parent, textvariable=entry_var)
        entry.grid(row=row, column=1, sticky="ew")
        TextContextMenu(entry)
        button = ttk.Button(parent, text="Browse...", command=lambda: self.browse_file(entry_var, filetypes=filetypes))
        button.grid(row=row, column=2, sticky="w", padx=(5, 0))
        return label, entry, button, entry_var

    def create_file_input(self, parent, label_text, row):
        _, _, _, entry_var = self.create_file_input_widgets(parent, label_text, row)
        return entry_var

    def create_text_input_widgets(self, parent, label_text, row, default_value="", validation_type=None, columnspan=1, grid_column_offset=0):
        label = ttk.Label(parent, text=label_text)
        label.grid(row=row, column=0 + grid_column_offset, sticky="w")
        entry_var = tk.StringVar(value=default_value)
        
        if validation_type == "numeric":
            entry = ttk.Entry(parent, textvariable=entry_var, validate="key", validatecommand=(self.numeric_validate_cmd, '%P'))
        elif validation_type == "hex":
            entry = ttk.Entry(parent, textvariable=entry_var, validate="key", validatecommand=(self.hex_validate_cmd, '%P'))
        else:
            entry = ttk.Entry(parent, textvariable=entry_var)
            
        entry.grid(row=row, column=1 + grid_column_offset, columnspan=columnspan, sticky="ew")
        TextContextMenu(entry)
        return label, entry, entry_var

    def create_text_input(self, parent, label_text, row, default_value="", validation_type=None, columnspan=1, grid_column_offset=0):
        _, _, entry_var = self.create_text_input_widgets(parent, label_text, row, default_value, validation_type, columnspan, grid_column_offset)
        return entry_var

    def create_combobox_input(self, parent, label_text, row, default_value, options, grid_column_offset=0):
        _, _, entry_var = self.create_combobox_input_widgets(parent, label_text, row, default_value, options, grid_column_offset)
        return entry_var

    def create_combobox_input_widgets(self, parent, label_text, row, default_value, options, grid_column_offset=0):
        label = ttk.Label(parent, text=label_text)
        label.grid(row=row, column=0 + grid_column_offset, sticky="w", padx=(0, 10))
        entry_var = tk.StringVar(value=default_value)
        combobox = ttk.Combobox(parent, textvariable=entry_var, values=options, state="readonly")
        combobox.grid(row=row, column=1, columnspan=2, sticky="ew")
        TextContextMenu(combobox)
        combobox.bind("<<ComboboxSelected>>", lambda e: self.update_command_preview())
        return label, combobox, entry_var

    def clear_log(self):
        self.log_output.delete("1.0", tk.END)

    def log_message(self, message):
        # The widget is now always in a 'normal' state but made read-only via binding
        self.log_output.insert(tk.END, message)
        self.log_output.see(tk.END) # Scroll to the end

    def save_log(self):
        """Saves the content of the log output to a text file."""
        log_content = self.log_output.get("1.0", tk.END)
        if not log_content.strip():
            messagebox.showinfo("Log Empty", "There is nothing to save.", parent=self)
            return

        default_filename = f"hackdvb_log_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
        filepath = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Log File",
            initialfile=default_filename
        )

        if not filepath:
            return # User cancelled

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(log_content)
            messagebox.showinfo("Success", f"Log saved successfully to:\n{filepath}", parent=self)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save log file: {e}", parent=self)

    def browse_file(self, entry_var, filetypes=None):
        options = {}
        if filetypes:
            options['filetypes'] = filetypes
        filename = filedialog.askopenfilename(**options)
        if filename:
            entry_var.set(filename)

    def check_dependencies_on_startup(self):
        """
        Checks for required executables (ffmpeg, tsp, tdt) on startup.
        If missing, it opens a dialog for the user to resolve the issue.
        Returns True if all dependencies are met, False otherwise.
        """
        while True: # Loop until dependencies are met or user aborts
            missing = []
            if not shutil.which(self.ffmpeg_path.get()):
                missing.append("ffmpeg")
            if not shutil.which(self.tsp_path.get()):
                missing.append("TSDuck (tsp)")
            if not shutil.which(self.tdt_path.get()):
                missing.append("TDT Injector (tdt.exe)")

            if not missing:
                # All dependencies found, re-check HW support with correct paths
                self.cuda_supported = self.check_cuda_support()
                self.qsv_supported = self.check_qsv_support()
                return True

            # --- Create and show the dependency error dialog ---
            dialog = tk.Toplevel(self)
            dialog.title("Missing Dependencies")
            dialog.transient(self)
            dialog.grab_set()
            dialog.resizable(False, False)

            main_frame = ttk.Frame(dialog, padding=20)
            main_frame.pack(fill="both", expand=True)

            message = f"The following required dependencies could not be found in your system's PATH:\n\n"
            message += "\n".join([f" • {dep}" for dep in missing])
            message += "\n\nPlease manually locate the executables or download them."

            ttk.Label(main_frame, text=message, justify=tk.LEFT).pack(pady=(0, 20))

            button_frame = ttk.Frame(main_frame)
            button_frame.pack(fill="x")

            user_choice = tk.StringVar()

            def on_manual_select():
                user_choice.set("manual")
                dialog.destroy()

            def on_download():
                user_choice.set("download")
                dialog.destroy()

            def on_abort():
                user_choice.set("abort")
                dialog.destroy()

            ttk.Button(button_frame, text="Manually Select...", command=on_manual_select).pack(side="left", expand=True, fill="x", padx=5)
            ttk.Button(button_frame, text="Download Info", command=on_download).pack(side="left", expand=True, fill="x", padx=5)
            ttk.Button(button_frame, text="Abort", command=on_abort).pack(side="left", expand=True, fill="x", padx=5)

            dialog.protocol("WM_DELETE_WINDOW", on_abort)
            self.wait_window(dialog) # Wait for the dialog to close

            # --- Process user's choice ---
            choice = user_choice.get()
            if choice == "manual":
                if "ffmpeg" in missing:
                    self.browse_for_executable(self.ffmpeg_path, "FFmpeg")
                if "TSDuck (tsp)" in missing:
                    self.browse_for_executable(self.tsp_path, "TSDuck (tsp)")
                if "TDT Injector (tdt.exe)" in missing:
                    self.browse_for_executable(self.tdt_path, "TDT Injector")
                # The loop will re-check the paths on the next iteration.
            elif choice == "download":
                download_info = (
                    "FFmpeg: https://ffmpeg.org/download.html\n\n"
                    "TSDuck: https://tsduck.io/d/download.html\n\n"
                    "TDT Injector (tdt.exe) is a custom tool and does not have a public download link. It should be included with the application."
                )
                messagebox.showinfo("Download Information", download_info, parent=self)
                # The loop will re-show the dependency dialog after the user closes the info box.
            else: # Abort or window closed
                return False

    def browse_for_executable(self, path_var, name):
        """Opens a file dialog to select an executable and updates its path."""
        if os.name == 'nt':
            filetypes = [(f"{name} Executable", "*.exe"), ("All files", "*.*")]
        else:
            filetypes = [(f"{name} Executable", "*"), ("All files", "*.*")]

        filepath = filedialog.askopenfilename(
            title=f"Select {name} Executable",
            filetypes=filetypes
        )
        if filepath:
            path_var.set(filepath)
            self.log_message(f"Set {name} path to: {filepath}\n")
            self.update_command_preview()

    def show_about_dialog(self):
        """Displays the application's about dialog box."""
        # Using the current year for the version.
        current_year = datetime.now().year
        about_message = (
            f"HackDVB GUI\n\n"
            f"Copyright © {current_year}\n\n"
            "A spiritual digital successor to the analogue HackTV project.\n\n"
            "Authors: GamerA1 and StefanVL"
        )
        messagebox.showinfo("About HackDVB GUI", about_message, parent=self)

    def show_dependencies_dialog(self):
        """Displays an informational dialog about the required dependencies."""
        dialog = tk.Toplevel(self)
        dialog.title("Dependencies Information")
        dialog.geometry("850x700") # A more reasonable starting size
        dialog.minsize(650, 500) # Set a minimum size
        dialog.transient(self)
        dialog.grab_set()

        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        intro_text = (
            "This application orchestrates several external command-line tools to create a DVB broadcast. "
            "They must be installed and accessible in your system's PATH, or their location must be set manually via the 'Settings' menu."
        )
        intro_label = ttk.Label(main_frame, text=intro_text, justify=tk.LEFT)
        intro_label.pack(fill='x', pady=(0, 15))
        # Bind configure event directly to the label
        intro_label.bind('<Configure>', lambda e: e.widget.configure(wraplength=e.width - 10))

        def create_dependency_frame(parent, title, what_it_is, why_needed, website_url=None):
            frame = ttk.Labelframe(parent, text=title, padding=10, style="Card.TLabelframe")
            frame.pack(fill='x', pady=5)
            frame.grid_columnconfigure(1, weight=1)

            ttk.Label(frame, text="What it is:", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky='nw', padx=(0, 10))
            what_label = ttk.Label(frame, text=what_it_is, justify=tk.LEFT)
            what_label.grid(row=0, column=1, sticky='ew')
            what_label.bind('<Configure>', lambda e: e.widget.configure(wraplength=e.width))

            ttk.Label(frame, text="Why it's needed:", font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky='nw', padx=(0, 10), pady=(5,0))
            why_label = ttk.Label(frame, text=why_needed, justify=tk.LEFT)
            why_label.grid(row=1, column=1, sticky='ew', pady=(5,0))
            why_label.bind('<Configure>', lambda e: e.widget.configure(wraplength=e.width))

            if website_url:
                ttk.Label(frame, text="Website:", font=("Segoe UI", 9, "bold")).grid(row=2, column=0, sticky='nw', padx=(0, 10), pady=(5,0))
                link = ttk.Label(frame, text=website_url, foreground="blue", cursor="hand2")
                link.grid(row=2, column=1, sticky='w', pady=(5,0))
                link.bind("<Button-1>", lambda e, url=website_url: webbrowser.open_new(url))
                ToolTip(link, f"Open {website_url} in your browser")

        # FFmpeg
        create_dependency_frame(
            main_frame, "1. FFmpeg (ffmpeg)",
            "A complete, cross-platform solution to record, convert, and stream audio and video.",
            "It's the core engine for all media processing. It reads your source files, decodes them, applies filters (like loudness normalization and subtitle burn-in), and re-encodes them into the correct format (e.g., MPEG-2, H.264) for the broadcast.",
            "https://ffmpeg.org/"
        )

        # TSDuck
        create_dependency_frame(
            main_frame, "2. TSDuck (tsp)",
            "An extensible toolkit for MPEG transport streams. 'tsp' is its transport stream processor.",
            "It takes the encoded stream from FFmpeg and adds the necessary DVB-specific information (like Service and Network tables), injects the EPG data (EIT), and modulates the final signal for output via the DekTec hardware.",
            "https://tsduck.io/"
        )

        # TDT Injector
        create_dependency_frame(
            main_frame, "3. TDT Injector (tdt.exe)",
            "A small, custom utility to generate Time and Date Table (TDT) and Time Offset Table (TOT) packets.",
            "DVB receivers need these packets to synchronize their internal clocks, which is essential for the EPG to function correctly. Without it, your schedule information may not appear. This tool should be included with the application."
        )

        ttk.Button(main_frame, text="Close", command=dialog.destroy).pack(side=tk.RIGHT, pady=(15, 0))

    def update_hw_support_ui(self):
        """Updates the state of hardware acceleration checkboxes based on detected support."""
        if not self.cuda_supported:
            self.use_cuda_var.set(False)
            self.cuda_checkbox.config(state=tk.DISABLED)
            self.converter_use_cuda_var.set(False)
            self.converter_cuda_checkbox.config(state=tk.DISABLED)

        if not self.qsv_supported:
            self.use_qsv_var.set(False)
            self.qsv_checkbox.config(state=tk.DISABLED)
            self.converter_use_qsv_var.set(False)
            self.converter_qsv_checkbox.config(state=tk.DISABLED)

    def check_cuda_support(self):
        """Checks if ffmpeg has support for CUDA NVENC encoders."""
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            # Step 1: Check if the encoders are listed in the build. This is a fast check.
            ffmpeg_exe = self.ffmpeg_path.get()
            result = subprocess.run([ffmpeg_exe, '-encoders'], capture_output=True, text=True, startupinfo=startupinfo)
            output = result.stdout
            if 'h264_nvenc' not in output or 'hevc_nvenc' not in output:
                return False # Encoders not even built, no need to go further.

            # Step 2: Perform a "dry run" to see if CUDA can actually be initialized.
            # This tests the hardware and drivers. We use a command that is very fast and will
            # fail early if CUDA context cannot be created.
            dry_run_cmd = [
                ffmpeg_exe, '-f', 'lavfi', '-i', 'nullsrc', '-c:v', 'h264_nvenc',
                '-preset', 'p1', '-f', 'null', '-'
            ]
            result = subprocess.run(dry_run_cmd, capture_output=True, text=True, startupinfo=startupinfo)
            # If the command fails and the error contains CUDA-related errors, it's not supported.
            return "Cannot load" not in result.stderr and "cuda" not in result.stderr.lower()

        except (FileNotFoundError, Exception) as e:
            # ffmpeg not found or another error occurred
            return False
        return False

    def check_qsv_support(self):
        """Checks if ffmpeg has support for Intel QSV encoders."""
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            # Step 1: Check if the encoders are listed in the build.
            ffmpeg_exe = self.ffmpeg_path.get()
            result = subprocess.run([ffmpeg_exe, '-encoders'], capture_output=True, text=True, startupinfo=startupinfo)
            output = result.stdout
            if 'h264_qsv' not in output or 'hevc_qsv' not in output:
                return False

            # Step 2: Perform a "dry run" to see if QSV can be initialized.
            dry_run_cmd = [
                ffmpeg_exe, '-f', 'lavfi', '-i', 'nullsrc', '-c:v', 'h264_qsv',
                '-f', 'null', '-'
            ]
            result = subprocess.run(dry_run_cmd, capture_output=True, text=True, startupinfo=startupinfo)
            return "Impossible to convert between formats" not in result.stderr and "failed" not in result.stderr.lower()

        except (FileNotFoundError, Exception):
            return False

    def update_audio_options(self, *args):
        """Updates audio bitrate and sample rate options based on the selected codec."""
        codec = self.audio_codec.get()
        options = self.audio_options_map.get(codec)

        if not options:
            return

        # Update bitrates
        self.audio_bitrate_combobox['values'] = options["bitrates"]
        if self.audio_bitrate.get() not in options["bitrates"]:
            self.audio_bitrate.set(options["default_bitrate"])

        # Update sample rates
        self.audio_samplerate_combobox['values'] = options["samplerates"]
        if self.audio_samplerate.get() not in options["samplerates"]:
            self.audio_samplerate.set(options["samplerates"][0])

    def update_hw_accel_options(self, *args):
        """Manages mutual exclusivity of HW accel options and updates video codecs."""
        use_cuda = self.use_cuda_var.get()
        use_qsv = self.use_qsv_var.get()
        current_codec = self.video_codec.get()
        encoder_type = "software"

        # --- Mutual Exclusivity Logic ---
        if use_cuda:
            encoder_type = "cuda"
            self.use_qsv_var.set(False) # Uncheck QSV if CUDA is checked
            if self.qsv_supported: self.qsv_checkbox.config(state=tk.DISABLED)
        elif use_qsv:
            encoder_type = "qsv"
            self.use_cuda_var.set(False) # Uncheck CUDA if QSV is checked
            if self.cuda_supported: self.cuda_checkbox.config(state=tk.DISABLED)
        else: # Neither is checked, re-enable both if supported
            encoder_type = "software"
            if self.cuda_supported: self.cuda_checkbox.config(state=tk.NORMAL)
            if self.qsv_supported: self.qsv_checkbox.config(state=tk.NORMAL)

        # --- Update Preset Dropdown ---
        self.preset_combobox['values'] = self.preset_map[encoder_type]
        if self.preset.get() not in self.preset_map[encoder_type]:
            # Set a sensible default for the new encoder type
            default_preset = "medium" if encoder_type != "cuda" else "p4 (medium)"
            self.preset.set(default_preset)

        # --- Update Codec Dropdown ---
        if encoder_type == "cuda":
            self.video_codec_combobox['values'] = self.video_codec_map["cuda"]
            if current_codec == "libx264":
                self.video_codec.set("h264_nvenc")
            elif current_codec == "libx265":
                self.video_codec.set("hevc_nvenc")
            elif current_codec.endswith("_qsv"):
                self.video_codec.set("h264_nvenc")
            elif current_codec not in self.video_codec_map["cuda"]:
                self.video_codec.set("h264_nvenc")
        elif encoder_type == "qsv":
            self.video_codec_combobox['values'] = self.video_codec_map["qsv"]
            if current_codec == "libx264":
                self.video_codec.set("h264_qsv")
            elif current_codec == "libx265":
                self.video_codec.set("hevc_qsv")
            elif current_codec.endswith("_nvenc"):
                self.video_codec.set("h264_qsv")
            elif current_codec not in self.video_codec_map["qsv"]:
                self.video_codec.set("h264_qsv")
        else:
            self.video_codec_combobox['values'] = self.video_codec_map["software"]
            if current_codec.endswith("_nvenc"):
                self.video_codec.set("libx264")
            elif current_codec.endswith("_qsv"):
                self.video_codec.set("libx265")
            elif current_codec not in self.video_codec_map["software"]:
                self.video_codec.set("mpeg2video")

        self.update_command_preview()

    def update_dvb_options(self, *args):
        standard = self.dvb_standard.get()

        # Update Modulation
        mod_opts = self.mod_options.get(standard, [])
        self.dek_mod_combobox['values'] = mod_opts
        if mod_opts:
            self.dek_mod_var.set(mod_opts[0])

        # Update FEC
        fec_opts = self.fec_options.get(standard, [])
        self.dek_fec_combobox['values'] = fec_opts
        if fec_opts:
            # Set a sensible default, like the middle option
            self.dek_fec_var.set(fec_opts[len(fec_opts) // 2])

        self.update_command_preview()
        self.calculate_mux_rate()

    def calculate_mux_rate(self):
        try:
            symrate_str = self.dek_symrate.get()
            fec_str = self.dek_fec_var.get()
            standard = self.dvb_standard.get()

            if not symrate_str or not fec_str:
                self.mux_rate_mbps_label.config(text="")
                return

            symrate = int(symrate_str)
            fec_num, fec_den = map(int, fec_str.split('/'))
            fec = fec_num / fec_den

            mux_rate_bps = 0

            if standard == "DVB-S":
                # DVB-S uses QPSK (2 bits/symbol) and Reed-Solomon (188/204)
                bits_per_symbol = 2
                rs_overhead = 188 / 204
                mux_rate_bps = symrate * bits_per_symbol * fec * rs_overhead

            elif standard == "DVB-S2":
                mod = self.dek_mod_var.get()
                bits_per_symbol_map = {
                    "DVB-S2-QPSK": 2,
                    "DVB-S2-8PSK": 3,
                    "DVB-S2-16APSK": 4,
                    "DVB-S2-32APSK": 5
                }
                bits_per_symbol = bits_per_symbol_map.get(mod, 0)
                
                # DVB-S2 uses LDPC+BCH. The overhead is complex, but a common approximation
                # for the final TS rate is to use a factor around 0.97 (representing ~3% overhead for pilots, BB header etc).
                # This is a simplification.
                efficiency_factor = 0.97 
                mux_rate_bps = symrate * bits_per_symbol * fec * efficiency_factor

            self.mux_rate_var.set(str(int(mux_rate_bps)))
            self.mux_rate_mbps_label.config(text=f"~{mux_rate_bps / 1_000_000:.2f} Mbps")
            self.update_command_preview()

        except (ValueError, ZeroDivisionError) as e:
            self.mux_rate_mbps_label.config(text="Invalid input")
        except Exception as e:
            self.mux_rate_mbps_label.config(text="Error")

    def add_channel(self):
        channel_num = len(self.channels) + 1
        channel_index = channel_num - 1
        num_columns = 3
        row = channel_index // num_columns
        col = channel_index % num_columns
        
        # --- Create Service UI ---
        service_frame = ttk.Labelframe(self.scrollable_service_frame, text=f"Service {channel_num}: FilmNet {channel_num}", padding=10, style="Card.TLabelframe")
        service_frame.grid(row=row, column=col, sticky="nsew", padx=(0, 15), pady=(0, 15))
        service_frame.grid_columnconfigure(2, weight=1)
        service_frame.grid_rowconfigure(0, pad=5)
        service_frame.grid_rowconfigure(1, pad=5)
        service_frame.grid_rowconfigure(2, pad=5)
        service_frame.grid_rowconfigure(3, pad=5)
        service_frame.grid_rowconfigure(4, pad=5)
        # The lambda captures the service_frame widget itself to identify which channel to remove.
        remove_button = ttk.Button(service_frame, text="✖", width=3, command=lambda sf=service_frame: self.remove_channel(sf))
        ToolTip(remove_button, "Remove this service.")
        remove_button.grid(row=0, column=0, sticky='n', padx=(0, 10))

        # Use column 1 for the labels and 2 for the entries now
        _, s_name_entry, s_name = self.create_text_input_widgets(service_frame, "Service Name:", 0, f"FilmNet {channel_num}", grid_column_offset=1)
        ToolTip(s_name_entry, "Name of the service as it appears in the channel list.")
        _, s_provider_entry, s_provider = self.create_text_input_widgets(service_frame, "Provider:", 1, "MultiChoice", grid_column_offset=1)
        ToolTip(s_provider_entry, "Provider name for the service.")
        _, s_pid_entry, s_pid = self.create_text_input_widgets(service_frame, "Program Num (hex):", 2, f"0x{channel_num:04x}", validation_type="hex", grid_column_offset=1)
        ToolTip(s_pid_entry, "Program/Service ID (SID) in hexadecimal (e.g., 0x0001). Must be unique.")

        # --- TV/Radio Mode Selection ---
        mode_frame = ttk.Frame(service_frame)
        mode_frame.grid(row=3, column=1, columnspan=2, sticky='w')
        s_type_var = tk.StringVar(value="TV")
        tv_radio_button = ttk.Radiobutton(mode_frame, text="TV", variable=s_type_var, value="TV")
        radio_radio_button = ttk.Radiobutton(mode_frame, text="Radio", variable=s_type_var, value="Radio")
        tv_radio_button.pack(side=tk.LEFT, padx=(0, 10))
        radio_radio_button.pack(side=tk.LEFT)

        # --- Create Input UI on the Inputs Tab ---
        # Create a container frame for this channel's inputs
        channel_input_frame = ttk.Labelframe(self.inputs_frame, text=f"Input Source: FilmNet {channel_num}", padding=10, style="Card.TLabelframe")
        channel_input_frame.grid(row=row, column=col, sticky="nsew", padx=(0, 15), pady=(0, 15))
        channel_input_frame.grid_columnconfigure(2, weight=1) # Make entry column expandable

        # --- Media Input ---

        input_label = ttk.Label(channel_input_frame, text="Source:")
        input_label.grid(row=0, column=0, sticky="w", pady=2)

        input_type_var = tk.StringVar(value="Concat File")
        input_type_combo = ttk.Combobox(channel_input_frame, textvariable=input_type_var, values=["Concat File", "Media File", "UDP/IP Stream"], state="readonly", width=15)
        ToolTip(input_type_combo, "Choose the type of input source for this channel.\n- Concat File: A text file listing media files to loop.\n- Media File: A single video/audio file to loop.\n- UDP/IP Stream: A network stream (e.g., udp://@239.0.0.1:1234).")
        input_type_combo.grid(row=0, column=1, sticky="ew", padx=(0, 5))

        input_path_var = tk.StringVar()
        input_path_entry = ttk.Entry(channel_input_frame, textvariable=input_path_var)
        ToolTip(input_path_entry, "Path to the file or the URL of the stream.")
        input_path_entry.grid(row=0, column=2, sticky="ew")
        TextContextMenu(input_path_entry)

        browse_button = ttk.Button(channel_input_frame, text="Browse...", command=lambda v=input_path_var: self.browse_file(v, filetypes=[("All files", "*.*")]))
        ToolTip(browse_button, "Browse for a file.")
        browse_button.grid(row=0, column=3, sticky="w", padx=(5, 0))
        
        loop_var = tk.BooleanVar(value=True)
        loop_checkbox = ttk.Checkbutton(channel_input_frame, text="Loop", variable=loop_var, command=self.update_command_preview)
        ToolTip(loop_checkbox, "Loop the media file or concat list.")
        loop_checkbox.grid(row=0, column=4, sticky="w", padx=(5,0))
        
        # --- Subtitle Input ---
        subtitle_label = ttk.Label(channel_input_frame, text="Subtitles:")
        subtitle_label.grid(row=1, column=0, sticky="w", pady=2)

        subtitle_path_var = tk.StringVar()
        subtitle_path_entry = ttk.Entry(channel_input_frame, textvariable=subtitle_path_var)
        ToolTip(subtitle_path_entry, "Optional: Path to an external subtitle file (e.g., .srt, .ass, .vtt) to burn into the video.")
        subtitle_path_entry.grid(row=1, column=1, columnspan=2, sticky="ew")
        TextContextMenu(subtitle_path_entry)

        subtitle_browse_button = ttk.Button(channel_input_frame, text="Browse...", command=lambda v=subtitle_path_var: self.browse_file(v, filetypes=[("Subtitle Files", "*.srt *.ass *.vtt"), ("All files", "*.*")]))
        ToolTip(subtitle_browse_button, "Browse for a subtitle file.")
        subtitle_browse_button.grid(row=1, column=3, sticky="w", padx=(5, 0))
        
        default_sub_size = "Medium"
        subtitle_size_var = tk.StringVar(value=default_sub_size)
        subtitle_size_combobox = ttk.Combobox(channel_input_frame, textvariable=subtitle_size_var, values=list(self.subtitle_size_map.keys()), state="readonly", width=10)
        ToolTip(subtitle_size_combobox, "Size for burned-in subtitles.")
        subtitle_size_combobox.grid(row=1, column=4, sticky="w", padx=(5,0))
        subtitle_size_combobox.bind("<<ComboboxSelected>>", lambda e: self.update_command_preview())
        
        # --- Probe Button and Track Selection ---
        probe_button = ttk.Button(channel_input_frame, text="Probe Input Tracks", command=lambda ch_num=channel_num: self.probe_input(ch_num))
        probe_button.grid(row=2, column=0, columnspan=5, sticky='ew', pady=(5,0))

        # --- Audio and Subtitle Track Selection Dropdowns ---
        track_label = ttk.Label(channel_input_frame, text="Tracks:")
        track_label.grid(row=3, column=0, sticky="w", pady=2)

        # --- Audio Track Selection Button ---
        audio_select_button = ttk.Button(channel_input_frame, text="Select Audio Tracks...", command=lambda ch_num=channel_num: self.open_audio_selection_dialog(ch_num))
        ToolTip(audio_select_button, "Select which audio tracks from the source file to include in the broadcast.")
        audio_select_button.grid(row=4, column=1, columnspan=2, sticky="ew")
        subtitle_track_var = tk.StringVar(value="None")
        subtitle_track_combobox = ttk.Combobox(channel_input_frame, textvariable=subtitle_track_var, values=["None"], state="readonly", width=25)
        ToolTip(subtitle_track_combobox, "Select the embedded subtitle track to use from the source file after probing. Requires 'Probe Input Tracks'. 'None' disables embedded subtitles.")
        subtitle_track_combobox.grid(row=4, column=3, columnspan=2, sticky="ew", padx=(5,0))
        subtitle_track_combobox.bind("<<ComboboxSelected>>", lambda e, ch_num=channel_num: self.on_track_selected(ch_num, 'subtitle'))



        def on_input_type_change(*args):
            # Reset fields to avoid carrying over old settings
            input_path_var.set("")
            subtitle_path_var.set("")
            loop_var.set(True)
            subtitle_size_var.set("Medium")

            # Reset probed audio track information
            channel_data["selected_audio_specifiers"] = ["a:0"] # Default to first audio stream
            channel_data["audio_track_map"] = {"Default Audio": ("a:0", "und")} # Map of display name to (specifier, lang_code)

            subtitle_track_var.set("None")
            subtitle_track_combobox['values'] = ["None"]
            channel_data["selected_subtitle_specifier"].set("None")
            channel_data["subtitle_track_map"] = {"None": "None"}

            # Adjust UI layout based on new type
            if input_type_var.get() == "UDP/IP Stream":
                browse_button.grid_remove()
                loop_checkbox.grid_remove()
                # Hide all subtitle widgets
                for w in [subtitle_label, subtitle_path_entry, subtitle_browse_button, subtitle_size_combobox]:
                    w.grid_remove()
                probe_button.grid_configure(row=1, column=0, columnspan=4, rowspan=1) # Move probe button up
            else:
                browse_button.grid()
                loop_checkbox.grid()
                # Show all subtitle widgets
                for w in [subtitle_label, subtitle_path_entry, subtitle_browse_button, subtitle_size_combobox]:
                    w.grid()
                probe_button.grid_configure(row=2, column=0, columnspan=5, rowspan=1) # Move probe button back
            self.update_command_preview()

        input_type_var.trace_add("write", on_input_type_change)

        def on_service_type_change(*args):
            """Enable/disable video-related inputs based on service type."""
            is_tv = s_type_var.get() == "TV"
            new_state = tk.NORMAL if is_tv else tk.DISABLED

            # Disable/Enable subtitle widgets
            subtitle_path_entry.config(state=new_state)
            subtitle_browse_button.config(state=new_state)
            subtitle_size_combobox.config(state='readonly' if is_tv else 'disabled')
            subtitle_track_combobox.config(state='readonly' if is_tv else 'disabled')

            if not is_tv:
                # Clear subtitle fields when switching to Radio
                subtitle_path_var.set("")
                subtitle_track_var.set("None")
            self.update_command_preview()

        s_type_var.trace_add("write", on_service_type_change)
        # Add a trace to update the labels when the service name changes
        s_name.trace_add("write", lambda *args, ch_num=channel_num, sn=s_name: self._update_channel_labels(ch_num, sn))

        channel_data = {
            "num": channel_num,
            "service_frame": service_frame,
            "name": s_name,
            "provider": s_provider,
            "pid": s_pid,
            "service_type": s_type_var,
            "input_type": input_type_var,
            "input_path": input_path_var,
            "loop": loop_var,
            "subtitle_path": subtitle_path_var,
            "subtitle_size": subtitle_size_var,
            "subtitle_track_display_var": subtitle_track_var,
            "subtitle_track_combobox": subtitle_track_combobox, # Direct reference
            "selected_audio_specifiers": ["a:0"], # List of selected audio stream specifiers
            "selected_subtitle_specifier": tk.StringVar(value="None"), # Default to no internal subtitle
            "audio_track_map": {"Default Audio": ("a:0", "und")}, # Maps display name to (specifier, lang_code)
            "subtitle_track_map": {"None": "None"},
            # Store all widgets in a list for easy removal
            "input_widgets": [channel_input_frame]
        }
        self.channels.append(channel_data)
        # Run once to set initial state
        on_input_type_change()
        on_service_type_change()
        self.update_command_preview()

    def remove_channel(self, service_frame_to_remove):
        # Find the index of the channel to remove by matching its service_frame widget
        index_to_remove = -1
        for i, channel in enumerate(self.channels):
            if channel["service_frame"] == service_frame_to_remove:
                index_to_remove = i
                break

        if index_to_remove == -1:
            print("Error: Could not find channel to remove.")
            return

        # Remove UI elements
        channel_to_remove = self.channels[index_to_remove]
        channel_to_remove["service_frame"].destroy()
        for widget in channel_to_remove["input_widgets"]:
            widget.destroy()

        # Remove from data structure
        del self.channels[index_to_remove]

        # Re-grid and re-number all remaining channels
        for i, channel in enumerate(self.channels):
            new_num = i+1
            channel["num"] = new_num
            
            # Re-calculate grid position for the service card
            row = i // 3
            col = i % 3
            channel["service_frame"].grid(row=row, column=col, sticky="nsew", padx=(0, 15), pady=(0, 15))
            # Update labels using the current name
            channel["service_frame"].config(text=f"Service {new_num}: {channel['name'].get()}")
            
            # Re-grid the input card and update its label
            channel["input_widgets"][0].grid(row=row, column=col, sticky="nsew", padx=(0, 15), pady=(0, 15))
            channel["input_widgets"][0].config(text=f"Input Source: {channel['name'].get()}")

            # Re-create the trace with the correct new channel number
            s_name_var = channel['name']
            # Remove old traces to avoid multiple calls
            s_name_var.trace_remove("write", s_name_var.trace_info()[0][1])
            s_name_var.trace_add("write", lambda *args, ch_num=new_num, sn=s_name_var: self._update_channel_labels(ch_num, sn))

        self.update_command_preview()

    def probe_input(self, channel_num):
        """Probes the input for a given channel and updates the track selection dropdowns."""
        channel_index = channel_num - 1
        if channel_index < 0 or channel_index >= len(self.channels):
            return

        channel = self.channels[channel_index]
        input_path = channel["input_path"].get()
        input_type = channel["input_type"].get()

        if not input_path:
            messagebox.showwarning("Probe Warning", f"Please specify an input path for Service {channel_num} first.")
            return

        # For concat files, we probe the first file in the list.
        if input_type == "Concat File":
            try:
                with open(input_path, 'r') as f:
                    first_line = f.readline().strip()
                    # The format is "file '/path/to/media.mkv'"
                    match = re.search(r"file\s+'(.+?)'", first_line)
                    if match:
                        input_path = match.group(1)
                        self.log_message(f"Probing first file in concat list: {input_path}\n")
                    else:
                        messagebox.showerror("Probe Error", "Could not parse the first file from the concat list. Ensure it's in the format: file '/path/to/file.ext'")
                        return
            except Exception as e:
                messagebox.showerror("Probe Error", f"Could not read concat file: {e}")
                return

        self.status_label.config(text=f"Status: Probing Service {channel_num}...")
        # Run ffprobe in a separate thread to avoid freezing the GUI
        thread = threading.Thread(target=self._run_ffprobe, args=(channel_num, input_path), daemon=True)
        thread.start()

    def _run_ffprobe(self, channel_num, file_path):
        """Worker function to execute ffprobe and schedule UI update."""
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        ffmpeg_exe = self.ffmpeg_path.get()
        ffprobe_exe = "ffprobe"
        if os.path.isabs(ffmpeg_exe):
            dir_name = os.path.dirname(ffmpeg_exe)
            ffprobe_exe = os.path.join(dir_name, "ffprobe.exe" if os.name == 'nt' else "ffprobe")

        command = [
            ffprobe_exe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            file_path
        ]

        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True, startupinfo=startupinfo)
            streams_data = json.loads(result.stdout)
            self.after(0, self._update_channel_tracks, channel_num, streams_data)
        except FileNotFoundError:
            self.log_queue.put("ERROR: ffprobe command not found. Make sure it is in your system's PATH.\n")
            messagebox.showerror("Error", "ffprobe not found. Make sure it is installed and in your system's PATH.")
        except subprocess.CalledProcessError as e:
            self.log_queue.put(f"ERROR: ffprobe failed for '{file_path}': {e.stderr}\n")
            messagebox.showerror("Probe Error", f"ffprobe failed. Check the log for details.")
        except json.JSONDecodeError:
            self.log_queue.put(f"ERROR: Failed to parse ffprobe output for '{file_path}'.\n")
            messagebox.showerror("Probe Error", "Failed to parse ffprobe output.")
        finally:
            self.after(0, self.status_label.config, {"text": "Status: Idle"})

    def _update_channel_labels(self, channel_num, service_name_var):
        """Updates the labels for service and input frames when a service name changes."""
        channel_index = channel_num - 1
        if channel_index < 0 or channel_index >= len(self.channels):
            return

        channel = self.channels[channel_index]
        new_name = service_name_var.get()
        channel["service_frame"].config(text=f"Service {channel_num}: {new_name}")
        channel["input_widgets"][0].config(text=f"Input Source: {new_name}")

    def _update_channel_tracks(self, channel_num, streams_data):
        """Updates the UI with the probed track information. Must be called on the main thread."""
        channel = self.channels[channel_num - 1]

        audio_track_map = {"Default Audio": ("a:0", "und")} # Keep a default: (specifier, lang_code)
        subtitle_track_map = {"None": "None"} # Option to disable subtitles

        audio_count = 0
        subtitle_count = 0

        for stream in streams_data.get("streams", []):
            stream_index = stream.get("index")
            codec_type = stream.get("codec_type")
            
            if codec_type == "audio":
                # Use the count of audio streams found so far to create the specifier (a:0, a:1, etc.)
                specifier = f"a:{audio_count}"
                lang = stream.get("tags", {}).get("language", "und")
                codec = stream.get("codec_name", "unknown")
                title = stream.get("tags", {}).get("title", "")
                label = f"Audio {audio_count}: {codec}, {lang}"
                if title:
                    label += f" ({title})"
                audio_track_map[label] = (specifier, lang)
                audio_count += 1

            elif codec_type == "subtitle":
                # Use the count of subtitle streams found so far for the specifier (s:0, s:1, etc.)
                specifier = f"s:{subtitle_count}"
                lang = stream.get("tags", {}).get("language", "und")
                codec = stream.get("codec_name", "unknown")
                title = stream.get("tags", {}).get("title", "")
                label = f"Subtitle {subtitle_count}: {codec}, {lang}"
                if title:
                    label += f" ({title})"
                subtitle_track_map[label] = specifier
                subtitle_count += 1

        # Store the maps on the channel object
        channel["audio_track_map"] = audio_track_map
        channel["subtitle_track_map"] = subtitle_track_map

        subtitle_combobox = channel["subtitle_track_combobox"]
        subtitle_combobox['values'] = list(subtitle_track_map.keys())
        channel["subtitle_track_display_var"].set("None") # Reset to default

        messagebox.showinfo("Probe Complete", f"Found {len(audio_track_map)-1} audio track(s) and {len(subtitle_track_map)-1} subtitle track(s).")
        self.log_message(f"Probe for Service {channel_num} complete.\n")

    def on_track_selected(self, channel_num, track_type):
        """Called when a user selects a track from a combobox."""
        if track_type == 'audio':
            # This is now handled by the dialog's OK button
            return

        channel = self.channels[channel_num - 1]
        if track_type == 'subtitle':
            selected_display_name = channel["subtitle_track_display_var"].get()
            specifier = channel["subtitle_track_map"].get(selected_display_name, "s:0")
            channel["selected_subtitle_specifier"].set(specifier)
        self.update_command_preview()

    def open_audio_selection_dialog(self, channel_num):
        """Opens a Toplevel window to select multiple audio tracks."""
        channel = self.channels[channel_num - 1]
        
        dialog = tk.Toplevel(self)
        dialog.title(f"Select Audio Tracks for Service {channel_num}")
        dialog.geometry("400x300")
        dialog.transient(self)
        dialog.grab_set()

        main_frame = ttk.Frame(dialog, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Select the audio tracks to include:").pack(anchor='w', pady=(0, 10))

        track_vars = {}
        for display_name, (specifier, lang) in channel["audio_track_map"].items():
            var = tk.BooleanVar()
            # Check the box if this track was previously selected
            if specifier in channel["selected_audio_specifiers"]:
                var.set(True)
            cb = ttk.Checkbutton(main_frame, text=display_name, variable=var)
            cb.pack(anchor='w')
            track_vars[specifier] = var

        def on_ok():
            # Update the channel's list of selected specifiers
            channel["selected_audio_specifiers"] = [spec for spec, var in track_vars.items() if var.get()]
            self.update_command_preview()
            dialog.destroy()

        ok_button = ttk.Button(main_frame, text="OK", command=on_ok)
        ok_button.pack(side=tk.RIGHT, pady=(10, 0))
        dialog.wait_window()

    def save_configuration(self):
        """Gathers all settings from the UI and saves them to a JSON file."""
        config_data = {
            "channels": [],
            "encoding": {},
            "dvb": {},
            "eit": {},
            "paths": {}
        }

        # Gather channel data
        for channel in self.channels:
            config_data["channels"].append({
                "name": channel["name"].get(),
                "provider": channel["provider"].get(),
                "pid": channel["pid"].get(),
                "service_type": channel["service_type"].get(),
                "input_type": channel["input_type"].get(),
                "input_path": channel["input_path"].get(),
                "loop": channel["loop"].get(),
                "subtitle_path": channel["subtitle_path"].get(),
                "subtitle_size": channel["subtitle_size"].get(),
                "selected_audio_specifiers": channel["selected_audio_specifiers"],
                "selected_subtitle_specifier": channel["selected_subtitle_specifier"].get(),
                "audio_track_map": channel["audio_track_map"],
                "subtitle_track_map": channel["subtitle_track_map"],
            })

        # Gather encoding data
        config_data["encoding"] = {
            "video_bitrate": self.video_bitrate.get(),
            "audio_codec": self.audio_codec.get(),
            "audio_bitrate": self.audio_bitrate.get(),
            "audio_samplerate": self.audio_samplerate.get(),
            "use_loudnorm": self.use_loudnorm_var.get(),
            "use_cuda": self.use_cuda_var.get(),
            "use_qsv": self.use_qsv_var.get(),
            "video_codec": self.video_codec.get(),
            "preset": self.preset.get(),
            "pixel_format": self.pix_fmt.get(),
            "aspect_ratio": self.aspect_ratio.get(),
            "video_format": self.video_format_display.get(),
        }

        # Gather DVB data
        config_data["dvb"] = {
            "device_index": self.dek_device.get(),
            "standard": self.dvb_standard.get(),
            "modulation": self.dek_mod_var.get(),
            "lnb_lo": self.lnb_lo_freq.get(),
            "frequency": self.dek_freq.get(),
            "symbol_rate": self.dek_symrate.get(),
            "fec": self.dek_fec_var.get(),
            "mux_rate": self.mux_rate_var.get(),
            "tdt_source": self.tdt_source.get(),
        }

        # Gather EIT data
        config_data["eit"] = {
            "path": self.eit_path.get()
        }

        # Gather executable paths
        config_data["paths"] = {
            "ffmpeg": self.ffmpeg_path.get(),
            "tsp": self.tsp_path.get(),
            "tdt": self.tdt_path.get()
        }

        # Ask user for file path
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Save Configuration"
        )
        if not filepath:
            return

        try:
            with open(filepath, 'w') as f:
                json.dump(config_data, f, indent=4)
            messagebox.showinfo("Success", "Configuration saved successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save configuration: {e}")

    def load_configuration(self):
        """Loads a configuration from a JSON file and applies it to the UI."""
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Load Configuration"
        )
        if not filepath:
            return

        try:
            with open(filepath, 'r') as f:
                config_data = json.load(f)

            # Clear existing channels before loading new ones
            while self.channels:
                self.remove_channel(self.channels[0]["service_frame"])

            self.apply_configuration(config_data)
            messagebox.showinfo("Success", "Configuration loaded successfully.")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load configuration: {e}")

    def get_command(self):
        eit_xml = self.eit_path.get()

        ffmpeg_cmd = [self.ffmpeg_path.get(), "-y"]
        filter_complex_parts = []
        output_map_args = []
        metadata_args = []
        program_args = []
        codec_args = []

        total_audio_streams_mapped = 0
        subtitle_copy_stream_count = 0
        output_stream_counter = 0
        input_idx = 0
        for i, channel in enumerate(self.channels):
            input_type = channel["input_type"].get()
            input_path = channel["input_path"].get()
            loop = channel["loop"].get()
            service_type = channel["service_type"].get()
            subtitle_path = channel["subtitle_path"].get()
            subtitle_size = channel["subtitle_size"].get()
            selected_audio_specifiers = channel["selected_audio_specifiers"]
            selected_subtitle_specifier = channel["selected_subtitle_specifier"].get()
            
            # --- Add Media Input ---
            # Correctly handle looping and input types
            if input_type == "Concat File":
                if loop:
                    ffmpeg_cmd.extend(["-stream_loop", "-1"])
                ffmpeg_cmd.extend(["-f", "concat", "-safe", "0", "-i", input_path])
            elif input_type == "Media File":
                if loop:
                    ffmpeg_cmd.extend(["-stream_loop", "-1"])
                ffmpeg_cmd.extend(["-i", input_path])
            elif input_type == "UDP/IP Stream":
                ffmpeg_cmd.extend(["-i", input_path]) # No quotes for URLs

            media_input_idx = input_idx
            input_idx += 1

            # --- Video Mapping and Subtitle Handling (Only for TV mode) ---
            if service_type == "TV":
                # Priority 1: Burn-in external subtitle file
                if subtitle_path and input_type != "UDP/IP Stream":
                    # For SRT files, we need to explicitly enable force_style in the filter itself.
                    is_srt = subtitle_path.lower().endswith('.srt')

                    numeric_size = self.subtitle_size_map.get(subtitle_size, "24") # Default to 24 if not found
                    style_overrides = [f"FontSize={numeric_size}"]
                    if is_srt:
                        style_overrides.append("ForceStyle=1")

                    filter_options = f"filename='{subtitle_path.replace(':', '\\:')}':force_style='{','.join(style_overrides)}'"
                    filter_complex_parts.append(f"[{media_input_idx}:v]subtitles={filter_options}[v_out_{i}]")
                    output_map_args.extend([f"-map", f"[v_out_{i}]"])
                else:
                    # If no external subtitle, map the video stream directly.
                    output_map_args.extend([f"-map", f"{media_input_idx}:v:0"])

            # --- Map Audio and Internal Subtitles (for all channels) ---
            # 1. Map all selected audio streams.
            for specifier in selected_audio_specifiers:
                # Build an explicit, unambiguous stream specifier (e.g., "9:a:0" for the 10th channel's first audio stream).
                # This handles both default ('a:0') and probed (e.g., '1', '2') specifiers correctly.
                map_spec = f"{media_input_idx}:{specifier}"
                output_map_args.extend([f"-map", f"{map_spec}?"])

            # 2. If an internal subtitle is selected, map it.
            if service_type == "TV" and selected_subtitle_specifier != "None" and ":" in selected_subtitle_specifier:
                output_map_args.extend([f"-map", f"{media_input_idx}:{selected_subtitle_specifier}?"])
                # Apply the copy codec specifically to this mapped subtitle stream
                # The index is the number of subtitle streams we are copying across all channels.
                codec_args.extend([f"-c:s:{subtitle_copy_stream_count}", "copy"])
                subtitle_copy_stream_count += 1
            
            # --- Program and Metadata Stream Indexing ---
            # This logic correctly tracks the absolute index of each stream in the output.
            program_streams_list = []
            if service_type == "TV":
                video_output_stream_index = output_stream_counter
                program_streams_list.append(f"st={video_output_stream_index}")
                output_stream_counter += 1 # Increment for video

            audio_stream_indices_in_output = []
            for j, specifier in enumerate(selected_audio_specifiers):
                audio_output_stream_index = output_stream_counter + j
                program_streams_list.append(f"st={audio_output_stream_index}")
                audio_stream_indices_in_output.append(audio_output_stream_index)
            output_stream_counter += len(selected_audio_specifiers)

            if service_type == "TV" and selected_subtitle_specifier != "None" and ":" in selected_subtitle_specifier:
                subtitle_output_stream_index = output_stream_counter
                program_streams_list.append(f"st={subtitle_output_stream_index}")
                output_stream_counter += 1

            program_streams = ":".join(program_streams_list)

            # Add per-stream language metadata for each selected audio track FOR THIS CHANNEL
            spec_to_lang_map = {spec: lang for name, (spec, lang) in channel["audio_track_map"].items()}
            
            for j, specifier in enumerate(selected_audio_specifiers):
                lang_code = "und"
                if specifier == "a:0": # Handle "Default Audio"
                    # Find the first audio stream in the map (excluding the "Default Audio" entry itself)
                    first_audio_entry = next((item for key, item in channel["audio_track_map"].items() if key != "Default Audio"), None)
                    if first_audio_entry:
                        lang_code = first_audio_entry[1] # Get the language code
                else:
                    lang_code = spec_to_lang_map.get(specifier, "und")
                
                metadata_args.extend([f"-metadata:s:a:{total_audio_streams_mapped}", f"language={lang_code}"])
                total_audio_streams_mapped += 1
            
            # Add program and essential service metadata (for SDT)
            program_args.extend(["-program", f"title={channel['name'].get()}:program_num={channel['pid'].get()}:{program_streams}"])
            metadata_args.extend([f"-metadata:s:p:{i}", f"service_name={channel['name'].get()}"])
            metadata_args.extend([f"-metadata:s:p:{i}", f"service_provider={channel['provider'].get()}"])


        # --- Build Final Command ---
        if filter_complex_parts:
            ffmpeg_cmd.extend(["-filter_complex", ";".join(filter_complex_parts)])

        ffmpeg_cmd.extend(output_map_args)

        # Get video format settings
        resolution, scan_type, frame_rate = self.video_format_map[self.video_format_display.get()]

        # Apply common encoding settings that apply to all streams of a given type
        video_codec = self.video_codec.get()
        video_bitrate_k = self.video_bitrate.get()
        try:
            video_bitrate_val = int(video_bitrate_k)
        except (ValueError, TypeError):
            video_bitrate_val = 0 # Fallback

        common_video_opts = [
            "-pix_fmt", self.pix_fmt.get(), "-r", frame_rate, "-s", resolution, "-aspect", self.aspect_ratio.get(),
            "-maxrate", f"{video_bitrate_k}k", "-bufsize", f"{video_bitrate_val * 2}k"
        ]
        if scan_type != "prog":
            common_video_opts.extend(["-field_order", scan_type])

        preset_val = self.preset.get().split(" ")[0] # Gets "p4" from "p4 (medium)"

        # Add encoder-specific options
        if 'nvenc' in video_codec:
            # Options for NVIDIA NVENC hardware encoders
            common_video_opts.extend(["-preset", preset_val, "-tune", "hq", "-rc", "vbr", "-g", "12"])
        elif 'qsv' in video_codec:
            # Options for Intel QSV hardware encoders
            # QSV has different preset names and options. 'veryfast' is a good balance.
            common_video_opts.extend(["-preset", preset_val, "-tune", "hq", "-rc", "vbr", "-g", "12"])
            if self.use_bframes_var.get():
                common_video_opts.extend(["-bf", "3"])
            else:
                common_video_opts.extend(["-bf", "0"])
        else:
            # Options for software encoders (libx264, mpeg2video, etc.)
            common_video_opts.extend([
                "-preset", preset_val, "-g", "50" # Use a longer GOP for better efficiency
            ])

        common_audio_opts = ["-ar", self.audio_samplerate.get(), "-ac", "2"]
        # Add loudnorm filter only if the checkbox is ticked
        if self.use_loudnorm_var.get():
            common_audio_opts.extend(["-af", "loudnorm=I=-23:TP=-2:LRA=11"])
        
        # Apply codecs and options to all mapped streams
        if 'nvenc' not in video_codec: # B-frames for software encoders
            if self.use_bframes_var.get():
                ffmpeg_cmd.extend(["-bf", "3"])
            else:
                ffmpeg_cmd.extend(["-bf", "0"])
        ffmpeg_cmd.extend([f"-c:v", self.video_codec.get(), f"-b:v", f"{video_bitrate_k}k"])
        ffmpeg_cmd.extend(common_video_opts)
        
        ffmpeg_cmd.extend([f"-c:a", self.audio_codec.get(), f"-b:a", f"{self.audio_bitrate.get()}k"])
        ffmpeg_cmd.extend(common_audio_opts)
        ffmpeg_cmd.extend(codec_args) # Add subtitle codec arguments here
        
        ffmpeg_cmd.extend(program_args)
        ffmpeg_cmd.extend(metadata_args)

        ffmpeg_cmd.extend(["-muxrate", self.mux_rate_var.get(), "-f", "mpegts", "pipe:1"])

        # Calculate output frequency in Hz
        try:
            satellite_freq_mhz = int(self.dek_freq.get())
            lnb_lo_mhz = int(self.lnb_lo_freq.get())
            output_freq_mhz = abs(satellite_freq_mhz - lnb_lo_mhz)
            output_freq_hz = str(output_freq_mhz * 1_000_000)
        except (ValueError, TypeError):
            # Fallback if inputs are empty or invalid
            output_freq_hz = "0"

        # The bitrate is removed from the tsp command line. It will be automatically
        # computed by tsp from the PCR in the transport stream from ffmpeg.
        tsp_cmd = [
            self.tsp_path.get(), "-v",
            "-b", self.mux_rate_var.get(),
            "-I", "file", "-",
        ]

        # Add datainject plugin to listen for external TDT/TOT from tdt.exe for time synchronization
        tsp_cmd.extend(["-P", "datainject", "-r", "-s", self.tdt_source.get(), "-b", "50000", "-p", "0x14"])

        # Define a writable path for the analysis file in the system's temp directory
        analysis_file_path = os.path.join(tempfile.gettempdir(), "spts_analysis.txt")
        # Add analysis plugin to generate a report every 90 seconds
        tsp_cmd.extend(["-P", "analyze", "-i", "90", "-o", analysis_file_path])

        # Inject EIT *after* the main SI tables are likely to be created by ffmpeg/tsp
        if eit_xml:
            # Normalize the path to use OS-specific separators (e.g., backslashes on Windows)
            tsp_cmd.extend(["-P", "eitinject", "--pid", "0x0012", "-f", os.path.normpath(eit_xml)])

        tsp_cmd.extend([
            "-P", "nit", "--create", "--build-service-list-descriptors", "--network-id", "0xFF01",
            "-O", "dektec", "-d", self.dek_device.get(), "--modulation", self.dek_mod_var.get(),
            "-f", output_freq_hz, "--convolutional-rate", self.dek_fec_var.get(), "--symbol-rate", self.dek_symrate.get(), "--stuffing"
        ])

        return ffmpeg_cmd, tsp_cmd

    def apply_configuration(self, config):
        """Helper function to set UI elements from a loaded config dictionary."""
        # Set encoding options
        enc = config.get("encoding", {})        
        self.video_bitrate.set(enc.get("video_bitrate", "6000"))
        self.audio_codec.set(enc.get("audio_codec", "mp2"))
        self.update_audio_options() # Update dependent dropdowns
        self.audio_bitrate.set(enc.get("audio_bitrate", "192"))
        self.audio_samplerate.set(enc.get("audio_samplerate", "48000"))
        self.use_loudnorm_var.set(enc.get("use_loudnorm", True))
        # self.audio_lang_display is now per-channel
        self.use_cuda_var.set(enc.get("use_cuda", False))
        self.use_qsv_var.set(enc.get("use_qsv", False))
        self.update_hw_accel_options() # Update dependent dropdowns
        self.video_codec.set(enc.get("video_codec", "mpeg2video"))
        self.preset.set(enc.get("preset", "medium"))
        self.pix_fmt.set(enc.get("pixel_format", "yuv420p"))
        self.aspect_ratio.set(enc.get("aspect_ratio", "4:3"))
        self.video_format_display.set(enc.get("video_format", "720x576i @ 25 fps (PAL SD)"))

        # Set DVB options
        dvb = config.get("dvb", {})
        self.dek_device.set(dvb.get("device_index", "0"))
        self.dvb_standard.set(dvb.get("standard", "DVB-S"))
        self.update_dvb_options() # Update dependent dropdowns
        self.dek_mod_var.set(dvb.get("modulation", "DVB-S-QPSK"))
        self.lnb_lo_freq.set(dvb.get("lnb_lo", "10600"))
        self.dek_freq.set(dvb.get("frequency", "11797"))
        self.dek_symrate.set(dvb.get("symbol_rate", "27500000"))
        self.dek_fec_var.set(dvb.get("fec", "3/4"))
        self.mux_rate_var.set(dvb.get("mux_rate", "33790800"))
        self.tdt_source.set(dvb.get("tdt_source", "127.0.0.1:32000"))

        # Set EIT path
        self.eit_path.set(config.get("eit", {}).get("path", ""))

        # Set executable paths
        paths = config.get("paths", {})
        self.ffmpeg_path.set(paths.get("ffmpeg", "ffmpeg"))
        self.tsp_path.set(paths.get("tsp", "tsp"))
        self.tdt_path.set(paths.get("tdt", "tdt.exe"))

        # Add and configure channels
        for ch_conf in config.get("channels", []):
            self.add_channel()
            new_channel = self.channels[-1] # Get the channel we just added
            for key, value in ch_conf.items():
                if key in new_channel and hasattr(new_channel[key], 'set'):
                    new_channel[key].set(value)
            
            # Restore probed track data if it exists in the config
            if "audio_track_map" in ch_conf:
                new_channel["audio_track_map"] = ch_conf.get("audio_track_map", {"Default Audio": ("a:0", "und")})
            if "selected_audio_specifiers" in ch_conf:
                new_channel["selected_audio_specifiers"] = ch_conf.get("selected_audio_specifiers", ["a:0"])
            if "subtitle_track_map" in ch_conf:
                new_channel["subtitle_track_map"] = ch_conf["subtitle_track_map"]
                new_channel["subtitle_track_combobox"]['values'] = list(ch_conf["subtitle_track_map"].keys())


    def update_command_preview(self):
        try:
            ffmpeg_cmd, tsp_cmd = self.get_command()
            # Create a readable string for the text box, quoting arguments with spaces
            def quote_arg(arg):
                return f'"{arg}"' if ' ' in arg else arg
            ffmpeg_cmd = [quote_arg(arg) for arg in ffmpeg_cmd]
            tsp_cmd = [quote_arg(arg) for arg in tsp_cmd]
            full_command_str = " ".join(ffmpeg_cmd) + " | " + " ".join(tsp_cmd)

            self.command_preview.delete("1.0", tk.END)
            self.command_preview.insert(tk.END, full_command_str)
        except Exception as e:
            self.command_preview.delete("1.0", tk.END)
            self.command_preview.insert(tk.END, f"Error generating command: {e}")

    def process_log_queue(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log_message(line)
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_log_queue)

    def stream_reader(self, stream, prefix):
        """Reads a stream line by line and puts it into the queue, handling potential decoding errors."""
        try:
            for line in iter(stream.readline, ''):
                self.log_queue.put(f"{prefix}: {line}")
        finally:
            stream.close()

    def run_command(self):
        try:
            ffmpeg_cmd, tsp_cmd = self.get_command()
            self.log_queue.put("--- Starting processes ---\n")

            # Start the external TDT injector
            tdt_cmd = [self.tdt_path.get(), "32000"]
            self.tdt_process = subprocess.Popen(tdt_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW)
            threading.Thread(target=self.stream_reader, args=(self.tdt_process.stderr, "TDT"), daemon=True).start()

            p1 = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW)
            p2 = subprocess.Popen(tsp_cmd, stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW)

            # Allow p1 to receive a SIGTERM if p2 closes the pipe
            p1.stdout.close()
            self.process = (p1, p2)

            # Start threads to read stderr from both processes
            threading.Thread(target=self.stream_reader, args=(p1.stderr, "FFmpeg"), daemon=True).start()
            threading.Thread(target=self.stream_reader, args=(p2.stderr, "TSP"), daemon=True).start()

            # Wait for the tsp process to complete
            p2.wait()
            self.log_queue.put(f"--- TSP process finished with exit code: {p2.returncode} ---\n")
            p1.poll() # Check if ffmpeg is still running
            if p1.returncode is not None:
                self.log_queue.put(f"--- FFmpeg process finished with exit code: {p1.returncode} ---\n")

        except FileNotFoundError as e:
            self.log_queue.put(f"ERROR: Command not found: {e.filename}. Make sure ffmpeg and tsp are in your system's PATH.\n")
            messagebox.showerror("Error", f"Command not found: {e.filename}. Make sure ffmpeg and tsp are in your system's PATH.")
        except Exception as e:
            self.log_queue.put(f"ERROR: An unexpected error occurred: {e}\n")
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")
        finally:
            self.stop_process() # Ensure buttons are reset

    def start_process(self):
        self.clear_log()
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        # self.preview_button.config(state=tk.DISABLED) # Keep preview active
        self.clear_log_button.config(state=tk.DISABLED)
        self.status_label.config(text="Status: Running...")

        # Run the command in a separate thread to keep the GUI responsive
        thread = threading.Thread(target=self.run_command, daemon=True)
        thread.start()

    def stop_process(self):
        if self.process:
            p1, p2 = self.process
            try:
                p2.terminate() # Terminate tsp first
            except ProcessLookupError:
                pass
            try:
                p1.terminate() # Then terminate ffmpeg
            except ProcessLookupError:
                pass
            self.process = None
            self.log_queue.put("--- Processes terminated by user ---\n")
        if self.tdt_process:
            try:
                self.tdt_process.terminate()
            except ProcessLookupError:
                pass
            self.status_label.config(text="Status: Stopped")

        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        # self.preview_button.config(state=tk.NORMAL)
        self.clear_log_button.config(state=tk.NORMAL)

    def on_closing(self):
        """Handles the window closing event to ensure child processes are killed."""
        self.stop_process() # This will terminate ffmpeg and tsp if they are running
        self.destroy()      # This closes the Tkinter window

    def _create_media_tools_ui(self, parent_tab):
        """Creates the UI for the unified media tools."""
        tools_frame = ttk.Labelframe(parent_tab, text="Media Tools", padding=(15, 10), style="Card.TLabelframe")
        tools_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        tools_frame.grid_columnconfigure(0, weight=1)
        # Make the log area (row 4) inside the tools frame expand
        tools_frame.grid_rowconfigure(4, weight=1) # Make log area resizable

        # --- Tool Selection ---
        tool_selection_frame = ttk.Frame(tools_frame)
        tool_selection_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(tool_selection_frame, text="Tool:").pack(side=tk.LEFT, padx=(0, 10))
        self.tool_type = tk.StringVar(value="Video Converter")
        tool_combobox = ttk.Combobox(tool_selection_frame, textvariable=self.tool_type, values=["Video Converter", "Remux to TS", "Bitrate Converter", "Subtitle Ripper"], state="readonly")
        ToolTip(tool_combobox, "Select the conversion or remuxing tool to use.")
        tool_combobox.pack(fill=tk.X, expand=True)
        tool_combobox.bind("<<ComboboxSelected>>", self.on_tool_type_change)

        # --- Input Files ---
        files_frame = ttk.Frame(tools_frame)
        files_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        files_frame.grid_columnconfigure(0, weight=1)

        ttk.Label(files_frame, text="Input Files:").grid(row=0, column=0, sticky='w')
        self.tool_files_listbox = tk.Listbox(files_frame, height=6, selectmode=tk.EXTENDED)
        self.tool_files_listbox.grid(row=1, column=0, sticky="nsew")
        ToolTip(self.tool_files_listbox, "List of input files for the selected tool.")
        listbox_scrollbar = ttk.Scrollbar(files_frame, orient="vertical", command=self.tool_files_listbox.yview)
        listbox_scrollbar.grid(row=1, column=1, sticky="ns")
        self.tool_files_listbox.config(yscrollcommand=listbox_scrollbar.set)

        files_buttons_frame = ttk.Frame(files_frame)
        files_buttons_frame.grid(row=2, column=0, columnspan=2, sticky='w', pady=(5,0))
        add_btn = ttk.Button(files_buttons_frame, text="Add Files", command=self.add_tool_files)
        add_btn.pack(side=tk.LEFT); ToolTip(add_btn, "Add one or more media files to the list.")
        remove_btn = ttk.Button(files_buttons_frame, text="Remove Selected", command=self.remove_tool_files)
        remove_btn.pack(side=tk.LEFT, padx=5); ToolTip(remove_btn, "Remove the selected files from the list.")
        clear_btn = ttk.Button(files_buttons_frame, text="Clear All", command=lambda: self.tool_files_listbox.delete(0, tk.END))
        clear_btn.pack(side=tk.LEFT); ToolTip(clear_btn, "Remove all files from the list.")

        # --- Settings ---
        self.converter_settings_frame = ttk.Frame(tools_frame)
        self.converter_settings_frame.grid(row=2, column=0, sticky="ew", pady=10)
        self.converter_settings_frame.grid_columnconfigure(1, weight=1)
        self.converter_settings_frame.grid_columnconfigure(3, weight=1)
        self.converter_settings_frame.grid_columnconfigure(5, weight=1)

        # --- Row 0: HW Accel ---
        self.converter_use_cuda_var = tk.BooleanVar(value=False)
        self.converter_cuda_checkbox = ttk.Checkbutton(self.converter_settings_frame, text="Use NVIDIA CUDA", variable=self.converter_use_cuda_var, command=self.update_tool_hw_accel_options)
        self.converter_cuda_checkbox.grid(row=0, column=0, columnspan=2, sticky='w', padx=5, pady=2)
        ToolTip(self.converter_cuda_checkbox, "Enable to use your NVIDIA GPU for encoding (NVENC).")
        if not self.cuda_supported:
            self.converter_cuda_checkbox.config(state=tk.DISABLED)

        self.converter_use_qsv_var = tk.BooleanVar(value=False)
        self.converter_qsv_checkbox = ttk.Checkbutton(self.converter_settings_frame, text="Use Intel QSV", variable=self.converter_use_qsv_var, command=self.update_tool_hw_accel_options)
        ToolTip(self.converter_qsv_checkbox, "Enable to use your Intel GPU for encoding (QSV).")
        self.converter_qsv_checkbox.grid(row=0, column=2, columnspan=2, sticky='w', padx=5, pady=2)
        if not self.qsv_supported:
            self.converter_qsv_checkbox.config(state=tk.DISABLED)

        # --- Row 1: Video Codec ---
        self.tool_vcodec_map = {
            "software": [
                "libx264",    # H.264/AVC
                "libx265",    # H.265/HEVC
                "mpeg2video", # MPEG-2
                "mpeg4",      # MPEG-4 Part 2
                "libvpx-vp9", # VP9
            ],
            "cuda": ["h264_nvenc", "hevc_nvenc"],
            "qsv": ["h264_qsv", "hevc_qsv"]
        }
        default_tool_vcodec = "libx264"
        self.converter_vcodec = tk.StringVar(value=default_tool_vcodec)
        self.converter_vcodec_label = ttk.Label(self.converter_settings_frame, text="Video Codec:")
        self.converter_vcodec_label.grid(row=1, column=0, sticky='w', padx=5)
        self.converter_vcodec_combobox = ttk.Combobox(self.converter_settings_frame, textvariable=self.converter_vcodec, values=self.tool_vcodec_map["software"], state="readonly")
        ToolTip(self.converter_vcodec_combobox, "Select the video codec for the conversion.")
        self.converter_vcodec_combobox.grid(row=1, column=1, sticky='ew', pady=2)

        # --- Row 2: Codec Preset ---
        default_tool_preset = "medium"
        self.converter_preset = tk.StringVar(value=default_tool_preset)
        ttk.Label(self.converter_settings_frame, text="Codec Preset:").grid(row=2, column=0, sticky='w', padx=5)
        self.converter_preset_combobox = ttk.Combobox(self.converter_settings_frame, textvariable=self.converter_preset, values=self.preset_map["software"], state="readonly")
        ToolTip(self.converter_preset_combobox, "Controls the encoding speed vs. compression efficiency.")
        self.converter_preset_combobox.grid(row=2, column=1, sticky='ew', pady=2)

        # --- Row 3: Audio Settings ---
        default_tool_acodec = "mp2"
        self.converter_acodec = tk.StringVar(value=default_tool_acodec)
        self.converter_acodec.trace_add("write", self.update_tool_audio_options)
        ttk.Label(self.converter_settings_frame, text="Audio Codec:").grid(row=3, column=0, sticky='w', padx=5, pady=5)
        self.converter_acodec_combobox = ttk.Combobox(self.converter_settings_frame, textvariable=self.converter_acodec, values=list(self.audio_options_map.keys()), state="readonly")
        ToolTip(self.converter_acodec_combobox, "Select the audio codec for the conversion.")
        self.converter_acodec_combobox.grid(row=3, column=1, sticky='ew', pady=5)

        self.converter_abitrate = tk.StringVar()
        ttk.Label(self.converter_settings_frame, text="Audio Bitrate (k):").grid(row=3, column=2, sticky='w', padx=(15, 5), pady=5)
        self.converter_abitrate_combobox = ttk.Combobox(self.converter_settings_frame, textvariable=self.converter_abitrate, state="readonly")
        ToolTip(self.converter_abitrate_combobox, "Select the target audio bitrate in kilobits per second.")
        self.converter_abitrate_combobox.grid(row=3, column=3, sticky='ew', pady=5)

        # --- Row 4: Audio Samplerate ---
        self.converter_asamplerate = tk.StringVar()
        ttk.Label(self.converter_settings_frame, text="Sample Rate (Hz):").grid(row=4, column=0, sticky='w', padx=5)
        self.converter_asamplerate_combobox = ttk.Combobox(self.converter_settings_frame, textvariable=self.converter_asamplerate, state="readonly")
        ToolTip(self.converter_asamplerate_combobox, "Select the audio sample rate.")
        self.converter_asamplerate_combobox.grid(row=4, column=1, sticky='ew')

        # --- Row 5: Resolution and Framerate ---
        # The map's value is a tuple: (resolution_string, scan_type_char)
        # We derive this from the main video_format_map, but remove the frame rate from the display text.
        self.tool_resolution_map = {}
        for display_text, (res, scan, fr) in self.video_format_map.items():
            # Remove the frame rate part (e.g., " @ 25 fps") from the display text for the tool
            new_display_text = re.sub(r'\s*@\s*[\d\.]+\s*fps', '', display_text)
            # Map the new display text to the resolution and scan type
            # The scan type from the main map needs to be converted to 'p' or 'i'
            scan_char = 'i' if scan != 'prog' else 'p'
            self.tool_resolution_map[new_display_text] = (res, scan_char)
        
        # Add specific anamorphic resolutions
        self.tool_resolution_map["1440x1080p (HD Anamorphic)"] = ("1440x1080", "p")
        self.tool_resolution_map["1440x1080i (HD Anamorphic)"] = ("1440x1080", "i")
        self.tool_resolution_map["704x576i (PAL Anamorphic)"] = ("704x576", "i")
        self.tool_resolution_map["704x480i (NTSC Anamorphic)"] = ("704x480", "i")


        # Remove duplicates by converting to a dict and back to a list
        unique_keys = list(dict.fromkeys(self.tool_resolution_map.keys()))

        default_tool_res = "1920x1080p (Full HD)"
        self.converter_resolution_display = tk.StringVar(value=default_tool_res)
        ttk.Label(self.converter_settings_frame, text="Resolution:").grid(row=5, column=0, sticky='w', padx=5, pady=(5,0))
        resolution_combo = ttk.Combobox(self.converter_settings_frame, textvariable=self.converter_resolution_display, values=unique_keys, state="readonly")
        ToolTip(resolution_combo, "Select the output resolution and scan type.")
        resolution_combo.grid(row=5, column=1, sticky='ew', pady=(5,0))

        framerate_opts = ["24", "25", "29.97", "30", "50", "59.94", "60"]
        self.converter_framerate = tk.StringVar(value="25")
        ttk.Label(self.converter_settings_frame, text="Frame Rate:").grid(row=5, column=2, sticky='w', padx=(15, 5), pady=(5,0))
        framerate_combo = ttk.Combobox(self.converter_settings_frame, textvariable=self.converter_framerate, values=framerate_opts)
        ToolTip(framerate_combo, "Select the output frame rate.")
        framerate_combo.grid(row=5, column=3, sticky='ew', pady=(5,0))

        default_pix_fmt = "yuv420p"
        self.converter_pix_fmt = tk.StringVar(value=default_pix_fmt)
        self.converter_pix_fmt_label = ttk.Label(self.converter_settings_frame, text="Pixel Format:")
        self.converter_pix_fmt_label.grid(row=5, column=4, sticky='w', padx=(15, 5), pady=(5,0))
        self.converter_pix_fmt_combo = ttk.Combobox(self.converter_settings_frame, textvariable=self.converter_pix_fmt, values=self.pix_fmt_options, state="readonly")
        ToolTip(self.converter_pix_fmt_combo, "Select the pixel format (color space and bit depth).")
        self.converter_pix_fmt_combo.grid(row=5, column=5, sticky='ew', pady=(5,0))

        # Hide resolution/framerate for anamorphic converter initially
        self.converter_resolution_label = self.converter_settings_frame.grid_slaves(row=5, column=0)[0]
        self.converter_resolution_combo = self.converter_settings_frame.grid_slaves(row=5, column=1)[0]
        self.converter_framerate_label = self.converter_settings_frame.grid_slaves(row=5, column=2)[0]
        self.converter_framerate_combo = self.converter_settings_frame.grid_slaves(row=5, column=3)[0]

        # --- Row 6: Video Bitrate and Aspect Ratio ---
        self.converter_vbitrate = tk.StringVar(value="6000")
        ttk.Label(self.converter_settings_frame, text="Video Bitrate (k):").grid(row=6, column=0, sticky='w', padx=5, pady=(5,0))
        converter_vbitrate_entry = ttk.Entry(self.converter_settings_frame, textvariable=self.converter_vbitrate, validate="key", validatecommand=(self.numeric_validate_cmd, '%P'))
        ToolTip(converter_vbitrate_entry, "Enter the target video bitrate in kilobits per second (e.g., 6000 for 6 Mbps).")
        converter_vbitrate_entry.grid(row=6, column=1, sticky='ew', pady=(5,0))

        aspect_opts = ["16:9", "4:3"]
        self.converter_aspect_ratio = tk.StringVar(value="16:9")
        self.converter_aspect_label = ttk.Label(self.converter_settings_frame, text="Aspect Ratio:")
        self.converter_aspect_label.grid(row=6, column=2, sticky='w', padx=(15, 5), pady=(5,0))
        self.converter_aspect_combo = ttk.Combobox(self.converter_settings_frame, textvariable=self.converter_aspect_ratio, values=aspect_opts, state="readonly")
        ToolTip(self.converter_aspect_combo, "Select the display aspect ratio for the output video.")
        self.converter_aspect_combo.grid(row=6, column=3, sticky='ew', pady=(5,0))

        # --- Row 7: Subtitle Ripper Settings ---
        self.subtitle_rip_format_var = tk.StringVar(value="srt")
        self.subtitle_rip_format_label = ttk.Label(self.converter_settings_frame, text="Output Format:")
        self.subtitle_rip_format_label.grid(row=7, column=0, sticky='w', padx=5, pady=(5,0))
        self.subtitle_rip_format_combo = ttk.Combobox(self.converter_settings_frame, textvariable=self.subtitle_rip_format_var, values=["srt", "ass", "vtt"], state="readonly")
        ToolTip(self.subtitle_rip_format_combo, "Select the output format for the ripped subtitle files.")
        self.subtitle_rip_format_combo.grid(row=7, column=1, sticky='ew', pady=(5,0))


        # --- Progress Bar ---
        progress_frame = ttk.Frame(tools_frame)
        progress_frame.grid(row=3, column=0, sticky="ew", pady=(5,0))
        progress_frame.grid_columnconfigure(0, weight=1)
        self.tool_progressbar = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate")
        self.tool_progressbar.grid(row=0, column=0, sticky="ew")

        # --- Log and Actions ---
        log_frame = ttk.Frame(tools_frame)
        log_frame.grid(row=4, column=0, sticky="nsew", pady=(10,0))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)

        self.tool_log = ScrolledText(log_frame, height=8, wrap=tk.WORD, bg="black", fg="white", relief=tk.SUNKEN, borderwidth=1, insertbackground="white")
        self.tool_log.grid(row=0, column=0, sticky="nsew")
        make_readonly(self.tool_log)
        TextContextMenu(self.tool_log)

        action_frame = ttk.Frame(tools_frame)
        action_frame.grid(row=5, column=0, sticky="ew", pady=(10,0))
        self.tool_start_button = ttk.Button(action_frame, text="Start", command=self.start_tool_processing, style="Success.TButton")
        ToolTip(self.tool_start_button, "Start processing the files with the selected tool and settings.")
        self.tool_start_button.pack(side=tk.LEFT)
        self.tool_stop_button = ttk.Button(action_frame, text="Stop", command=self.stop_tool_processing, state=tk.DISABLED)
        ToolTip(self.tool_stop_button, "Stop the current processing task.")
        self.tool_stop_button.pack(side=tk.LEFT, padx=5)

        self.update_tool_audio_options() # Populate audio dropdowns
        self.update_tool_hw_accel_options() # Set initial codec list
        self.on_tool_type_change() # Call once to set initial visibility state

    def on_tool_type_change(self, event=None):
        """Shows or hides settings based on the selected tool."""
        selected_tool = self.tool_type.get()
        # Hide all settings widgets by default
        for child in self.converter_settings_frame.winfo_children():
            child.grid_remove()

        if selected_tool in ["Video Converter", "Bitrate Converter"]:
            # Show all settings widgets
            for child in self.converter_settings_frame.winfo_children():
                child.grid()

            if selected_tool == "Video Converter":
                # Show resolution/framerate
                self.converter_resolution_label.grid()
                self.converter_resolution_combo.grid()
                # Ensure framerate is visible
                self.converter_framerate_label.grid()
                self.converter_framerate_combo.grid()

                self.converter_framerate_label.grid()
                self.converter_framerate_combo.grid()
                self.converter_aspect_label.grid()
                self.converter_aspect_combo.grid()
                self.converter_pix_fmt_label.grid()
                self.converter_pix_fmt_combo.grid()
                self.tool_start_button.config(text="Start Conversion")
            else: # Bitrate Converter
                # Hide resolution/framerate as they are not needed for this tool
                self.converter_resolution_label.grid_remove()
                self.converter_resolution_combo.grid_remove()
                self.converter_framerate_label.grid_remove()
                self.converter_framerate_combo.grid_remove()
                self.converter_aspect_label.grid_remove()
                self.converter_aspect_combo.grid_remove()
                self.converter_pix_fmt_label.grid_remove()
                self.converter_pix_fmt_combo.grid_remove()
                self.tool_start_button.config(text="Start Re-encoding")
        elif selected_tool == "Remux to TS":
            # Only show the framerate option for remuxing
            self.converter_framerate_label.grid()
            self.converter_framerate_combo.grid()
            self.tool_start_button.config(text="Start Remuxing")
        elif selected_tool == "Subtitle Ripper":
            # Only show the subtitle format option
            self.subtitle_rip_format_label.grid()
            self.subtitle_rip_format_combo.grid()
            self.tool_start_button.config(text="Start Ripping")



    def update_tool_audio_options(self, *args):
        """Updates audio bitrate and sample rate options for the Tools tab."""
        codec = self.converter_acodec.get()
        options = self.audio_options_map.get(codec)

        if not options:
            return

        # Update bitrates
        self.converter_abitrate_combobox['values'] = options["bitrates"]
        if self.converter_abitrate.get() not in options["bitrates"]:
            self.converter_abitrate.set(options["default_bitrate"])

        # Update sample rates
        self.converter_asamplerate_combobox['values'] = options["samplerates"]
        if self.converter_asamplerate.get() not in options["samplerates"]:
            self.converter_asamplerate.set(options["samplerates"][0])

    def update_tool_hw_accel_options(self, *args):
        """Manages mutual exclusivity of HW accel options for the Tools tab."""
        use_cuda = self.converter_use_cuda_var.get()
        use_qsv = self.converter_use_qsv_var.get()
        encoder_type = "software"

        # --- Mutual Exclusivity Logic ---
        if use_cuda:
            encoder_type = "cuda"
            self.converter_use_qsv_var.set(False)
            if self.qsv_supported: self.converter_qsv_checkbox.config(state=tk.DISABLED)
        elif use_qsv:
            encoder_type = "qsv"
            self.converter_use_cuda_var.set(False)
            if self.cuda_supported: self.converter_cuda_checkbox.config(state=tk.DISABLED)
        else: # Neither is checked, re-enable both if supported
            encoder_type = "software"
            if self.cuda_supported: self.converter_cuda_checkbox.config(state=tk.NORMAL)
            if self.qsv_supported: self.converter_qsv_checkbox.config(state=tk.NORMAL)

        # --- Update Codec Dropdown ---
        codec_list = self.tool_vcodec_map.get(encoder_type, ["libx264"])
        self.converter_vcodec_combobox['values'] = codec_list
        if self.converter_vcodec.get() not in codec_list:
            self.converter_vcodec.set(codec_list[0])

        # --- Update Preset Dropdown ---
        self.converter_preset_combobox['values'] = self.preset_map[encoder_type]
        if self.converter_preset.get() not in self.preset_map[encoder_type]:
            # Set a sensible default for the new encoder type
            default_preset = "medium" if encoder_type != "cuda" else "p4 (medium)"
            self.converter_preset.set(default_preset)




    def add_tool_files(self):
        files = filedialog.askopenfilenames(title="Select media files", filetypes=[("Video Files", "*.mp4 *.mkv *.mov *.ts *.avi"), ("All files", "*.*")])
        for f in files:
            self.tool_files_listbox.insert(tk.END, f)

    def remove_tool_files(self):
        selected_indices = self.tool_files_listbox.curselection()
        for i in reversed(selected_indices):
            self.tool_files_listbox.delete(i)

    def start_tool_processing(self):
        files_to_process = self.tool_files_listbox.get(0, tk.END)
        if not files_to_process:
            messagebox.showwarning("No Files", "Please add files to the list before starting.")
            return

        self.tool_log.delete("1.0", tk.END)
        self.tool_progressbar['value'] = 0
        self.tool_start_button.config(state=tk.DISABLED)
        self.tool_stop_button.config(state=tk.NORMAL)

        thread = threading.Thread(target=self.run_tool_thread, args=(files_to_process,), daemon=True)
        thread.start()

    def stop_tool_processing(self):
        if self.tool_process:
            try:
                self.tool_process.terminate()
                self.tool_log.insert(tk.END, "\n--- PROCESS STOPPED BY USER ---\n")
            except ProcessLookupError:
                pass # Process already finished
        self.tool_process = None
        self.tool_start_button.config(state=tk.NORMAL)
        self.tool_stop_button.config(state=tk.DISABLED)

    def _get_media_duration(self, file_path):
        """Uses ffprobe to get the duration of a media file in seconds."""
        ffmpeg_exe = self.ffmpeg_path.get()
        ffprobe_exe = "ffprobe"
        if os.path.isabs(ffmpeg_exe):
            dir_name = os.path.dirname(ffmpeg_exe)
            ffprobe_exe = os.path.join(dir_name, "ffprobe.exe" if os.name == 'nt' else "ffprobe")

        cmd = [ffprobe_exe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            return float(result.stdout.strip())
        except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
            self.tool_log.insert(tk.END, f"--- Could not get duration for {os.path.basename(file_path)}: {e} ---\n")
            return None

    def _get_media_streams(self, file_path):
        """Uses ffprobe to get stream information for a media file."""
        ffmpeg_exe = self.ffmpeg_path.get()
        ffprobe_exe = "ffprobe"
        if os.path.isabs(ffmpeg_exe):
            dir_name = os.path.dirname(ffmpeg_exe)
            ffprobe_exe = os.path.join(dir_name, "ffprobe.exe" if os.name == 'nt' else "ffprobe")

        cmd = [ffprobe_exe, '-v', 'error', '-show_streams', '-print_format', 'json', file_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            return json.loads(result.stdout).get("streams", [])
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
            self.tool_log.insert(tk.END, f"--- Could not probe streams for {os.path.basename(file_path)}: {e} ---\n")
            self.tool_log.see(tk.END)
            return []

    def _tool_log_message(self, message):
        """Helper to insert log messages from the tool thread."""
        def inserter():
            self.tool_log.insert(tk.END, message)
            self.tool_log.see(tk.END)
        self.after(0, inserter)

    def _update_tool_progress(self, current_progress, total_progress):
        """Updates the progress bar from a thread."""
        self.tool_progressbar['value'] = (current_progress / total_progress) * 100

    def run_tool_thread(self, files):
        tool_type = self.tool_type.get()
        num_files = len(files)
        total_duration = sum(self._get_media_duration(f) or 0 for f in files)
        if tool_type == "Subtitle Ripper":
            total_duration = num_files # For ripper, progress is per file
        processed_duration = 0
        
        error_occurred = False
        final_message = ""

        for i, file_path in enumerate(files):
            self._tool_log_message(f"--- Processing file {i+1} of {num_files}: {os.path.basename(file_path)} ---\n")

            duration = self._get_media_duration(file_path)

            if tool_type == "Bitrate Converter":
                output_path = f"{os.path.splitext(file_path)[0]}_reencoded.mp4"
                vcodec_choice = self.converter_vcodec.get()
                vbitrate = self.converter_vbitrate.get()
                acodec = self.converter_acodec.get()
                abitrate = self.converter_abitrate.get()
                asamplerate = self.converter_asamplerate.get()
                resolution, scan_type = self.tool_resolution_map[self.converter_resolution_display.get()]
                preset = self.converter_preset.get().split(" ")[0]
                cmd = [self.ffmpeg_path.get(), '-hide_banner', '-y', '-i', file_path]

                if 'nvenc' in vcodec_choice:
                    cmd.extend(['-c:v', vcodec_choice, '-preset', preset, '-rc', 'cbr', '-tune', 'hq'])
                elif 'qsv' in vcodec_choice:
                    cmd.extend(['-c:v', vcodec_choice, '-preset', preset, '-g', '50', '-rc', 'cbr'])
                else: # libx264
                    cmd.extend(['-c:v', vcodec_choice, '-preset', preset])

                cmd.extend(['-b:v', f'{vbitrate}k', '-maxrate', f'{vbitrate}k', '-bufsize', f'{int(vbitrate)*2}k'])
                # Bitrate converter does not change resolution or framerate
                if scan_type == "i":
                    cmd.extend(['-flags', '+ilme+ildct'])
                cmd.extend(['-c:a', acodec, '-b:a', f'{abitrate}k', '-ar', asamplerate, '-ac', '2'])
                cmd.extend(['-progress', 'pipe:1']) # Output progress to stdout
                cmd.append(output_path)

            elif tool_type == "Video Converter":
                vcodec_choice = self.converter_vcodec.get()
                
                # Determine the best container format for the selected codec
                container_map = {
                    "mpeg2video": ".mpg",
                    "libvpx-vp9": ".mkv"
                }
                output_ext = container_map.get(vcodec_choice, ".mp4")
                output_path = f"{os.path.splitext(file_path)[0]}_converted{output_ext}"

                vcodec_choice = self.converter_vcodec.get()
                vbitrate = self.converter_vbitrate.get()
                acodec = self.converter_acodec.get()
                abitrate = self.converter_abitrate.get()
                asamplerate = self.converter_asamplerate.get()
                resolution, scan_type = self.tool_resolution_map[self.converter_resolution_display.get()]
                framerate = self.converter_framerate.get()
                preset = self.converter_preset.get().split(" ")[0]
                aspect_ratio = self.converter_aspect_ratio.get()
                pix_fmt = self.converter_pix_fmt.get()
                cmd = [self.ffmpeg_path.get(), '-hide_banner', '-y', '-i', file_path]
                
                # Set SAR based on selected resolution for anamorphic output
                if resolution == "1440x1080":
                    cmd.extend(['-vf', 'setsar=4/3'])
                elif resolution == "704x576": # PAL Anamorphic
                    cmd.extend(['-vf', 'setsar=16/11'])
                elif resolution == "704x480": # NTSC Anamorphic
                    cmd.extend(['-vf', 'setsar=40/33'])
                else: # Default behavior for non-anamorphic resolutions
                    cmd.extend(['-vf', 'setsar=1/1']) # Assume square pixels

                if 'nvenc' in vcodec_choice:
                    cmd.extend(['-c:v', vcodec_choice, '-preset', preset, '-rc', 'cbr', '-tune', 'hq'])
                elif 'qsv' in vcodec_choice:
                    cmd.extend(['-c:v', vcodec_choice, '-preset', preset, '-g', '50', '-rc', 'cbr'])
                else: # libx264
                    cmd.extend(['-c:v', vcodec_choice, '-preset', preset])

                cmd.extend(['-b:v', f'{vbitrate}k', '-maxrate', f'{vbitrate}k', '-bufsize', f'{int(vbitrate)*2}k'])
                cmd.extend(['-s', resolution, '-r', framerate, '-pix_fmt', pix_fmt, '-aspect', aspect_ratio])
                if scan_type == "i":
                    cmd.extend(['-flags', '+ilme+ildct'])
                cmd.extend(['-c:a', acodec, '-b:a', f'{abitrate}k', '-ar', asamplerate, '-ac', '2'])
                cmd.extend(['-progress', 'pipe:1']) # Output progress to stdout
                cmd.append(output_path)
            
            elif tool_type == "Remux to TS":
                output_path = f"{os.path.splitext(file_path)[0]}.ts"
                framerate = self.converter_framerate.get()
                cmd = [self.ffmpeg_path.get(), '-hide_banner', '-y', '-i', file_path]
                if framerate:
                    cmd.extend(['-r', framerate])
                cmd.extend(['-c', 'copy', '-f', 'mpegts', '-progress', 'pipe:1', output_path])

            elif tool_type == "Subtitle Ripper":
                output_format = self.subtitle_rip_format_var.get()
                # Map the user-friendly format name to the actual ffmpeg codec name.
                codec_map = {
                    "srt": "srt",
                    "ass": "ass",
                    "vtt": "webvtt"
                }
                output_codec = codec_map.get(output_format, output_format)
                streams = self._get_media_streams(file_path)
                subtitle_streams = [s for s in streams if s.get('codec_type') == 'subtitle']

                if not subtitle_streams:
                    self._tool_log_message(f"--- No subtitle tracks found in {os.path.basename(file_path)}. Skipping. ---\n\n")
                    processed_duration += 1 # Increment file-based progress
                    self.after(0, self._update_tool_progress, processed_duration, total_duration)
                    continue

                self._tool_log_message(f"--- Found {len(subtitle_streams)} subtitle track(s). Ripping... ---\n")

                for sub_stream in subtitle_streams:
                    stream_index = sub_stream['index']
                    lang = sub_stream.get('tags', {}).get('language', 'und')
                    output_path = f"{os.path.splitext(file_path)[0]}_track_{stream_index}_{lang}.{output_format}"

                    # Check if we are converting from a text-based subtitle to a bitmap-based one.
                    # This requires a more complex filter graph to render the subtitles.
                    cmd = [self.ffmpeg_path.get(), '-hide_banner', '-y', '-i', file_path, '-map', f'0:{stream_index}', '-c:s', output_codec, output_path]

                    try:
                        # For ripping, we don't need progress, just run and wait.
                        self.tool_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                        stdout, stderr = self.tool_process.communicate()
                        if self.tool_process.returncode == 0:
                            self._tool_log_message(f"--- Successfully ripped track {stream_index} to {os.path.basename(output_path)} ---\n")
                        else:
                            self._tool_log_message(f"--- FAILED to rip track {stream_index}. FFmpeg says: ---\n{stderr}\n")
                            error_occurred = True
                    except Exception as e:
                        self._tool_log_message(f"--- ERROR ripping track {stream_index}: {e} ---\n")
                        error_occurred = True
                self._tool_log_message("\n") # Add a newline after processing a file
                processed_duration += 1 # Increment file-based progress
                self.after(0, self._update_tool_progress, processed_duration, total_duration)
                continue # Skip the generic process handling below
            else:
                self._tool_log_message(f"--- ERROR: Unknown tool type '{tool_type}' ---\n\n")
                break

            try:
                self.tool_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                
                # Thread to read stderr and log it
                def log_stderr():
                    for line in iter(self.tool_process.stderr.readline, ''):
                        self._tool_log_message(line)
                
                stderr_thread = threading.Thread(target=log_stderr, daemon=True)
                stderr_thread.start()

                # Read stdout for progress
                for line in iter(self.tool_process.stdout.readline, ''):
                    if 'out_time_ms=' in line and duration:
                        try:
                            current_time_ms = int(line.strip().split('=')[1])
                            current_time_s = current_time_ms / 1_000_000
                            self.after(0, self._update_tool_progress, processed_duration + current_time_s, total_duration)
                        except (ValueError, IndexError):
                            continue # Ignore malformed progress lines

                self.tool_process.wait()
                if self.tool_process.returncode == 0:
                    self._tool_log_message(f"--- Successfully created {os.path.basename(output_path)} ---\n\n")
                else:
                    self._tool_log_message(f"--- FAILED to process {os.path.basename(file_path)} ---\n\n")
                    error_occurred = True
                    final_message = f"Processing failed on file: {os.path.basename(file_path)}.\nCheck the log for details."
                    break # Stop on failure
            except Exception as e:
                self._tool_log_message(f"--- ERROR: {e} ---\n\n")
                error_occurred = True
                final_message = f"An unexpected error occurred: {e}"
                break # Stop on error
            
            if duration:
                processed_duration += duration

        # After the loop, show a final status message box on the main thread
        if not error_occurred:
            final_message = f"Task completed successfully for {num_files} file(s)."
            self.after(0, messagebox.showinfo, "Task Complete", final_message)
        else:
            self.after(0, messagebox.showerror, "Task Failed", final_message)

        self.after(0, self.stop_tool_processing)

    def delete_eit_file(self):
        """Finds and deletes all .xml files in the system's temp directory."""
        temp_dir = tempfile.gettempdir()
        try:
            # Find all files ending with .xml in the temp directory
            xml_files = [f for f in os.listdir(temp_dir) if f.endswith('.xml') and os.path.isfile(os.path.join(temp_dir, f))]
        except OSError as e:
            messagebox.showerror("Error", f"Could not read temporary directory: {e}", parent=self)
            return

        if not xml_files:
            messagebox.showinfo("No Files Found", "No temporary .xml files were found to delete.", parent=self)
            return

        # Prepare confirmation message
        file_list_str = "\n".join(f"- {f}" for f in xml_files[:10]) # Show up to 10 files
        if len(xml_files) > 10:
            file_list_str += f"\n... and {len(xml_files) - 10} more."

        confirm_msg = f"Are you sure you want to delete these {len(xml_files)} file(s) from the temporary directory?\n\n{file_list_str}"

        if messagebox.askyesno("Confirm Deletion", confirm_msg, parent=self):
            deleted_count = 0
            errors = []
            for filename in xml_files:
                file_path = os.path.join(temp_dir, filename)
                try:
                    os.remove(file_path)
                    self.log_message(f"Deleted temporary EPG file: {file_path}\n")
                    deleted_count += 1
                except OSError as e:
                    errors.append(filename)
                    self.log_message(f"ERROR: Failed to delete {file_path}: {e}\n")
            
            self.eit_path.set("") # Clear the path in the UI regardless
            self.update_command_preview()
            messagebox.showinfo("Deletion Complete", f"Successfully deleted {deleted_count} of {len(xml_files)} file(s).", parent=self)

    def open_epg_editor(self):
        """Opens the Toplevel window for creating and editing EPG events."""
        if not self.channels:
            messagebox.showwarning("No Channels", "Please add at least one channel in the 'Services' tab before creating EPG events.")
            return

        # --- Check if an existing EIT file should be loaded ---
        existing_eit_path = self.eit_path.get()
        if existing_eit_path and os.path.exists(existing_eit_path):
            if messagebox.askyesno("Load Existing EPG?", f"An EPG file is already specified:\n\n{os.path.basename(existing_eit_path)}\n\nDo you want to load its events for editing?"):
                try:
                    self.epg_events = self._parse_eit_xml(existing_eit_path)
                    self.log_message(f"Loaded {len(self.epg_events)} events from {existing_eit_path}\n")
                except Exception as e:
                    messagebox.showerror("Parse Error", f"Failed to parse the XML file: {e}")
                    # Don't proceed if parsing fails
                    return
            else:
                # User chose not to load, so clear the internal list to start fresh
                self.epg_events = []
        else:
            # No file or path is invalid, start with a clean slate
            self.epg_events = []

        editor = tk.Toplevel(self)
        editor.title("EPG Event Editor")
        editor.geometry("950x600")
        editor.transient(self)
        editor.grab_set()

        # --- Main UI setup for the editor ---
        self._setup_epg_editor_ui(editor)

    def _parse_eit_xml(self, xml_path):
        """Parses a TSDuck EIT XML file and returns a list of event dictionaries."""
        new_events = []
        pid_to_channel_name = {ch['pid'].get(): ch['name'].get() for ch in self.channels}

        tree = ET.parse(xml_path)
        root = tree.getroot()

        for eit_table in root.findall('EIT'):
            service_id = eit_table.get('service_id')
            channel_name = pid_to_channel_name.get(service_id)
            if not channel_name:
                continue # Skip events for services not currently in the UI

            for event_node in eit_table.findall('event'):
                event_data = {"channel": channel_name}
                try:
                    # Time and Duration
                    start_str = event_node.get('start_time')
                    duration_str = event_node.get('duration')
                    start_time = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                    h, m, s = map(int, duration_str.split(':'))
                    end_time = start_time + timedelta(hours=h, minutes=m, seconds=s)
                    event_data['start'] = start_time
                    event_data['end'] = end_time

                    # Descriptors
                    short_desc_node = event_node.find('short_event_descriptor')
                    if short_desc_node is not None:
                        event_data['title'] = short_desc_node.find('event_name').text or ""
                        event_data['short_desc'] = short_desc_node.find('text').text or ""
                        event_data['language'] = short_desc_node.get('language_code', 'eng')

                    ext_desc_node = event_node.find('extended_event_descriptor')
                    event_data['ext_desc'] = ext_desc_node.find('text').text if ext_desc_node is not None and ext_desc_node.find('text') is not None else ""

                    content_node = event_node.find('content_descriptor/content')
                    if content_node is not None:
                        event_data['nibble1'] = int(content_node.get('content_nibble_level_1', 15))
                        event_data['nibble2'] = int(content_node.get('content_nibble_level_2', 0))

                    parental_node = event_node.find('parental_rating_descriptor/country')
                    if parental_node is not None:
                        event_data['country_code'] = parental_node.get('country_code')
                        rating_val = int(parental_node.get('rating'), 16)
                        event_data['min_age'] = str(rating_val + 3) if 1 <= rating_val <= 15 else "None"

                    new_events.append(event_data)
                except (ValueError, TypeError, AttributeError) as e:
                    self.log_message(f"Warning: Skipping malformed event in XML: {e}\n")
        return new_events

    def _setup_epg_editor_ui(self, editor):
        """Helper function to create all the widgets for the EPG editor window."""

        main_frame = ttk.Frame(editor, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.grid_rowconfigure(1, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_columnconfigure(1, weight=1)

        # --- Event List (Left Side) ---
        list_frame = ttk.Labelframe(main_frame, text="Events", padding=10)
        list_frame.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 10))
        list_frame.grid_rowconfigure(1, weight=1) # Make the treeview expand
        list_frame.grid_columnconfigure(0, weight=1)

        # --- Search Bar ---
        search_frame = ttk.Frame(list_frame)
        search_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        search_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(search_frame, text="Filter:").grid(row=0, column=0, sticky="w")
        search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=search_var)
        search_entry.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        ToolTip(search_entry, "Filter events by title (case-insensitive).")

        tree = ttk.Treeview(list_frame, columns=("channel", "title", "start"), show="headings")
        tree.heading("channel", text="Channel", command=lambda: self.sort_epg_tree(tree, "channel", False))
        tree.heading("title", text="Title")
        tree.heading("start", text="Start Time")
        tree.column("channel", width=100)
        tree.column("title", width=150)
        tree.column("start", width=120)
        tree.grid(row=1, column=0, sticky="nsew")
        
        # Store references on the editor window for easy access
        editor.tree = tree
        editor.selected_event_index = None # To track which event is being edited

        list_buttons = ttk.Frame(list_frame)
        list_buttons.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(list_buttons, text="Delete Selected", command=lambda: self.delete_epg_event(editor)).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(list_buttons, text="Duplicate Selected", command=lambda: self.duplicate_epg_event(editor)).pack(side=tk.LEFT)

        # --- Event Form (Right Side) ---
        form_frame = ttk.Labelframe(main_frame, text="Event Details", padding=10)
        form_frame.grid(row=0, column=1, sticky="new")
        form_frame.grid_columnconfigure(1, weight=1)

        # --- Form Widgets ---
        # Channel
        ttk.Label(form_frame, text="Channel:").grid(row=0, column=0, sticky="w", pady=2)
        channel_names = [ch['name'].get() for ch in self.channels]
        event_channel = tk.StringVar(value=channel_names[0] if channel_names else "")
        channel_combo = ttk.Combobox(form_frame, textvariable=event_channel, values=channel_names, state="readonly")
        channel_combo.grid(row=0, column=1, sticky="ew")

        # Title
        ttk.Label(form_frame, text="Title:").grid(row=1, column=0, sticky="w", pady=2)
        event_title = tk.StringVar()
        title_entry = ttk.Entry(form_frame, textvariable=event_title)
        title_entry.grid(row=1, column=1, sticky="ew")
        ToolTip(title_entry, "The main title of the event.")

        # Short Description
        ttk.Label(form_frame, text="Short Desc:").grid(row=2, column=0, sticky="w", pady=2)
        event_short_desc = tk.StringVar()
        short_desc_entry = ttk.Entry(form_frame, textvariable=event_short_desc)
        short_desc_entry.grid(row=2, column=1, sticky="ew")
        ToolTip(short_desc_entry, "A brief, one-line summary of the event.")

        # Language
        ttk.Label(form_frame, text="Language:").grid(row=3, column=0, sticky="w", pady=2)
        event_language_display = tk.StringVar(value="English")
        lang_display_names = sorted(self.language_map.keys())
        lang_combo = ttk.Combobox(form_frame, textvariable=event_language_display, values=lang_display_names, state="readonly")
        lang_combo.grid(row=3, column=1, sticky="ew")

        # Start Time
        ttk.Label(form_frame, text="Start Time:").grid(row=3, column=0, sticky="w", pady=2)
        start_time_frame = ttk.Frame(form_frame)
        start_time_frame.grid(row=3, column=1, sticky="ew")
        now = datetime.now()
        event_date_var = tk.StringVar(value=now.strftime("%Y-%m-%d"))
        event_time_var = tk.StringVar(value=now.strftime("%H:%M"))
        date_entry = ttk.Entry(start_time_frame, textvariable=event_date_var, width=12)
        date_entry.pack(side=tk.LEFT)
        time_entry = ttk.Entry(start_time_frame, textvariable=event_time_var, width=8)
        time_entry.pack(side=tk.LEFT, padx=5)

        def set_time_to_now():
            """Sets the date and time variables to the current time."""
            now_time = datetime.now()
            event_date_var.set(now_time.strftime("%Y-%m-%d"))
            event_time_var.set(now_time.strftime("%H:%M"))

        now_button = ttk.Button(start_time_frame, text="Now", command=set_time_to_now, width=5)
        now_button.pack(side=tk.LEFT, padx=(0, 5))
        ToolTip(now_button, "Set the start time to the current date and time.")
        ToolTip(start_time_frame, "Start time in YYYY-MM-DD and HH:MM (24-hour) format.")

        # Re-grid Start Time and Duration
        form_frame.grid_slaves(row=3, column=0)[0].grid(row=4, column=0) # Start Time Label
        start_time_frame.grid(row=4, column=1) # Start Time Frame
        ttk.Label(form_frame, text="Duration:").grid(row=5, column=0, sticky="w", pady=2)
        duration_frame = ttk.Frame(form_frame)
        duration_frame.grid(row=5, column=1, sticky="ew")
        event_dur_h_var = tk.StringVar(value="0")
        event_dur_m_var = tk.StringVar(value="30")
        dur_h_spinbox = ttk.Spinbox(duration_frame, from_=0, to=23, textvariable=event_dur_h_var, width=5)
        dur_h_spinbox.pack(side=tk.LEFT)
        ttk.Label(duration_frame, text="h").pack(side=tk.LEFT, padx=(0, 5))
        dur_m_spinbox = ttk.Spinbox(duration_frame, from_=0, to=59, textvariable=event_dur_m_var, width=5)
        dur_m_spinbox.pack(side=tk.LEFT)
        ttk.Label(duration_frame, text="m").pack(side=tk.LEFT)

        # Extended Description
        ttk.Label(form_frame, text="Extended Desc:").grid(row=6, column=0, sticky="nw", pady=2)
        event_ext_desc_text = tk.Text(form_frame, height=5, width=40)
        event_ext_desc_text.grid(row=6, column=1, sticky="ew")
        ToolTip(event_ext_desc_text, "The full, detailed description of the event. Can be multiple lines.")

        # Content Nibbles
        ttk.Label(form_frame, text="Content Type:").grid(row=7, column=0, sticky="w", pady=2)
        content_frame = ttk.Frame(form_frame)
        content_frame.grid(row=7, column=1, sticky="ew")
        event_nibble1_var = tk.StringVar(value="15")
        event_nibble2_var = tk.StringVar(value="0")
        ttk.Label(content_frame, text="L1:").pack(side=tk.LEFT)
        nibble1_spinbox = ttk.Spinbox(content_frame, from_=0, to=15, textvariable=event_nibble1_var, width=5)
        nibble1_spinbox.pack(side=tk.LEFT)
        ttk.Label(content_frame, text="L2:").pack(side=tk.LEFT, padx=(5,0))
        nibble2_spinbox = ttk.Spinbox(content_frame, from_=0, to=15, textvariable=event_nibble2_var, width=5)
        nibble2_spinbox.pack(side=tk.LEFT)
        ToolTip(content_frame, "DVB Content Type Nibbles.\nL1 (Main): 1=Movie, 2=News, 4=Sport, 5=Children, 15=Undefined.\nL2 (Sub): Varies by L1. e.g., for Movie: 1=Thriller, 8=Comedy.")

        # Help button for nibbles
        nibble_help_btn = ttk.Button(content_frame, text="?", width=2, command=self.show_nibble_help)
        nibble_help_btn.pack(side=tk.LEFT, padx=(5,0))
        ToolTip(nibble_help_btn, "Show a detailed table of DVB content nibble values.")

        # Parental Rating
        ttk.Label(form_frame, text="Parental Rating:").grid(row=8, column=0, sticky="w", pady=2)
        rating_frame = ttk.Frame(form_frame)
        rating_frame.grid(row=8, column=1, sticky="ew")
        event_country_code_var = tk.StringVar(value="gbr") # This will hold the 3-letter code
        country_display_var = tk.StringVar() # This will hold the "CODE - Name" for display
        event_min_age_var = tk.StringVar(value="None")
        ttk.Label(rating_frame, text="Country:").pack(side=tk.LEFT)
        country_code_map = { # ISO 3166-1 alpha-3
            "afg": "Afghanistan", "ala": "Åland Islands", "alb": "Albania", "dza": "Algeria", "asm": "American Samoa",
            "and": "Andorra", "ago": "Angola", "aia": "Anguilla", "ata": "Antarctica", "atg": "Antigua and Barbuda",
            "arg": "Argentina", "arm": "Armenia", "abw": "Aruba", "aus": "Australia", "aut": "Austria", "aze": "Azerbaijan",
            "bhs": "Bahamas", "bhr": "Bahrain", "bgd": "Bangladesh", "brb": "Barbados", "blr": "Belarus", "bel": "Belgium",
            "blz": "Belize", "ben": "Benin", "bmu": "Bermuda", "btn": "Bhutan", "bol": "Bolivia", "bes": "Bonaire, Sint Eustatius and Saba",
            "bwa": "Botswana", "bvt": "Bouvet Island", "bra": "Brazil", "iot": "British Indian Ocean Territory", "brn": "Brunei Darussalam",
            "bgr": "Bulgaria", "bfa": "Burkina Faso", "bdi": "Burundi", "cpv": "Cabo Verde", "khm": "Cambodia", "cmr": "Cameroon",
            "can": "Canada", "cym": "Cayman Islands", "caf": "Central African Republic", "tcd": "Chad", "chl": "Chile", "chn": "China",
            "cxr": "Christmas Island", "cck": "Cocos (Keeling) Islands", "col": "Colombia", "com": "Comoros", "cog": "Congo",
            "cod": "Congo (DRC)", "cok": "Cook Islands", "cri": "Costa Rica", "civ": "Côte d'Ivoire", "hrv": "Croatia",
            "cub": "Cuba", "cuw": "Curaçao", "cyp": "Cyprus", "cze": "Czech Republic", "dnk": "Denmark", "dji": "Djibouti",
            "dma": "Dominica", "dom": "Dominican Republic", "ecu": "Ecuador", "egy": "Egypt", "slv": "El Salvador",
            "gnq": "Equatorial Guinea", "eri": "Eritrea", "est": "Estonia", "swz": "Eswatini", "eth": "Ethiopia",
            "flk": "Falkland Islands (Malvinas)", "fro": "Faroe Islands", "fji": "Fiji", "fin": "Finland", "fra": "France",
            "guf": "French Guiana", "pyf": "French Polynesia", "atf": "French Southern Territories", "gab": "Gabon",
            "gmb": "Gambia", "geo": "Georgia", "deu": "Germany", "gha": "Ghana", "gib": "Gibraltar", "grc": "Greece",
            "grl": "Greenland", "grd": "Grenada", "glp": "Guadeloupe", "gum": "Guam", "gtm": "Guatemala", "ggy": "Guernsey",
            "gin": "Guinea", "gnb": "Guinea-Bissau", "guy": "Guyana", "hti": "Haiti", "hmd": "Heard Island and McDonald Islands",
            "vat": "Holy See", "hnd": "Honduras", "hkg": "Hong Kong", "hun": "Hungary", "isl": "Iceland", "ind": "India",
            "idn": "Indonesia", "irn": "Iran", "irq": "Iraq", "irl": "Ireland", "imn": "Isle of Man", "isr": "Israel",
            "ita": "Italy", "jam": "Jamaica", "jpn": "Japan", "jey": "Jersey", "jor": "Jordan", "kaz": "Kazakhstan",
            "ken": "Kenya", "kir": "Kiribati", "prk": "Korea (North)", "kor": "Korea (South)", "kwt": "Kuwait",
            "kgz": "Kyrgyzstan", "lao": "Laos", "lva": "Latvia", "lbn": "Lebanon", "lso": "Lesotho", "lbr": "Liberia",
            "lby": "Libya", "lie": "Liechtenstein", "ltu": "Lithuania", "lux": "Luxembourg", "mac": "Macao", "mdg": "Madagascar",
            "mwi": "Malawi", "mys": "Malaysia", "mdv": "Maldives", "mli": "Mali", "mlt": "Malta", "mhl": "Marshall Islands",
            "mtq": "Martinique", "mrt": "Mauritania", "mus": "Mauritius", "myt": "Mayotte", "mex": "Mexico",
            "fsm": "Micronesia", "mda": "Moldova", "mco": "Monaco", "mng": "Mongolia", "mne": "Montenegro", "msr": "Montserrat",
            "mar": "Morocco", "moz": "Mozambique", "mmr": "Myanmar", "nam": "Namibia", "nru": "Nauru", "npl": "Nepal",
            "nld": "Netherlands", "ncl": "New Caledonia", "nzl": "New Zealand", "nic": "Nicaragua", "ner": "Niger",
            "nga": "Nigeria", "niu": "Niue", "nfk": "Norfolk Island", "mkd": "North Macedonia", "mnp": "Northern Mariana Islands",
            "nor": "Norway", "omn": "Oman", "pak": "Pakistan", "plw": "Palau", "pse": "Palestine, State of", "pan": "Panama",
            "png": "Papua New Guinea", "pry": "Paraguay", "per": "Peru", "phl": "Philippines", "pcn": "Pitcairn", "pol": "Poland",
            "prt": "Portugal", "pri": "Puerto Rico", "qat": "Qatar", "reu": "Réunion", "rou": "Romania", "rus": "Russian Federation",
            "rwa": "Rwanda", "blm": "Saint Barthélemy", "shn": "Saint Helena, Ascension and Tristan da Cunha",
            "kna": "Saint Kitts and Nevis", "lca": "Saint Lucia", "maf": "Saint Martin (French part)",
            "spm": "Saint Pierre and Miquelon", "vct": "Saint Vincent and the Grenadines", "wsm": "Samoa",
            "smr": "San Marino", "stp": "Sao Tome and Principe", "sau": "Saudi Arabia", "sen": "Senegal", "srb": "Serbia",
            "syc": "Seychelles", "sle": "Sierra Leone", "sgp": "Singapore", "sxm": "Sint Maarten (Dutch part)",
            "svk": "Slovakia", "svn": "Slovenia", "slb": "Solomon Islands", "som": "Somalia", "zaf": "South Africa",
            "sgs": "South Georgia and the South Sandwich Islands", "ssd": "South Sudan", "esp": "Spain", "lka": "Sri Lanka",
            "sdn": "Sudan", "sur": "Suriname", "sjm": "Svalbard and Jan Mayen", "swe": "Sweden", "che": "Switzerland",
            "syr": "Syrian Arab Republic", "twn": "Taiwan", "tjk": "Tajikistan", "tza": "Tanzania", "tha": "Thailand",
            "tls": "Timor-Leste", "tgo": "Togo", "tkl": "Tokelau", "ton": "Tonga", "tto": "Trinidad and Tobago",
            "tun": "Tunisia", "tur": "Turkey", "tkm": "Turkmenistan", "tca": "Turks and Caicos Islands", "tuv": "Tuvalu",
            "uga": "Uganda", "ukr": "Ukraine", "are": "United Arab Emirates", "gbr": "United Kingdom",
            "usa": "United States of America", "ury": "Uruguay", "uzb": "Uzbekistan", "vut": "Vanuatu",
            "ven": "Venezuela", "vnm": "Viet Nam", "vgb": "Virgin Islands (British)", "vir": "Virgin Islands (U.S.)",
            "wlf": "Wallis and Futuna", "esh": "Western Sahara", "yem": "Yemen", "zmb": "Zambia", "zwe": "Zimbabwe"
        }
        # Create a list of "CODE - Name" for display
        country_display_list = sorted([f"{code.upper()} - {name}" for code, name in country_code_map.items()])

        country_combo = ttk.Combobox(
            rating_frame, 
            textvariable=country_display_var, 
            values=country_display_list
        )

        def on_country_select(event):
            """Extracts the 3-letter code from the 'CODE - Name' display format."""
            selection = country_display_var.get()
            try:
                code = selection.split(" - ")[0].lower()
                event_country_code_var.set(code)
            except IndexError:
                # Handle cases where user types a code not in the list
                event_country_code_var.set(selection.lower())

        def on_country_var_change(*args):
            """Updates the combobox text when the variable is changed programmatically."""
            code = event_country_code_var.get().lower()
            name = country_code_map.get(code)
            if name:
                country_display_var.set(f"{code.upper()} - {name}")
            else:
                country_display_var.set(code.upper())

        country_combo.bind("<<ComboboxSelected>>", on_country_select)
        country_combo.bind("<FocusOut>", on_country_select) # Also update when user types and leaves
        event_country_code_var.trace_add("write", on_country_var_change)

        # The combobox is not set to readonly to allow users to enter
        # a different 3-letter ISO code if their country is not listed.
        country_combo.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(rating_frame, text="Min Age:").pack(side=tk.LEFT)
        age_combo = ttk.Combobox(rating_frame, textvariable=event_min_age_var, values=["None"] + [str(i) for i in range(4, 19)], state="readonly", width=20)
        age_combo.pack(side=tk.LEFT)
        ToolTip(country_combo, "Set the parental rating for the event (country and minimum age).\n'None' means no rating will be included.")

        # CA Mode
        event_ca_mode_var = tk.BooleanVar(value=False)
        ca_mode_check = ttk.Checkbutton(form_frame, text="Scrambled (CA Mode)", variable=event_ca_mode_var)
        ca_mode_check.grid(row=9, column=1, sticky="w", pady=2)
        ToolTip(ca_mode_check, "Set to true if this event is scrambled (requires a Conditional Access system).")        

        # Store form variables on the editor object for easier access
        editor.form_vars = {
            'channel': event_channel, 'title': event_title, 'short_desc': event_short_desc,
            'language_display': event_language_display, 'date': event_date_var, 'time': event_time_var,
            'dur_h': event_dur_h_var, 'dur_m': event_dur_m_var, 'ext_desc': event_ext_desc_text,
            'ca_mode': event_ca_mode_var, 'country_code': event_country_code_var, 'min_age': event_min_age_var,
            'nibble1': event_nibble1_var, 'nibble2': event_nibble2_var
        }

        # Bind double-click to load event for editing
        tree.bind("<Double-1>", lambda event: self.load_epg_event_for_edit(editor))

        # Add Event Button
        ttk.Button(form_frame, text="Add/Update Event", command=lambda: self.add_epg_event(
            editor, editor.form_vars['channel'].get(), editor.form_vars['title'].get(), editor.form_vars['short_desc'].get(),
            editor.form_vars['language_display'].get(), editor.form_vars['date'].get(), editor.form_vars['time'].get(),
            editor.form_vars['dur_h'].get(), editor.form_vars['dur_m'].get(), editor.form_vars['ext_desc'].get("1.0", tk.END),
            editor.form_vars['nibble1'].get(), editor.form_vars['nibble2'].get(), editor.form_vars['ca_mode'].get(),
            editor.form_vars['country_code'].get(), editor.form_vars['min_age'].get()
        )).grid(row=10, column=1, sticky="e", pady=(10, 0))
        
        # Clear Form Button
        ttk.Button(form_frame, text="Clear Form", command=lambda: self.clear_epg_form(
            editor
        )).grid(row=10, column=0, sticky="w", pady=(10, 0))

        # --- Main Action Buttons ---
        action_frame = ttk.Frame(main_frame)
        action_frame.grid(row=1, column=1, sticky="sew")
        ttk.Button(action_frame, text="Save and Use EPG", command=lambda: self.save_epg_and_close(editor)).pack(side=tk.RIGHT)
        ttk.Button(action_frame, text="Cancel", command=editor.destroy).pack(side=tk.RIGHT, padx=10)
        
        # Bind search entry to filter the tree
        search_var.trace_add("write", lambda *args: self.populate_epg_tree(tree, search_var.get()))

        self.populate_epg_tree(tree) # Initial population

    def show_nibble_help(self):
        """Displays a Toplevel window with a detailed table of DVB content nibbles."""
        help_win = tk.Toplevel(self)
        help_win.title("DVB Content Nibble Reference")
        help_win.geometry("600x500")
        help_win.transient(self)
        help_win.grab_set()

        main_frame = ttk.Frame(help_win, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_columnconfigure(1, weight=1)
        main_frame.grid_rowconfigure(1, weight=1)

        # --- Data ---
        l1_data = {
            0x0: "Reserved for future use",
            0x1: "Movie/Cinema",
            0x2: "News/Current Affairs",
            0x3: "Show/Entertainment",
            0x4: "Sport",
            0x5: "Children's/Youth Programs",
            0x6: "Music/Ballet/Dance",
            0x7: "Arts/Culture",
            0x8: "Social/Political Issues/Economics",
            0x9: "Education/Science/Factual Topics",
            0xA: "Leisure/Hobbies",
            0xB: "Special Characteristics",
            0xC: "Adult Programs",
            0xD: "User Defined",
            0xE: "User Defined",
            0xF: "User Defined"
        }

        l2_data = { 0x1: { 0x0: "Movie/Cinema (default)", 0x1: "Detective/Thriller", 0x2: "Adventure/Western", 0x3: "Sci-Fi/Fantasy", 0x4: "Comedy", 0x5: "Serious/Classical/Drama", 0x6: "Documentary", 0x7: "Various" }, 0x2: { 0x0: "News/Current Affairs (default)", 0x1: "News/Weather Report", 0x2: "News Magazine", 0x3: "Documentary/Reportage", 0x4: "Discussion/Interview/Debate", 0x5: "Various" }, 0x3: { 0x0: "Show/Entertainment (default)", 0x1: "Game Show/Quiz/Contest", 0x2: "Variety Show", 0x3: "Talk Show", 0x4: "Various" }, 0x4: { 0x0: "Sport (default)", 0x1: "Special Event (Olympics, World Cup)", 0x2: "Soccer/Football", 0x3: "Tennis/Squash", 0x4: "Team Sports (other)", 0x5: "Athletics", 0x6: "Motor Sport", 0x7: "Water Sport", 0x8: "Winter Sport", 0x9: "Horse Racing", 0xA: "Cycling", 0xB: "Various" }, 0x5: { 0x0: "Children's/Youth (default)", 0x1: "Pre-school", 0x2: "Entertainment (6-14 years)", 0x3: "Factual (6-14 years)", 0x4: "Young Teenagers", 0x5: "Teenagers", 0x6: "Various" }, 0x6: { 0x0: "Music/Ballet/Dance (default)", 0x1: "Rock/Pop", 0x2: "Serious Music (Classical)", 0x3: "Jazz", 0x4: "Musical/Opera", 0x5: "Folk/Traditional Music", 0x6: "Various" }, 0x7: { 0x0: "Arts/Culture (default)", 0x1: "Performing Arts", 0x2: "Fine Arts", 0x3: "Religion/Mythology/Folklore", 0x4: "Experimental Cinema/Video", 0x5: "Broadcasting/Press", 0x6: "New Media", 0x7: "Various/Feuilleton/Serial" }, 0x8: { 0x0: "Social/Political (default)", 0x1: "Magazines/Reports/Documentary", 0x2: "Discussion/Interview/Debate", 0x3: "Various" }, 0x9: { 0x0: "Education/Science (default)", 0x1: "Nature/Animals/Environment", 0x2: "Technology/Natural Sciences", 0x3: "Medicine/Health/Well Being", 0x4: "Foreign Countries/Expeditions", 0x5: "Various" }, 0xA: { 0x0: "Leisure/Hobbies (default)", 0x1: "Gardening", 0x2: "Cooking/Haute Cuisine", 0x3: "Travel/Tourism", 0x4: "Handicraft", 0x5: "Motoring", 0x6: "Fitness/Health", 0x7: "Various" }, 0xB: { 0x0: "Special Characteristics (default)", 0x1: "Adult Material/Pornography (deprecated)", 0x2: "Black and White", 0x3: "Unedited", 0x4: "Live Broadcast", 0x5: "Original Language", 0x6: "Explicit" }, 0xC: { 0x0: "Adult Programs/Pornography (default)" } }

        # --- Level 1 Tree ---
        ttk.Label(main_frame, text="Level 1 (Main Category)", style="Header.TLabel").grid(row=0, column=0, sticky='w')
        l1_tree = ttk.Treeview(main_frame, columns=("val", "desc"), show="headings", selectmode="browse")
        l1_tree.heading("val", text="Value")
        l1_tree.heading("desc", text="Description")
        l1_tree.column("val", width=50, anchor='center')
        l1_tree.grid(row=1, column=0, sticky='nsew', padx=(0, 5))

        for val, desc in l1_data.items():
            l1_tree.insert("", "end", values=(f"{val} (0x{val:X})", desc), iid=val)

        # --- Level 2 Tree ---
        ttk.Label(main_frame, text="Level 2 (Sub-Category)", style="Header.TLabel").grid(row=0, column=1, sticky='w')
        l2_tree = ttk.Treeview(main_frame, columns=("val", "desc"), show="headings")
        l2_tree.heading("val", text="Value")
        l2_tree.heading("desc", text="Description")
        l2_tree.column("val", width=50, anchor='center')
        l2_tree.grid(row=1, column=1, sticky='nsew', padx=(5, 0))

        def on_l1_select(event):
            # Clear L2 tree
            for item in l2_tree.get_children():
                l2_tree.delete(item)

            selected_item = l1_tree.focus()
            if not selected_item:
                return

            l1_val = int(selected_item)
            sub_cats = l2_data.get(l1_val)
            if sub_cats:
                for val, desc in sub_cats.items():
                    l2_tree.insert("", "end", values=(f"{val} (0x{val:X})", desc))
            else:
                l2_tree.insert("", "end", values=("", "No specific sub-categories defined"))

        l1_tree.bind("<<TreeviewSelect>>", on_l1_select)

        # --- Close Button ---
        ttk.Button(main_frame, text="Close", command=help_win.destroy).grid(row=2, column=0, columnspan=2, pady=(10,0))

        # Select first item to populate L2 initially
        l1_tree.focus(l1_tree.get_children()[1]) # Focus on "Movie/Drama"
        l1_tree.selection_set(l1_tree.get_children()[1])
    def clear_epg_form(self, editor):
        """Clears all fields in the EPG editor form and resets the selection."""
        editor.selected_event_index = None
        form = editor.form_vars

        # Reset string/boolean vars
        channel_names = [ch['name'].get() for ch in self.channels]
        form['channel'].set(channel_names[0] if channel_names else "")
        form['title'].set("")
        form['short_desc'].set("")
        form['language_display'].set("English")
        now = datetime.now()
        form['date'].set(now.strftime("%Y-%m-%d"))
        form['time'].set(now.strftime("%H:%M"))
        form['dur_h'].set("0")
        form['dur_m'].set("30")
        form['ca_mode'].set(False)
        form['nibble1'].set("15")
        form['nibble2'].set("0")
        form['country_code'].set("gbr")
        form['min_age'].set("None")

        # Clear text widget
        form['ext_desc'].delete("1.0", tk.END)

    def populate_epg_tree(self, tree, filter_text=""):
        """Clears and repopulates the EPG event treeview."""
        for item in tree.get_children():
            tree.delete(item)
        
        # Filter events based on the search text
        filtered_events = self.epg_events
        if filter_text:
            filtered_events = [e for e in self.epg_events if filter_text.lower() in e.get('title', '').lower()]

        # Sort events by start time
        sorted_events = sorted(filtered_events, key=lambda x: x['start'])
        for i, event in enumerate(sorted_events):
            tree.insert("", tk.END, iid=self.epg_events.index(event), values=(event['channel'], event['title'], event['start'].strftime("%Y-%m-%d %H:%M")))

    def add_epg_event(self, editor, channel, title, short_desc, lang_display, date_str, time_str, dur_h, dur_m, ext_desc, nibble1, nibble2, ca_mode, country_code, min_age):
        """Validates and adds or updates an event in the internal list."""
        if not all([channel, title, short_desc, date_str, time_str, dur_h, dur_m]):
            messagebox.showerror("Missing Info", "Please fill all fields.", parent=editor)
            return
        try:
            start_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            duration_minutes = int(dur_h) * 60 + int(dur_m)
            
            # Add validation for max duration (3 hours = 180 minutes)
            if duration_minutes > 180:
                messagebox.showerror("Invalid Duration", "Event duration cannot exceed 3 hours.", parent=editor)
                return
            end_time = start_time + timedelta(minutes=duration_minutes)
            nibble1_val = int(nibble1)
            nibble2_val = int(nibble2)
        except ValueError as e:
            messagebox.showerror("Invalid Format", f"Invalid date/time or duration format: {e}", parent=editor)
            return

        event_data = {
            "channel": channel,
            "title": title,
            "start": start_time,
            "language": self.language_map.get(lang_display, "eng"),
            "end": end_time,
            "short_desc": short_desc.strip(),
            "ext_desc": ext_desc.rstrip('\n'),
            "nibble1": nibble1_val,
            "nibble2": nibble2_val,
            "ca_mode": ca_mode,
            "country_code": country_code.strip().lower(),
            "min_age": min_age
        }

        if editor.selected_event_index is not None:
            # Update existing event
            self.epg_events[editor.selected_event_index] = event_data
        else:
            # Add new event
            self.epg_events.append(event_data)

        # Reset selection and repopulate tree
        editor.selected_event_index = None
        self.populate_epg_tree(editor.tree)

    def _load_epg_form_data(self, editor, event_data):
        """Helper to populate the form with data from an event dictionary."""
        form = editor.form_vars
        form['channel'].set(event_data['channel'])
        form['title'].set(event_data['title'])
        form['short_desc'].set(event_data.get('short_desc', ''))

        lang_code = event_data.get('language', 'eng')
        lang_display_name = next((name for name, code in self.language_map.items() if code == lang_code), "English")
        form['language_display'].set(lang_display_name)

        form['date'].set(event_data['start'].strftime("%Y-%m-%d"))
        form['time'].set(event_data['start'].strftime("%H:%M"))

        duration = event_data['end'] - event_data['start']
        total_minutes = duration.total_seconds() // 60
        hours, minutes = divmod(total_minutes, 60)
        form['dur_h'].set(str(int(hours)))
        form['dur_m'].set(str(int(minutes)))

        form['ext_desc'].delete("1.0", tk.END)
        form['ext_desc'].insert("1.0", event_data.get('ext_desc', ''))
        form['ca_mode'].set(event_data.get('ca_mode', False))
        form['country_code'].set(event_data.get('country_code', 'gbr'))
        form['min_age'].set(event_data.get('min_age', 'None'))
        form['nibble1'].set(str(event_data.get('nibble1', 15)))
        form['nibble2'].set(str(event_data.get('nibble2', 0)))

    def load_epg_event_for_edit(self, editor):
        """Loads the data of the selected event into the form fields."""
        selected_item = editor.tree.focus()
        if not selected_item:
            return

        # The IID of the tree item is its index in the original self.epg_events list.
        original_index = int(selected_item)
        editor.selected_event_index = original_index
        event = self.epg_events[original_index]
        self._load_epg_form_data(editor, event)

    def delete_epg_event(self, editor):
        """Deletes the selected event from the list."""
        selected_item = editor.tree.focus()
        if not selected_item:
            return
        
        # The IID of the tree item is its index in the original self.epg_events list.
        del self.epg_events[int(selected_item)]

        # Crucially, reset the selected index so we don't try to update a deleted item
        editor.selected_event_index = None
        
        self.populate_epg_tree(editor.tree)

    def duplicate_epg_event(self, editor):
        """Duplicates the selected event and populates the form with its data."""
        selected_item = editor.tree.focus()
        if not selected_item:
            messagebox.showwarning("No Selection", "Please select an event to duplicate.", parent=editor)
            return

        original_index = int(selected_item)
        original_event = self.epg_events[original_index]

        # Create a copy of the event data
        new_event = original_event.copy()

        # Set the new start time to the end time of the original event
        duration = original_event['end'] - original_event['start']
        new_event['start'] = original_event['end']
        new_event['end'] = new_event['start'] + duration

        # Load this new data into the form
        self._load_epg_form_data(editor, new_event)
        # IMPORTANT: Unset the selected index so "Add/Update" creates a new event
        editor.selected_event_index = None
    
    def save_epg_and_close(self, editor_window):
        """Generates the XMLTV file, updates the path, and closes the editor."""
        if not self.epg_events:
            self.eit_path.set("") # Clear path if no events
            editor_window.destroy()
            return

        # --- Gap Detection and Filling ---
        gaps_found, new_event_list = self._detect_and_fill_epg_gaps()

        if gaps_found:
            channels_with_gaps = sorted(list(set(g['channel'] for g in gaps_found)))
            gap_details = "\n".join([f"- {g['channel']} ({g['start'].strftime('%H:%M')} to {g['end'].strftime('%H:%M')})" for g in gaps_found[:5]])
            if len(gaps_found) > 5:
                gap_details += "\n... and more."

            warning_msg = (
                f"Warning: {len(gaps_found)} gap(s) detected in the EPG schedule for channel(s): {', '.join(channels_with_gaps)}.\n\n"
                f"Example gaps:\n{gap_details}\n\n"
                "These gaps will be automatically filled with a 'To Be Announced' event. Without this, your EPG may not display correctly on the receiver.\n\n"
                "Do you want to proceed?"
            )
            
            if messagebox.askyesno("EPG Gap Warning", warning_msg, parent=editor_window):
                self.epg_events = new_event_list # Replace original events with the gap-filled list
                self.populate_epg_tree(editor_window.tree) # Refresh the tree view to show fillers
                self.log_message(f"INFO: Filled {len(gaps_found)} EPG gap(s).\n")
            else:
                return # User chose not to proceed, so we return to the editor.

        xml_content = self._build_eit_xml()
        try:
            # Create a temporary file, close it so other processes can access it, then write to it.
            # This avoids file locking issues on Windows.
            tmp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.xml', encoding='utf-8')
            tmp_file_path = tmp_file.name
            tmp_file.close()
            with open(tmp_file_path, 'w', encoding='utf-8') as tmp_file:
                tmp_file.write(xml_content)

            self.eit_path.set(tmp_file_path)
            self.log_message(f"Generated temporary EPG file at: {self.eit_path.get()}\n")
            self.update_command_preview()
            editor_window.destroy()
        except Exception as e:
            messagebox.showerror("File Error", f"Could not write temporary EPG file: {e}", parent=editor_window)

    def _detect_and_fill_epg_gaps(self):
        """Detects time gaps between events on each channel and creates filler events."""
        if not self.epg_events:
            return [], []

        events_by_channel = {}
        for event in self.epg_events:
            ch_name = event['channel']
            events_by_channel.setdefault(ch_name, []).append(event)

        all_events_with_fillers = []
        gaps_found = []

        for ch_name, events in events_by_channel.items():
            sorted_events = sorted(events, key=lambda x: x['start'])
            
            # Add the first event
            if sorted_events:
                all_events_with_fillers.append(sorted_events[0])

            for i in range(len(sorted_events) - 1):
                current_event = sorted_events[i]
                next_event = sorted_events[i+1]

                # Check for a gap (more than 1 second difference)
                if next_event['start'] > current_event['end'] + timedelta(seconds=1):
                    gap_start = current_event['end']
                    gap_end = next_event['start']
                    gaps_found.append({'channel': ch_name, 'start': gap_start, 'end': gap_end})

                    filler_event = {
                        "channel": ch_name,
                        "title": "To Be Announced",
                        "start": gap_start,
                        "end": gap_end,
                        "language": "eng",
                        "short_desc": "Information not available.",
                        "ext_desc": "",
                        "nibble1": 15, "nibble2": 0, "ca_mode": False,
                        "country_code": "gbr", "min_age": "None"
                    }
                    all_events_with_fillers.append(filler_event)
                
                all_events_with_fillers.append(next_event)

        return gaps_found, all_events_with_fillers

    def _generate_event_xml(self, event, event_id, is_running):
        """Helper to generate the XML for a single event."""
        start_str = event['start'].strftime("%Y-%m-%d %H:%M:%S")
        total_seconds = int((event['end'] - event['start']).total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        ca_mode_str = "true" if event.get("ca_mode", False) else "false"
        duration_str = f"{hours:02}:{minutes:02}:{seconds:02}"
        running_status = "running" if is_running else "not-running"
        
        escaped_title = xml.sax.saxutils.escape(event.get("title", ""))
        escaped_short_desc = xml.sax.saxutils.escape(event.get("short_desc", ""))
        escaped_ext_desc = xml.sax.saxutils.escape(event.get("ext_desc", ""))
        nibble1 = event.get("nibble1", 15)
        language_code = event.get("language", "eng")
        nibble2 = event.get("nibble2", 0)
        country_code = event.get("country_code")
        min_age = event.get("min_age")

        xml_parts = [
            f'    <event event_id="{event_id}" start_time="{start_str}" duration="{duration_str}" running_status="{running_status}" CA_mode="{ca_mode_str}">\n'
            f'      <content_descriptor>\n'
            f'        <content content_nibble_level_1="{nibble1}" content_nibble_level_2="{nibble2}" user_byte="0x00"/>\n'
            f'      </content_descriptor>\n'
            f'      <short_event_descriptor language_code="{language_code}">\n'
            f'        <event_name>{escaped_title}</event_name>\n'
            f'        <text>{escaped_short_desc}</text>\n'
            f'      </short_event_descriptor>\n'
        ]

        # Add parental rating descriptor if age is specified
        if country_code and min_age and min_age != "None":
            try:
                # DVB rating = age - 3. 0x00 is undefined. 0x01-0x0F for ages 4-18.
                rating_val = int(min_age) - 3
                if 1 <= rating_val <= 15:
                    xml_parts.append(f'      <parental_rating_descriptor>\n')
                    xml_parts.append(f'        <country country_code="{country_code}" rating="0x{rating_val:02X}"/>\n')
                    xml_parts.append(f'      </parental_rating_descriptor>\n')
            except (ValueError, TypeError):
                pass # Ignore if min_age is not a valid integer
        # Add extended event descriptor if a description exists
        if escaped_ext_desc:
            xml_parts.append(
                f'      <extended_event_descriptor descriptor_number="0" last_descriptor_number="0" language_code="{language_code}">\n'
                f'        <text>{escaped_ext_desc}</text>\n'
                f'      </extended_event_descriptor>\n'
            )

        xml_parts.append('    </event>')
        return "".join(xml_parts)

    def generate_and_save_eit_xml(self, editor_window):
        """Generates the EIT XML and saves it to a temporary file."""
        # This method now contains the logic that was in save_epg_and_close
        # It is kept separate to allow for future expansion or direct calls.
        xml_content = self._build_eit_xml()
        try:
            # Create a temporary file to store the XML
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.xml', encoding='utf-8') as tmp_file:
                tmp_file.write(xml_content)
                self.eit_path.set(tmp_file.name)
            self.log_message(f"Generated temporary EPG file at: {self.eit_path.get()}\n")
            self.update_command_preview()
            editor_window.destroy()
        except Exception as e:
            messagebox.showerror("File Error", f"Could not write temporary EPG file: {e}", parent=editor_window)

    def _build_eit_xml(self):
        """Builds the TSDuck-compatible EIT XML string from self.epg_events."""
        xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<tsduck>']

        # Find channel PID mapping
        channel_pids = {ch['name'].get(): ch['pid'].get() for ch in self.channels}

        # Generate one EIT section per channel
        for ch_data in self.channels:
            ch_name = ch_data['name'].get()
            service_id_hex = ch_data['pid'].get()

            # Filter events for the current channel
            channel_events = sorted([e for e in self.epg_events if e['channel'] == ch_name], key=lambda x: x['start'])
            if not channel_events:
                continue # Skip channels with no events

            # Generate Present/Following EIT for this channel
            now = datetime.now()
            p_event = next((e for e in channel_events if e['start'] <= now < e['end']), None)

            # The new format seems to be a single "pf" (Present/Following) table per service.
            # We will populate it with all events for that service.
            xml_parts.append(f'  <EIT type="pf" version="0" actual="true" service_id="{service_id_hex}" transport_stream_id="0x0001" original_network_id="0x0001" last_table_id="0x4E">')

            # Use a simple counter for event_id, starting from a base for uniqueness.
            event_id_base = 10000
            for i, event in enumerate(channel_events):
                event_id = event_id_base + i
                is_running = (event == p_event)
                xml_parts.append(self._generate_event_xml(event, event_id, is_running))

            xml_parts.append('  </EIT>')

        xml_parts.append('</tsduck>')
        return '\n'.join(xml_parts)

if __name__ == "__main__":

    # Custom style for error entry
    from tkinter import TclError
    app = HackDvbGui()
    style = ttk.Style(app)
    style.map("Error.TEntry",
          fieldbackground=[("!disabled", "#ffcdd2")],
          foreground=[("!disabled", "#b71c1c")])
    app.mainloop()