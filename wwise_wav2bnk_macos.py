#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wwise Batch WAV → BNK Converter (CLI-only, macOS WineDirect Edition)
Version: 1.5 — Fully fixed for Wwise 2024.1.8 on macOS (Wine)
Author: Game Engineer Leader Assistant
"""

import os, json, subprocess, datetime, threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog

CONFIG_PATH = Path.home() / ".config/wwise_batch_cli/config.json"


# --------------------- LOGGER ---------------------
class Logger:
    def __init__(self, text_widget=None):
        self.text = text_widget
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = Path(f"WwiseBatchLog_{timestamp}.txt")

    def write(self, msg):
        line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
        print(line)
        if self.text:
            self.text.insert(tk.END, line + "\n")
            self.text.see(tk.END)
            self.text.update_idletasks()
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


# --------------------- WORKER ---------------------
class Worker:
    def __init__(self, console, project, wav_dir, output_dir, platforms, logger):
        self.console = console
        self.project = project
        self.wav_dir = wav_dir
        self.output_dir = output_dir
        self.platforms = platforms
        self.logger = logger

    def generate_import_json(self):
        tmp_json = Path("/tmp/import_wwise.json")
        imports = []
        for root, _, files in os.walk(self.wav_dir):
            for f in files:
                if f.lower().endswith(".wav"):
                    full = os.path.join(root, f)
                    obj = Path(f).stem
                    imports.append({
                        "audioFile": full,
                        "objectPath": f"\\Actor-Mixer Hierarchy\\Auto\\{obj}"
                    })
        data = {"importOperation": "useExisting", "imports": imports}
        tmp_json.write_text(json.dumps(data, indent=2))
        self.logger.write(f"📁 Import JSON created: {tmp_json}")
        return str(tmp_json)

    def build_args(self, operation, *extra):
   
        if "Wwise.app" in self.console and self.console.endswith(".sh"):
            root = Path(self.console).parents[3]
            found = list(root.glob("**/winewrapper.exe"))
            if not found:
                self.logger.write("❌ Cannot find winewrapper.exe in Wwise.app")
                return []
            winewrap = str(found[0])
            wwise_exe = "c:/Program Files/Audiokinetic/Wwise 2024.1.8.8898/Authoring/x64/Release/bin/WwiseConsole.exe"
            proj_win = "Z:" + self.project
            return [
                winewrap,
                "--enable-alt-loader", "macdrv", "--wait-children", "--run", "--",
                wwise_exe, proj_win, operation, *extra
            ]

        # Native
        return [self.console, self.project, operation, *extra]

    def run_cli(self, args, desc):
        self.logger.write(f"▶️ {desc}")
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            for line in iter(process.stdout.readline, ''):
                if line:
                    self.logger.write(line.strip())
            process.stdout.close()
            process.wait()
            self.logger.write(f"✅ Done: {desc}\n")
        except Exception as e:
            self.logger.write(f"❌ Error running {desc}: {e}")

    def run(self):
        if not os.path.exists(self.console):
            self.logger.write("❌ Invalid WwiseConsole path.")
            return
        if not os.path.exists(self.project):
            self.logger.write("❌ Invalid project file.")
            return
        if not os.path.isdir(self.wav_dir):
            self.logger.write("❌ Invalid WAV folder.")
            return

        json_path = self.generate_import_json()

        # Step 1: Import audio files
        args = self.build_args("tab-delimited-import", "-import-file", json_path)
        self.run_cli(args, "Running Wwise Console import...")

        # Step 2: Generate SoundBanks for selected platforms
        for plat in self.platforms:
            args = self.build_args("generate-soundbank", "-platform", plat)
            if self.output_dir:
                args += ["-outdir", self.output_dir]
            self.run_cli(args, f"Generating SoundBank for {plat}...")

        self.logger.write("🎉 All tasks completed successfully.")


# --------------------- GUI APP ---------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Wwise Batch WAV → BNK Converter (macOS WineDirect Edition)")
        self.geometry("960x640")

        self.console = tk.StringVar()
        self.project = tk.StringVar()
        self.wav_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.platforms = ["macOS", "Windows", "Android", "iOS"]

        self._load_config()
        self._build_ui()

    def _load_config(self):
        try:
            if CONFIG_PATH.exists():
                data = json.loads(CONFIG_PATH.read_text())
                self.console.set(data.get("console", ""))
                self.project.set(data.get("project", ""))
                self.wav_dir.set(data.get("wav_dir", ""))
                self.output_dir.set(data.get("output_dir", ""))
        except Exception as e:
            print("⚠️ Cannot load config:", e)

    def _save_config(self):
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "console": self.console.get(),
                "project": self.project.get(),
                "wav_dir": self.wav_dir.get(),
                "output_dir": self.output_dir.get()
            }
            CONFIG_PATH.write_text(json.dumps(data, indent=2))
        except Exception as e:
            print("⚠️ Cannot save config:", e)

    def _build_ui(self):
        main = ttk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        def row(label, var, browse):
            f = ttk.Frame(main)
            f.pack(fill=tk.X, pady=4)
            ttk.Label(f, text=label, width=22).pack(side=tk.LEFT)
            ttk.Entry(f, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
            ttk.Button(f, text="Browse…", command=browse).pack(side=tk.LEFT)

        row("WwiseConsole.sh:", self.console, lambda: self._browse_file(self.console))
        row("Project (.wproj):", self.project, lambda: self._browse_file(self.project))
        row("WAV Folder:", self.wav_dir, lambda: self._browse_dir(self.wav_dir))
        row("Output Folder:", self.output_dir, lambda: self._browse_dir(self.output_dir))

        plat_frame = ttk.LabelFrame(main, text="Target Platforms")
        plat_frame.pack(fill=tk.X, pady=8)
        self.plat_list = tk.Listbox(plat_frame, selectmode=tk.MULTIPLE, height=4)
        for p in self.platforms:
            self.plat_list.insert(tk.END, p)
        self.plat_list.selection_set(0)
        self.plat_list.pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)

        ttk.Button(main, text="Run", command=self._run).pack(pady=8)

        log_label = ttk.Label(main, text="Logs:")
        log_label.pack(anchor="w")

        self.log = tk.Text(main, height=15, bg="#111", fg="#0f0", insertbackground="#0f0")
        self.log.pack(fill=tk.BOTH, expand=True, pady=6)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _browse_file(self, var):
        f = filedialog.askopenfilename()
        if f:
            var.set(f)
            self._save_config()

    def _browse_dir(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)
            self._save_config()

    def _run(self):
        plats = [self.platforms[i] for i in self.plat_list.curselection()] or ["macOS"]
        logger = Logger(self.log)
        worker = Worker(
            self.console.get(),
            self.project.get(),
            self.wav_dir.get(),
            self.output_dir.get(),
            plats,
            logger
        )
        self._save_config()
        threading.Thread(target=worker.run, daemon=True).start()

    def _on_close(self):
        self._save_config()
        self.destroy()


# --------------------- ENTRY POINT ---------------------
if __name__ == "__main__":
    App().mainloop()
