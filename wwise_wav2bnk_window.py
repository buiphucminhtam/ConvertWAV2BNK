#!/usr/bin/env python3
"""
Wwise Batch WAV→BNK Converter (Pro Edition)
Author: Game Engineer Leader Assistant

New Upgrades:
✅ Multi-platform build (Windows, Android, iOS, macOS)
✅ Mapping mode B (flat: ObjectRoot\\<FileName>)
✅ Auto-create Events with pattern: customizable (default Play_{name})
✅ CI/CD mode: log .txt + exit code
✅ Auto-naming SoundBank = input folder name (optional)
✅ Save/Load profile JSON for team reuse
"""

import os
import sys
import json
import threading
import queue
import subprocess
import tempfile
import time
import datetime
from pathlib import Path
import argparse
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from waapi import WaapiClient
except Exception:
    WaapiClient = None

DEFAULT_PLATFORMS = ["Windows", "Android", "iOS", "macOS"]
DEFAULT_LANGUAGE = "SFX"
DEFAULT_OBJECT_ROOT = r"\\Actor-Mixer Hierarchy\\Auto"
DEFAULT_EVENT_PATTERN = "Play_{name}"
APP_TITLE = "Wwise Batch WAV→BNK Converter (Pro Edition)"

# --- Logger ---
class Logger:
    def __init__(self, gui_append=None, log_file_path=None):
        self.gui_append = gui_append
        self._fh = open(log_file_path, "a", encoding="utf-8") if log_file_path else None
        self._lock = threading.Lock()

    def close(self):
        if self._fh:
            self._fh.close()

    def write(self, msg):
        ts = time.strftime('%H:%M:%S')
        line = f"[{ts}] {msg}"
        with self._lock:
            if self._fh:
                self._fh.write(line + "\n")
                self._fh.flush()
        if self.gui_append:
            self.gui_append(line)
        else:
            print(line)


def discover_windows_console():
    """Try to locate WwiseConsole.exe in common Program Files locations and return the newest match.
    Returns full path or None.
    """
    import glob
    candidates = []
    # Common installation roots
    roots = [r"C:\Program Files\Audiokinetic", r"C:\Program Files (x86)\Audiokinetic", r"C:\Program Files\Audiokinetic\Wwise*"]
    for root in roots:
        pattern = os.path.join(root, "**", "WwiseConsole.exe")
        for p in glob.glob(pattern, recursive=True):
            candidates.append(p)
    if not candidates:
        return None
    # prefer newest by mtime
    candidates = sorted(candidates, key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]

# --- Worker ---
class WwiseBatchWorker:
    def __init__(self, console, project, language, soundbank, object_root, wavs, platforms, output_dir, create_events, event_pattern, auto_bankname, ci_mode, logger):
        self.console = console
        self.project = project
        self.language = language
        self.soundbank = soundbank
        self.object_root = object_root
        self.wavs = wavs
        self.platforms = platforms
        self.output_dir = output_dir
        self.create_events = create_events
        self.event_pattern = event_pattern
        self.auto_bankname = auto_bankname
        self.ci_mode = ci_mode
        self.logger = logger
        self.cancel_flag = threading.Event()

    def run(self):
        try:
            if self.auto_bankname:
                self.soundbank = Path(self.wavs[0]).parent.name
                self.logger.write(f"Auto Bank Name set: {self.soundbank}")

            tmp_dir = tempfile.mkdtemp(prefix="wwise_batch_")
            import_path = os.path.join(tmp_dir, "import.json")
            with open(import_path, 'w', encoding='utf-8') as f:
                json.dump(self._build_import_json(), f, indent=4)
            self.logger.write(f"Import JSON created: {import_path}")

            rc = self._run([self.console, self.project, 'import', '-import-file', import_path])
            if rc != 0:
                self.logger.write("ERROR: import failed")
                return False

            if self.create_events:
                self._create_events()

            for plat in self.platforms:
                args = [self.console, self.project, 'generate-soundbank', '-platform', plat, '-soundbank', self.soundbank]
                if self.output_dir:
                    args += ['-outdir', self.output_dir]
                rc = self._run(args)
                if rc != 0:
                    self.logger.write(f"ERROR: generation failed for {plat}")
                    return False
                self.logger.write(f"✔ Built {plat}")

            self.logger.write("All done successfully.")
            return True
        except Exception as e:
            self.logger.write(f"Exception: {e}")
            return False
        finally:
            self.logger.close()

    def _build_import_json(self):
        files = [{"AudioFile": os.path.abspath(w), "ObjectPath": f"{self.object_root}\\{Path(w).stem}"} for w in self.wavs]
        return {"ImportOperation": {"ImportLocation": "Actor-Mixer Hierarchy", "ImportLanguage": self.language, "AudioFiles": files}}

    def _create_events(self):
        if WaapiClient is None:
            self.logger.write("WAAPI not available; skip event creation.")
            return
        try:
            with WaapiClient() as client:
                for w in self.wavs:
                    name = Path(w).stem
                    evt_name = self.event_pattern.replace('{name}', name)
                    obj_path = f"{self.object_root}\\{name}"
                    try:
                        client.call('ak.wwise.core.object.create', {'parent': 'Events', 'type': 'Event', 'name': evt_name, 'onNameConflict': 'merge'})
                        self.logger.write(f"Event created: {evt_name}")
                    except Exception as e:
                        self.logger.write(f"Event failed: {evt_name} -> {e}")
        except Exception as e:
            self.logger.write(f"WAAPI connection failed: {e}")

    def _run(self, cmd):
        # On Windows, hide console windows when running WwiseConsole
        creationflags = 0
        if sys.platform.startswith('win'):
            try:
                creationflags = subprocess.CREATE_NO_WINDOW
            except Exception:
                creationflags = 0
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=creationflags)
        for line in proc.stdout:
            self.logger.write(line.strip())
        return proc.wait()

