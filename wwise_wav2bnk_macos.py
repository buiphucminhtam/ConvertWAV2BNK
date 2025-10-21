#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wwise Batch WAV → BNK Converter (CLI-only, macOS Edition)
Version: 2.0 — Native macOS Support + Auto Events + CLI Mode
Author: Game Engineer Leader Assistant
"""

import os, json, subprocess, datetime, threading, sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog

CONFIG_PATH = Path.home() / "Library/Application Support/WwiseBatchTool/config.json"


def discover_console(prefer_prefixs=("Wwise2025", "Wwise2024", "Wwise")):
    """Discover a Wwise console/binary. Prefer apps whose folder name starts with items in prefer_prefixs (in order).
    Tries to return a native executable under Contents/MacOS when possible, falling back to known wrapper scripts.
    """
    import glob
    base = "/Applications/Audiokinetic"
    # Look for preferred app folders first
    candidates = []
    for pfx in prefer_prefixs:
        paths = glob.glob(f"{base}/{pfx}*/Wwise.app")
        paths = sorted(paths, reverse=True)
        for p in paths:
            candidates.append(Path(p))

    # Fallback: any Wwise.app
    if not candidates:
        for p in glob.glob(f"{base}/Wwise*/Wwise.app"):
            candidates.append(Path(p))

    # For each candidate app, prefer a non-wine binary in Contents/MacOS
    for app in candidates:
        macos_dir = app / "Contents" / "MacOS"
        tools_dir = app / "Contents" / "Tools"
        if macos_dir.exists():
            # look for executable files
            for child in sorted(macos_dir.iterdir()):
                try:
                    if child.is_file() and os.access(child, os.X_OK):
                        # quick binary sniff: avoid files that clearly reference wine
                        try:
                            with child.open('rb') as fh:
                                chunk = fh.read(1024 * 64)
                                if b'winewrapper' in chunk or b'WwiseConsole.exe' in chunk or b'wineloader' in chunk:
                                    continue
                        except Exception:
                            pass
                        return str(child)
                except Exception:
                    # ignore per-child errors and continue
                    continue
        # fallback to tools/scripts
        if tools_dir.exists():
            # prefer fixed script then normal
            fixed = tools_dir / 'WwiseConsole_fixed.sh'
            normal = tools_dir / 'WwiseConsole.sh'
            if fixed.exists():
                return str(fixed)
            if normal.exists():
                return str(normal)

    return ""



# --------------------- LOGGER ---------------------
class Logger:
    def __init__(self, text_widget=None, output_dir=None):
        self.text = text_widget
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if output_dir:
            self.log_file = Path(output_dir) / f"WwiseBatchLog_{timestamp}.txt"
        else:
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
    def __init__(self, console, project, wav_dir, output_dir, platforms, logger, dry_run=False, force_wine=False):
        self.console = console
        self.project = project
        self.wav_dir = wav_dir
        self.output_dir = output_dir
        self.platforms = platforms
        self.logger = logger
        self.dry_run = dry_run
        self.force_wine = force_wine

    def generate_import_json(self):
        tmp_json = Path("/tmp/import_wwise.json")
        imports = []
        for root, _, files in os.walk(self.wav_dir):
            for f in files:
                if f.lower().endswith(".wav"):
                    full = os.path.join(root, f)
                    obj = Path(f).stem
                    rel_path = os.path.relpath(root, self.wav_dir)
                    if rel_path == ".":
                        object_path = f"\\Actor-Mixer Hierarchy\\Auto\\{obj}"
                    else:
                        object_path = f"\\Actor-Mixer Hierarchy\\Auto\\{rel_path.replace(os.sep, '\\')}\\{obj}"
                    imports.append({
                        "audioFile": full,
                        "objectPath": object_path
                    })
        self.imports = imports
        data = {"importOperation": "useExisting", "imports": imports}
        tmp_json.write_text(json.dumps(data, indent=2))
        self.logger.write(f"📁 Import JSON created: {tmp_json}")
        return str(tmp_json)

    def run_cli(self, args, desc):
        self.logger.write(f"▶️ {desc}")
        try:
            # Resolve which console to execute: prefer native MacOS binary over a shell wrapper that calls Wine
            console_to_run = self._resolve_console(self.console)
            # Log what we resolved (helps explain when the underlying binary delegates elsewhere)
            if console_to_run != self.console:
                self.logger.write(f"🔎 Resolved console: {console_to_run} (requested: {self.console})")
            else:
                self.logger.write(f"🔎 Using console: {console_to_run}")
            if console_to_run.endswith('.sh'):
                full_args = ["bash", console_to_run] + args
            else:
                full_args = [console_to_run] + args
            # If dry-run, do not execute external process; just log the command that would be run
            self.logger.write(f"Command: {' '.join(full_args)}")
            if self.dry_run:
                self.logger.write(f"(dry-run) Skipping execution of: {' '.join(full_args)}")
                self.logger.write(f"✅ Done: {desc} (dry-run)\n")
                return

            process = subprocess.Popen(
                full_args,
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
            self.logger.write(f"✅ Done: {desc} (Exit code: {process.returncode})\n")
        except Exception as e:
            self.logger.write(f"❌ Error running {desc}: {e}")

    def _resolve_console(self, path):
        """Return a path to an executable console. If the provided path is a shell wrapper that calls Wine
        try to find a native MacOS binary in the same Wwise.app bundle and prefer it.
        """
        try:
            p = Path(path)
            # if it's not a file, fallback to original
            if not p.exists():
                return path

            # if it's a .sh, inspect its contents for wine/Windows exe usage
            if p.suffix == '.sh':
                try:
                    text = p.read_text(errors='ignore')
                except Exception:
                    text = ''
                if 'WwiseConsole.exe' in text or 'wine' in text or 'winewrapper.exe' in text:
                    # try to locate the Wwise.app root and find native binary under Contents/MacOS
                    parts = p.parts
                    if 'Wwise.app' in parts:
                        idx = parts.index('Wwise.app')
                        wwise_app = Path(*parts[: idx + 1])
                        macos_dir = wwise_app / 'Contents' / 'MacOS'
                        if macos_dir.exists():
                            # pick the first executable in Contents/MacOS that looks like Wwise
                            for child in macos_dir.iterdir():
                                if child.is_file() and os.access(child, os.X_OK):
                                    return str(child)
                # otherwise return the shell script
                return path

            # if path is already a macOS binary, check whether it references wine internals (some Wwise binaries are wrappers)
            if p.exists() and os.access(p, os.X_OK):
                try:
                    # read a chunk of the binary and look for wine-related strings
                    with p.open('rb') as bf:
                        chunk = bf.read(1024 * 1024)  # read up to 1MB
                        if b'winewrapper' in chunk or b'WwiseConsole.exe' in chunk or b'\\\\Program Files\\Audiokinetic' in chunk:
                            # looks like a wrapper that delegates to Windows exe via wine; try to find a true native binary in the bundle
                            parts = p.parts
                            if 'Wwise.app' in parts:
                                idx = parts.index('Wwise.app')
                                wwise_app = Path(*parts[: idx + 1])
                                macos_dir = wwise_app / 'Contents' / 'MacOS'
                                if macos_dir.exists():
                                    for child in macos_dir.iterdir():
                                        if child.is_file() and os.access(child, os.X_OK):
                                            try:
                                                with child.open('rb') as cb:
                                                    cchunk = cb.read(1024 * 1024)
                                                    if b'winewrapper' not in cchunk and b'WwiseConsole.exe' not in cchunk:
                                                        return str(child)
                                            except Exception:
                                                continue
                            # otherwise fall through and return original path
                except Exception:
                    pass
                return path
        except Exception:
            pass
        return path

    def run(self):
        # Debug info
        try:
            self.logger.write(f"Debug: console={self.console}, dry_run={self.dry_run}")
        except Exception:
            print(f"Debug: console={self.console}, dry_run={self.dry_run}")

        # Validation
        if not os.path.exists(self.console):
            self.logger.write("❌ Invalid WwiseConsole.sh path.")
            return
        if not os.path.exists(self.project):
            self.logger.write("❌ Invalid project file.")
            return
        if not os.path.isdir(self.wav_dir):
            self.logger.write("❌ Invalid WAV folder.")
            return

        json_path = self.generate_import_json()

        # Safety: inspect the console/script to see if it delegates to Wine/Windows exe. If so, abort with clear message.
        try:
            p = Path(self.console)
            bad = False
            bad_source = None
            if p.exists():
                if p.suffix == '.sh':
                    try:
                        txt = p.read_text(errors='ignore')
                        if 'winewrapper' in txt or 'WwiseConsole.exe' in txt or 'wine' in txt:
                            bad = True
                            bad_source = str(p)
                    except Exception:
                        pass
                else:
                    # binary: read first MB and look for wine references
                    try:
                        with p.open('rb') as bf:
                            chunk = bf.read(1024*1024)
                            if b'winewrapper' in chunk or b'WwiseConsole.exe' in chunk or b'\\Program Files\\Audiokinetic' in chunk:
                                bad = True
                                bad_source = str(p)
                    except Exception:
                        pass
            if bad and not self.force_wine:
                msg = "❌ Detected that the selected Wwise console delegates to Wine/Windows exe (winewrapper).\n"
                if bad_source:
                    msg += f"Detected wine-reference in: {bad_source}\n"
                msg += "Please choose a native macOS WwiseConsole binary (Contents/MacOS) or install a native Wwise Authoring build. Aborting."
                self.logger.write(msg)
                return
        except Exception:
            pass

        # Import
        self.run_cli(
            [self.project, "tab-delimited-import", "-import-file", json_path],
            "Running Wwise Console import..."
        )

        # Create Events
        for imp in self.imports:
            obj_path = imp["objectPath"]
            event_name = f"Play_{Path(obj_path).name}"
            self.run_cli(
                [self.project, "create-new", "Event", "--name", event_name, "--parent", "\\Events\\Default Work Unit", "--action", "Play", "--target", obj_path],
                f"Creating Event {event_name}..."
            )

        # Generate SoundBanks
        for plat in self.platforms:
            args = [self.project, "generate-soundbank", "-platform", plat]
            if self.output_dir:
                args += ["-outdir", self.output_dir]
            self.run_cli(args, f"Generating SoundBank for {plat}...")

        self.logger.write("🎉 All tasks completed successfully.")


# --------------------- GUI APP ---------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Wwise Batch WAV → BNK Converter (Native macOS Edition)")
        self.geometry("960x640")

        self.console = tk.StringVar()
        self.wwise_app = tk.StringVar()
        self.project = tk.StringVar()
        self.wav_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.platforms = ["macOS", "Windows", "Android", "iOS"]

        self._load_config()
        self._build_ui()

    # ---------- CONFIG SAVE/LOAD ----------
    def _find_console(self):
        import glob
        # Try native binary first
        paths = glob.glob("/Applications/Audiokinetic/Wwise*/Wwise.app/Contents/MacOS/Wwise*")
        if paths:
            # Take the first one, assuming it's the console
            return paths[0]
        # Fallback to fixed.sh
        paths = glob.glob("/Applications/Audiokinetic/Wwise*/Wwise.app/Contents/Tools/WwiseConsole_fixed.sh")
        if paths:
            return paths[0]
        # Fallback to normal .sh
        paths = glob.glob("/Applications/Audiokinetic/Wwise*/Wwise.app/Contents/Tools/WwiseConsole.sh")
        if paths:
            return paths[0]
        return ""

    def _load_config(self):
        try:
            if CONFIG_PATH.exists():
                data = json.loads(CONFIG_PATH.read_text())
                self.console.set(data.get("console", ""))
                self.wwise_app.set(data.get("wwise_app", ""))
                self.project.set(data.get("project", ""))
                self.wav_dir.set(data.get("wav_dir", ""))
                self.output_dir.set(data.get("output_dir", ""))
            if not self.console.get():
                # if user configured a specific .app, resolve it first
                if self.wwise_app.get():
                    resolved = None
                    app_path = self.wwise_app.get()
                    if app_path.endswith('.app') and os.path.isdir(app_path):
                        macos_dir = Path(app_path) / 'Contents' / 'MacOS'
                        if macos_dir.exists():
                            for child in sorted(macos_dir.iterdir()):
                                if child.is_file() and os.access(child, os.X_OK):
                                    resolved = str(child)
                                    break
                    if resolved:
                        self.console.set(resolved)
                    else:
                        self.console.set(self._find_console())
                else:
                    self.console.set(self._find_console())
        except Exception as e:
            print("⚠️ Cannot load config:", e)

    def _save_config(self):
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "console": self.console.get(),
                "wwise_app": self.wwise_app.get(),
                "project": self.project.get(),
                "wav_dir": self.wav_dir.get(),
                "output_dir": self.output_dir.get()
            }
            CONFIG_PATH.write_text(json.dumps(data, indent=2))
        except Exception as e:
            print("⚠️ Cannot save config:", e)

    # ---------- UI ----------
    def _build_ui(self):
        main = ttk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        def row(label, var, browse):
            f = ttk.Frame(main)
            f.pack(fill=tk.X, pady=4)
            ttk.Label(f, text=label, width=22).pack(side=tk.LEFT)
            ttk.Entry(f, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
            ttk.Button(f, text="Browse…", command=browse).pack(side=tk.LEFT)

        row("Wwise.app (optional):", self.wwise_app, lambda: self._browse_app(self.wwise_app))
        row("WwiseConsole (fixed or native):", self.console, lambda: self._browse_file(self.console))
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

        ttk.Button(main, text="Run Conversion", command=self._run).pack(pady=8)

        log_label = ttk.Label(main, text="Logs:")
        log_label.pack(anchor="w")

        self.log = tk.Text(main, height=15, bg="#111", fg="#0f0", insertbackground="#0f0")
        self.log.pack(fill=tk.BOTH, expand=True, pady=6)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- HANDLERS ----------
    def _browse_file(self, var):
        f = filedialog.askopenfilename()
        if f:
            var.set(f)
            self._save_config()

    def _browse_app(self, var):
        # allow selecting a .app bundle; resolve to its Contents/MacOS executable if possible
        d = filedialog.askdirectory()
        if d:
            # accept paths that end with .app as Wwise.app
            if d.endswith('.app'):
                var.set(d)
                # resolve to a MacOS binary if possible and set console
                macos_dir = Path(d) / 'Contents' / 'MacOS'
                resolved = None
                if macos_dir.exists():
                    for child in sorted(macos_dir.iterdir()):
                        if child.is_file() and os.access(child, os.X_OK):
                            resolved = str(child)
                            break
                if resolved:
                    self.console.set(resolved)
            else:
                # if user picked a folder, still set as wwise_app for convenience
                var.set(d)
            self._save_config()

    def _browse_dir(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)
            self._save_config()

    def _run(self):
        plats = [self.platforms[i] for i in self.plat_list.curselection()] or ["macOS"]
        logger = Logger(self.log, self.output_dir.get())
        worker = Worker(
            self.console.get(),
            self.project.get(),
            self.wav_dir.get(),
            self.output_dir.get(),
            plats,
            logger
        )
        # Log resolved console and configured .app for clarity
        logger.write(f"🔧 Resolved console path: {worker.console}")
        logger.write(f"📦 Configured Wwise.app: {self.wwise_app.get()}")
        self._save_config()
        threading.Thread(target=worker.run, daemon=True).start()

    def _on_close(self):
        self._save_config()
        self.destroy()


# --------------------- ENTRY POINT ---------------------
if __name__ == "__main__":
    if len(sys.argv) > 1:
        # CLI mode: python script.py <project> <wav_dir> <output_dir> <platforms>
        if len(sys.argv) < 5:
            print("Usage: python wwise_wav2bnk_macos.py <project> <wav_dir> <output_dir> <platforms>")
            sys.exit(1)
        project = sys.argv[1]
        wav_dir = sys.argv[2]
        output_dir = sys.argv[3]
        platforms = sys.argv[4].split(',')
        dry_run = False
        # optional flag --dry-run or -n
        if '--dry-run' in sys.argv or '-n' in sys.argv:
            dry_run = True
        console = ""  # Need to find or assume
        import glob
        # discover console prefering Wwise2025
        # allow forcing a specific Wwise.app or console path via --wwise-app
        console = ""
        if '--wwise-app' in sys.argv:
            idx = sys.argv.index('--wwise-app')
            if idx + 1 < len(sys.argv):
                requested = sys.argv[idx + 1]
                # if a .app path provided, resolve to its Contents/MacOS native binary when possible
                if requested.endswith('.app') and os.path.isdir(requested):
                    macos_dir = Path(requested) / 'Contents' / 'MacOS'
                    if macos_dir.exists():
                        for child in sorted(macos_dir.iterdir()):
                            if child.is_file() and os.access(child, os.X_OK):
                                console = str(child)
                                break
                else:
                    # assume user provided exact binary/script path
                    console = requested
        if not console:
            console = discover_console()
        if not console:
            print("Cannot find WwiseConsole")
            sys.exit(1)

        # CLI debug
        print(f"CLI ARGV: {sys.argv}")
        print(f"Parsed: console={console}, project={project}, wav_dir={wav_dir}, output_dir={output_dir}, platforms={platforms}, dry_run={dry_run}")
        force_wine = False
        if '--force-wine' in sys.argv:
            force_wine = True
        logger = Logger(None, output_dir)
        worker = Worker(console, project, wav_dir, output_dir, platforms, logger, dry_run=dry_run, force_wine=force_wine)
        worker.run()
    else:
        App().mainloop()