# --- GUI ---
class GUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry('1024x720')
        self.console = tk.StringVar()
        self.project = tk.StringVar()
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.soundbank = tk.StringVar(value='AutoBank')
        self.object_root = tk.StringVar(value=DEFAULT_OBJECT_ROOT)
        self.language = tk.StringVar(value=DEFAULT_LANGUAGE)
        self.event_pattern = tk.StringVar(value=DEFAULT_EVENT_PATTERN)
        self.create_events = tk.BooleanVar(value=True)
        self.auto_bankname = tk.BooleanVar(value=True)
        self.ci_mode = tk.BooleanVar(value=False)
        self.wavs = []
        self._build_ui()

    def _build_ui(self):
        f = ttk.Frame(self); f.pack(fill='both', expand=True, padx=12, pady=12)
        def row(label, var, cmd=None, is_dir=False):
            r = ttk.Frame(f); r.pack(fill='x', pady=3)
            ttk.Label(r, text=label, width=22).pack(side='left')
            ttk.Entry(r, textvariable=var).pack(side='left', fill='x', expand=True, padx=6)
            if cmd:
                ttk.Button(r, text='Browse…', command=cmd).pack(side='left')
        row('WwiseConsole.exe:', self.console, self._browse_console)
        row('Project (.wproj):', self.project, self._browse_proj)
        row('Input Folder:', self.input_dir, self._browse_input, True)
        row('Output Folder:', self.output_dir, self._browse_output, True)

        o = ttk.LabelFrame(f, text='Options'); o.pack(fill='x', pady=6)
        ttk.Label(o, text='SoundBank:').pack(side='left'); ttk.Entry(o, textvariable=self.soundbank, width=20).pack(side='left', padx=6)
        ttk.Checkbutton(o, text='Auto BankName = Folder', variable=self.auto_bankname).pack(side='left', padx=6)
        ttk.Label(o, text='Lang:').pack(side='left'); ttk.Entry(o, textvariable=self.language, width=10).pack(side='left', padx=6)
        ttk.Label(o, text='Object Root:').pack(side='left'); ttk.Entry(o, textvariable=self.object_root, width=40).pack(side='left', padx=6)

        p = ttk.LabelFrame(f, text='Platforms'); p.pack(fill='x', pady=6)
        self.platforms = tk.Listbox(p, selectmode='extended', height=4)
        for pl in DEFAULT_PLATFORMS: self.platforms.insert('end', pl)
        self.platforms.selection_set(0, 'end'); self.platforms.pack(side='left', padx=6)

        e = ttk.Frame(f); e.pack(fill='x', pady=6)
        ttk.Label(e, text='Event Pattern:').pack(side='left'); ttk.Entry(e, textvariable=self.event_pattern, width=30).pack(side='left', padx=6)
        ttk.Checkbutton(e, text='Create Events', variable=self.create_events).pack(side='left', padx=12)
        ttk.Checkbutton(e, text='CI/CD Log', variable=self.ci_mode).pack(side='left', padx=12)
        ttk.Button(e, text='Save Profile', command=self._save_profile).pack(side='right', padx=6)
        ttk.Button(e, text='Load Profile', command=self._load_profile).pack(side='right')

        self.log = tk.Text(f, height=15); self.log.pack(fill='both', expand=True, pady=6)
        ttk.Button(f, text='Run', command=self._run).pack()

    def _browse_console(self):
        p = filedialog.askopenfilename(filetypes=[('Exe','*.exe')]);
        if p: self.console.set(p)
    def _browse_proj(self):
        p = filedialog.askopenfilename(filetypes=[('Wwise Project','*.wproj')]);
        if p: self.project.set(p)
    def _browse_input(self):
        p = filedialog.askdirectory();
        if p: self.input_dir.set(p)
    def _browse_output(self):
        p = filedialog.askdirectory();
        if p: self.output_dir.set(p)

    def _append_log(self, text):
        self.log.insert('end', text+'\n'); self.log.see('end')

    def _save_profile(self):
        d = {
            'console': self.console.get(), 'project': self.project.get(), 'input_dir': self.input_dir.get(), 'output_dir': self.output_dir.get(),
            'soundbank': self.soundbank.get(), 'object_root': self.object_root.get(), 'language': self.language.get(), 'event_pattern': self.event_pattern.get()
        }
        path = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('Profile','*.json')])
        if path:
            json.dump(d, open(path,'w'), indent=4); messagebox.showinfo('Saved', 'Profile saved.')

    def _load_profile(self):
        p = filedialog.askopenfilename(filetypes=[('Profile','*.json')])
        if not p: return
        try:
            d = json.load(open(p))
            for k,v in d.items():
                if hasattr(self, k): getattr(self,k).set(v)
            messagebox.showinfo('Loaded','Profile loaded.')
        except Exception as e:
            messagebox.showerror('Error',str(e))

    def _run(self):
        if not all(map(os.path.exists,[self.console.get(),self.project.get(),self.input_dir.get()])):
            messagebox.showerror('Error','Check paths'); return
        wavs=[os.path.join(r,f) for r,_,fs in os.walk(self.input_dir.get()) for f in fs if f.lower().endswith('.wav')]
        if not wavs: messagebox.showerror('No WAV','No files found'); return
        plats=[self.platforms.get(i) for i in self.platforms.curselection()]
        if not plats: messagebox.showerror('No Platforms','Select platforms'); return
        outdir=self.output_dir.get().strip() or None
        logpath=None
        if self.ci_mode.get():
            out=outdir or os.path.join(Path(self.project.get()).parent,'GeneratedSoundBanks')
            os.makedirs(out,exist_ok=True)
            logpath=os.path.join(out,f'WwiseBatchLog_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.txt')
        logger=Logger(self._append_log,logpath)
        w=WwiseBatchWorker(self.console.get(),self.project.get(),self.language.get(),self.soundbank.get(),self.object_root.get(),wavs,plats,outdir,self.create_events.get(),self.event_pattern.get(),self.auto_bankname.get(),self.ci_mode.get(),logger)
        threading.Thread(target=lambda:[w.run(),messagebox.showinfo('Done','Process finished')]).start()

# --- Entry ---
def main():
    if len(sys.argv)>1 and '--ci' in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument('--ci', action='store_true')
        parser.add_argument('--console')
        parser.add_argument('--project')
        parser.add_argument('--input')
        parser.add_argument('--output')
        parser.add_argument('--platforms', nargs='+', default=DEFAULT_PLATFORMS)
        parser.add_argument('--soundbank', default='AutoBank')
        parser.add_argument('--language', default=DEFAULT_LANGUAGE)
        parser.add_argument('--object-root', default=DEFAULT_OBJECT_ROOT)
        parser.add_argument('--event-pattern', default=DEFAULT_EVENT_PATTERN)
        parser.add_argument('--create-events', action='store_true')
        args = parser.parse_args()

        # Console autodiscovery on Windows if not provided
        console = args.console
        if not console and sys.platform.startswith('win'):
            console = discover_windows_console()

        if not console or not os.path.isfile(console):
            print('ERROR: Cannot find valid WwiseConsole.exe. Please provide --console or install Wwise.')
            sys.exit(2)

        wavs = [os.path.join(r, f) for r, _, fs in os.walk(args.input) for f in fs if f.lower().endswith('.wav')]
        if not wavs:
            print('ERROR: No WAV files found in input')
            sys.exit(3)

        logpath = os.path.join(args.output or Path(args.project).parent, 'WwiseBatchLog_CI.txt')
        logger = Logger(None, logpath)
        w = WwiseBatchWorker(console, args.project, args.language, args.soundbank, args.object_root, wavs, args.platforms, args.output, args.create_events, args.event_pattern, True, logger)
        ok = w.run()
        sys.exit(0 if ok else 1)
    else:
        GUI().mainloop()

if __name__=='__main__': main()
