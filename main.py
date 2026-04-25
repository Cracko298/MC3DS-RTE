from __future__ import annotations

import os
import shutil
import struct
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

def joaat32(data: bytes) -> int:
    h = 0
    for b in data:
        h = (h + b) & 0xFFFFFFFF
        h = (h + ((h << 10) & 0xFFFFFFFF)) & 0xFFFFFFFF
        h ^= (h >> 6)

    h = (h + ((h << 3) & 0xFFFFFFFF)) & 0xFFFFFFFF
    h ^= (h >> 11)
    h = (h + ((h << 15) & 0xFFFFFFFF)) & 0xFFFFFFFF

    return h

def normalize_resource_path(path: str) -> str:
    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]

    lower = path.lower()
    marker = "/client/"
    if marker in lower:
        index = lower.rfind(marker)
        path = path[index + len(marker):]

    if lower.startswith("client/"):
        path = path[7:]

    return path.lower()

def resource_hash(path: str) -> int:
    normalized = normalize_resource_path(path)
    return joaat32(normalized.encode("utf-8"))

def read_resindex(path: Path) -> list[int]:
    data = path.read_bytes()
    if len(data) < 4:
        raise ValueError("resindex.idx is too small to contain a count header.")

    count = struct.unpack_from("<I", data, 0)[0]
    expected_size = 4 + count * 4
    if len(data) != expected_size:
        raise ValueError(
            "Invalid resindex.idx size.\n\n"
            f"Header count: {count}\n"
            f"Expected size: {expected_size} bytes\n"
            f"Actual size:   {len(data)} bytes"
        )

    hashes = list(struct.unpack_from(f"<{count}I", data, 4))
    if hashes != sorted(hashes):
        raise ValueError(
            "The hash list is not sorted.\n\n"
            "This tool expects a normal MC3DS resindex.idx where all hashes "
            "are sorted from lowest to highest."
        )

    return hashes

def write_resindex(path: Path, hashes: list[int]) -> None:
    hashes = sorted(set(hashes))
    out = bytearray()
    out += struct.pack("<I", len(hashes))
    for h in hashes:
        out += struct.pack("<I", h)

    path.write_bytes(out)

def texture_list_entry(path: str) -> str:
    normalized = normalize_resource_path(path)
    p = Path(normalized)
    if p.suffix.lower() in {".3dst", ".png", ".tga"}:
        normalized = str(p.with_suffix("")).replace("\\", "/")

    return normalized.lower()

def read_textures_list(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"textures.list does not exist:\n{path}")

    entries: list[str] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip().replace("\\", "/")
        if line:
            entries.append(texture_list_entry(line))

    return entries

def write_textures_list(path: Path, entries: list[str]) -> None:
    unique_entries = list(dict.fromkeys(texture_list_entry(entry) for entry in entries if entry.strip()))
    path.write_text("\n".join(unique_entries) + ("\n" if unique_entries else ""), encoding="utf-8")

def make_backup(path: Path) -> Path:
    backup = path.with_suffix(path.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(path, backup)

    return backup

def build_aliases(path: str, png_alias: bool = True, tga_alias: bool = False) -> list[str]:
    normalized = normalize_resource_path(path)
    aliases = [normalized]
    p = Path(normalized)
    suffix = p.suffix.lower()
    if suffix == ".3dst":
        if png_alias:
            aliases.append(str(p.with_suffix(".png")).replace("\\", "/").lower())

        if tga_alias:
            aliases.append(str(p.with_suffix(".tga")).replace("\\", "/").lower())

    return list(dict.fromkeys(aliases))

def try_path_relative_to_client(file_path: Path) -> str:
    parts = file_path.parts
    lower_parts = [p.lower() for p in parts]
    if "client" in lower_parts:
        index = lower_parts.index("client")
        rel_parts = parts[index + 1:]
        return "/".join(rel_parts).replace("\\", "/")

    return str(file_path).replace("\\", "/")

class ResIndexGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title("MC3DS ResIndex Texture Index Tool")
        self.geometry("980x680")
        self.minsize(900, 600)

        self.index_path_var = tk.StringVar()
        self.texture_list_path_var = tk.StringVar()
        self.path_entry_var = tk.StringVar()
        self.status_var = tk.StringVar(value="No index loaded.")

        self.png_alias_var = tk.BooleanVar(value=True)
        self.tga_alias_var = tk.BooleanVar(value=False)
        self.update_texture_list_var = tk.BooleanVar(value=True)
        self.backup_var = tk.BooleanVar(value=True)

        self.paths: list[str] = []

        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        title = ttk.Label(
            self,
            text="MC3DS Texture Index + textures.list Patcher",
            font=("Segoe UI", 15, "bold"),
        )
        title.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))

        subtitle = ttk.Label(
            self,
            text="Adds hashed paths to client/resindex.idx and plain entries to textures.list so new textures can be discovered by the game.",
        )
        subtitle.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))

        self._build_index_selector()
        self._build_main_area()
        self._build_action_bar()
        self._build_log_area()
        self._build_status_bar()

    def _build_index_selector(self) -> None:
        frame = ttk.LabelFrame(self, text="Index / Texture List Files")
        frame.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="resindex.idx:").grid(row=0, column=0, padx=8, pady=6, sticky="w")

        entry = ttk.Entry(frame, textvariable=self.index_path_var)
        entry.grid(row=0, column=1, padx=8, pady=6, sticky="ew")

        ttk.Button(frame, text="Browse...", command=self.browse_index).grid(
            row=0, column=2, padx=8, pady=6
        )

        ttk.Button(frame, text="Load Info", command=self.load_info).grid(
            row=0, column=3, padx=8, pady=6
        )

        ttk.Label(frame, text="textures.list:").grid(row=1, column=0, padx=8, pady=6, sticky="w")

        texture_entry = ttk.Entry(frame, textvariable=self.texture_list_path_var)
        texture_entry.grid(row=1, column=1, padx=8, pady=6, sticky="ew")

        ttk.Button(frame, text="Browse...", command=self.browse_texture_list).grid(
            row=1, column=2, padx=8, pady=6
        )

        ttk.Button(frame, text="Load List Info", command=self.load_texture_list_info).grid(
            row=1, column=3, padx=8, pady=6
        )

    def _build_main_area(self) -> None:
        main = ttk.Frame(self)
        main.grid(row=3, column=0, sticky="nsew", padx=12, pady=6)
        main.columnconfigure(0, weight=2)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        path_frame = ttk.LabelFrame(main, text="Texture Paths To Add / Check / Remove")
        path_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        path_frame.columnconfigure(0, weight=1)
        path_frame.rowconfigure(2, weight=1)

        help_text = (
            "Use client-relative paths like: textures/gui/custom_button.3dst\n"
            "The tool strips leading client/ automatically."
        )
        ttk.Label(path_frame, text=help_text).grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(8, 4))

        path_entry = ttk.Entry(path_frame, textvariable=self.path_entry_var)
        path_entry.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        path_entry.bind("<Return>", lambda _event: self.add_path_from_entry())

        ttk.Button(path_frame, text="Add Path", command=self.add_path_from_entry).grid(
            row=1, column=1, padx=4, pady=4
        )

        ttk.Button(path_frame, text="Select .3DST Files", command=self.browse_texture_files).grid(
            row=1, column=2, padx=4, pady=4
        )

        ttk.Button(path_frame, text="Scan Folder", command=self.scan_folder).grid(
            row=1, column=3, padx=8, pady=4
        )

        self.path_list = tk.Listbox(path_frame, selectmode=tk.EXTENDED)
        self.path_list.grid(row=2, column=0, columnspan=4, sticky="nsew", padx=8, pady=8)

        path_buttons = ttk.Frame(path_frame)
        path_buttons.grid(row=3, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 8))
        path_buttons.columnconfigure(3, weight=1)

        ttk.Button(path_buttons, text="Remove Selected", command=self.remove_selected_paths).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(path_buttons, text="Clear List", command=self.clear_paths).grid(
            row=0, column=1, padx=6
        )
        ttk.Button(path_buttons, text="Paste Multi-Line Paths", command=self.paste_multiline_paths).grid(
            row=0, column=2, padx=6
        )

        options = ttk.LabelFrame(main, text="Options")
        options.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        options.columnconfigure(0, weight=1)

        ttk.Checkbutton(
            options,
            text="Add .png alias for .3dst textures",
            variable=self.png_alias_var,
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))

        ttk.Checkbutton(
            options,
            text="Also add .tga alias",
            variable=self.tga_alias_var,
        ).grid(row=1, column=0, sticky="w", padx=10, pady=4)

        ttk.Checkbutton(
            options,
            text="Also update textures.list entries",
            variable=self.update_texture_list_var,
        ).grid(row=2, column=0, sticky="w", padx=10, pady=4)

        ttk.Checkbutton(
            options,
            text="Create .bak backup before writing",
            variable=self.backup_var,
        ).grid(row=3, column=0, sticky="w", padx=10, pady=4)

        ttk.Separator(options).grid(row=4, column=0, sticky="ew", padx=10, pady=10)

        info = (
            "Recommended for textures:\n\n"
            "textures/custom/my_texture.3dst\n\n"
            "This will add hashes for:\n"
            "textures/custom/my_texture.3dst\n"
            "textures/custom/my_texture.png\n\n"
            "resindex.idx stores hashes. textures.list stores plain "
            "texture names without .3dst/.png/.tga."
        )

        ttk.Label(options, text=info, wraplength=280, justify="left").grid(
            row=5, column=0, sticky="nw", padx=10, pady=4
        )

    def _build_action_bar(self) -> None:
        frame = ttk.LabelFrame(self, text="Actions")
        frame.grid(row=4, column=0, sticky="ew", padx=12, pady=6)

        ttk.Button(frame, text="Check Paths", command=self.check_paths).grid(
            row=0, column=0, padx=8, pady=8
        )

        ttk.Button(frame, text="Add Paths To Index + List", command=self.add_paths_to_index).grid(
            row=0, column=1, padx=8, pady=8
        )

        ttk.Button(frame, text="Remove Paths From Index", command=self.remove_paths_from_index).grid(
            row=0, column=2, padx=8, pady=8
        )

        ttk.Button(frame, text="Dump Hashes To TXT", command=self.dump_hashes).grid(
            row=0, column=3, padx=8, pady=8
        )

        ttk.Button(frame, text="Validate Index", command=self.validate_index).grid(
            row=0, column=4, padx=8, pady=8
        )

        ttk.Button(frame, text="Validate textures.list", command=self.validate_texture_list).grid(
            row=0, column=5, padx=8, pady=8
        )

    def _build_log_area(self) -> None:
        frame = ttk.LabelFrame(self, text="Log")
        frame.grid(row=5, column=0, sticky="nsew", padx=12, pady=6)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)

        self.log_box = tk.Text(frame, height=10, wrap="none")
        self.log_box.grid(row=0, column=0, sticky="nsew")

        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.log_box.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.log_box.configure(yscrollcommand=yscroll.set)

        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.log_box.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        self.log_box.configure(xscrollcommand=xscroll.set)

    def _build_status_bar(self) -> None:
        status = ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w")
        status.grid(row=6, column=0, sticky="ew")

    def log(self, text: str = "") -> None:
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def get_index_path(self) -> Path:
        path = Path(self.index_path_var.get().strip())
        if not path.exists():
            raise FileNotFoundError(f"Index file does not exist:\n{path}")

        return path

    def get_texture_list_path(self, required: bool = True) -> Path | None:
        raw = self.texture_list_path_var.get().strip()
        if not raw:
            if required:
                raise FileNotFoundError(
                    "No textures.list selected. Select it first, or turn off the "
                    "'Also update textures.list entries' option."
                )
            return None

        path = Path(raw)
        if required and not path.exists():
            raise FileNotFoundError(f"textures.list does not exist:\n{path}")

        return path

    def get_paths(self) -> list[str]:
        return list(self.paths)

    def refresh_path_list(self) -> None:
        self.path_list.delete(0, "end")
        for p in self.paths:
            self.path_list.insert("end", p)

    def add_path(self, path: str) -> None:
        normalized = normalize_resource_path(path)
        if not normalized:
            return

        if normalized not in self.paths:
            self.paths.append(normalized)
            self.log(f"[path] Added: {normalized}")

        self.refresh_path_list()

    def browse_index(self) -> None:
        filename = filedialog.askopenfilename(
            title="Select client/resindex.idx",
            filetypes=[
                ("resindex.idx", "resindex.idx"),
                ("IDX files", "*.idx"),
                ("All files", "*.*"),
            ],
        )

        if filename:
            self.index_path_var.set(filename)
            self.try_autofill_texture_list(Path(filename))
            self.load_info()

    def browse_texture_list(self) -> None:
        filename = filedialog.askopenfilename(
            title="Select client/textures.list",
            filetypes=[
                ("textures.list", "textures.list"),
                ("List files", "*.list"),
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ],
        )

        if filename:
            self.texture_list_path_var.set(filename)
            self.load_texture_list_info()

    def try_autofill_texture_list(self, index_path: Path) -> None:
        if self.texture_list_path_var.get().strip():
            return

        candidates = [
            index_path.with_name("textures.list"),
            index_path.parent.parent / "textures.list",
        ]
        for candidate in candidates:
            if candidate.exists():
                self.texture_list_path_var.set(str(candidate))
                self.log(f"[info] Auto-selected textures.list: {candidate}")
                return

    def load_texture_list_info(self) -> None:
        try:
            texture_list_path = self.get_texture_list_path(required=True)
            assert texture_list_path is not None
            entries = read_textures_list(texture_list_path)
            size = texture_list_path.stat().st_size
            duplicates = len(entries) - len(set(entries))
            self.log()
            self.log("[info] Loaded textures.list")
            self.log(f"       Path:       {texture_list_path}")
            self.log(f"       Entries:    {len(entries)}")
            self.log(f"       Duplicates: {duplicates}")
            self.log(f"       Size:       {size} bytes")
            self.set_status(f"Loaded {len(entries)} entries from textures.list")

        except Exception as e:
            messagebox.showerror("textures.list Load Error", str(e))
            self.set_status("Failed to load textures.list.")

    def load_info(self) -> None:
        try:
            index_path = self.get_index_path()
            hashes = read_resindex(index_path)
            size = index_path.stat().st_size
            self.log()
            self.log("[info] Loaded index")
            self.log(f"       Path:    {index_path}")
            self.log(f"       Entries: {len(hashes)}")
            self.log(f"       Size:    {size} bytes")
            if hashes:
                self.log(f"       First:   0x{hashes[0]:08X}")
                self.log(f"       Last:    0x{hashes[-1]:08X}")

            self.set_status(f"Loaded {len(hashes)} entries from {index_path.name}")

        except Exception as e:
            messagebox.showerror("Load Error", str(e))
            self.set_status("Failed to load index.")

    def add_path_from_entry(self) -> None:
        raw = self.path_entry_var.get().strip()
        if not raw:
            return

        self.add_path(raw)
        self.path_entry_var.set("")

    def browse_texture_files(self) -> None:
        filenames = filedialog.askopenfilenames(
            title="Select texture files",
            filetypes=[
                ("MC3DS Texture Files", "*.3dst"),
                ("Image Files", "*.png *.tga"),
                ("All files", "*.*"),
            ],
        )

        for filename in filenames:
            rel = try_path_relative_to_client(Path(filename))
            self.add_path(rel)

    def scan_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select folder to scan for textures")
        if not folder:
            return

        folder_path = Path(folder)
        extensions = {".3dst", ".png", ".tga"}
        count = 0
        for file in folder_path.rglob("*"):
            if file.is_file() and file.suffix.lower() in extensions:
                rel = try_path_relative_to_client(file)
                self.add_path(rel)
                count += 1

        self.log(f"[scan] Found {count} texture-like files in: {folder_path}")
        self.set_status(f"Scanned folder. Found {count} files.")

    def remove_selected_paths(self) -> None:
        selected = list(self.path_list.curselection())
        if not selected:
            return

        for index in reversed(selected):
            removed = self.paths.pop(index)
            self.log(f"[path] Removed from list: {removed}")

        self.refresh_path_list()

    def clear_paths(self) -> None:
        self.paths.clear()
        self.refresh_path_list()
        self.log("[path] Cleared path list.")

    def paste_multiline_paths(self) -> None:
        try:
            data = self.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("Clipboard Empty", "No text found in clipboard.")
            return

        added = 0
        for line in data.splitlines():
            line = line.strip()
            if line:
                self.add_path(line)
                added += 1

        self.log(f"[paste] Added {added} path(s) from clipboard.")

    def build_texture_list_entries_for_paths(self, paths: list[str]) -> list[str]:
        entries: list[str] = []
        for raw_path in paths:
            entries.append(texture_list_entry(raw_path))
        return list(dict.fromkeys(entries))

    def add_paths_to_texture_list_file(self, paths: list[str]) -> tuple[int, int, int]:
        texture_list_path = self.get_texture_list_path(required=True)
        assert texture_list_path is not None

        entries = read_textures_list(texture_list_path)
        entry_set = set(entries)
        if self.backup_var.get():
            backup = make_backup(texture_list_path)
            self.log(f"[backup] {backup}")

        added = 0
        existed = 0
        for entry in self.build_texture_list_entries_for_paths(paths):
            if entry in entry_set:
                self.log(f"[list exists] {entry}")
                existed += 1
            else:
                entries.append(entry)
                entry_set.add(entry)
                self.log(f"[list add]    {entry}")
                added += 1

        write_textures_list(texture_list_path, entries)
        return added, existed, len(entries)

    def remove_paths_from_texture_list_file(self, paths: list[str]) -> tuple[int, int, int]:
        texture_list_path = self.get_texture_list_path(required=True)
        assert texture_list_path is not None

        entries = read_textures_list(texture_list_path)
        existing_set = set(entries)
        remove_set = set(self.build_texture_list_entries_for_paths(paths))
        if self.backup_var.get():
            backup = make_backup(texture_list_path)
            self.log(f"[backup] {backup}")

        removed = 0
        kept_entries: list[str] = []
        for entry in entries:
            if entry in remove_set:
                self.log(f"[list remove] {entry}")
                removed += 1
            else:
                kept_entries.append(entry)

        missing = len(remove_set - existing_set)
        for entry in sorted(remove_set - existing_set):
            self.log(f"[list missing] {entry}")

        write_textures_list(texture_list_path, kept_entries)
        return removed, missing, len(kept_entries)

    def validate_index(self) -> None:
        try:
            index_path = self.get_index_path()
            hashes = read_resindex(index_path)
            if len(hashes) != len(set(hashes)):
                raise ValueError("Index contains duplicate hashes.")

            if hashes != sorted(hashes):
                raise ValueError("Index hashes are not sorted.")

            expected_size = 4 + len(hashes) * 4
            actual_size = index_path.stat().st_size
            if expected_size != actual_size:
                raise ValueError(
                    f"Size mismatch.\nExpected {expected_size} bytes, got {actual_size} bytes."
                )

            self.log("[validate] Index is valid.")
            self.log(f"           Entries: {len(hashes)}")
            self.log(f"           Size:    {actual_size} bytes")
            self.set_status("Index validated successfully.")
            messagebox.showinfo("Valid Index", "resindex.idx appears valid.")

        except Exception as e:
            messagebox.showerror("Validation Error", str(e))
            self.set_status("Index validation failed.")

    def check_paths(self) -> None:
        try:
            index_path = self.get_index_path()
            paths = self.get_paths()
            if not paths:
                messagebox.showwarning("No Paths", "Add one or more texture paths first.")
                return

            hash_set = set(read_resindex(index_path))
            list_entries: set[str] | None = None
            texture_list_path = self.get_texture_list_path(required=False)
            if texture_list_path is not None and texture_list_path.exists():
                list_entries = set(read_textures_list(texture_list_path))

            self.log()
            self.log("[check] Checking paths...")
            missing = 0
            found = 0
            list_missing = 0
            list_found = 0
            for raw_path in paths:
                aliases = build_aliases(
                    raw_path,
                    png_alias=self.png_alias_var.get(),
                    tga_alias=self.tga_alias_var.get(),
                )

                for alias in aliases:
                    h = resource_hash(alias)
                    if h in hash_set:
                        self.log(f"[found]   0x{h:08X}  {alias}")
                        found += 1
                    else:
                        self.log(f"[missing] 0x{h:08X}  {alias}")
                        missing += 1

                if list_entries is not None:
                    entry = texture_list_entry(raw_path)
                    if entry in list_entries:
                        self.log(f"[list found]   {entry}")
                        list_found += 1
                    else:
                        self.log(f"[list missing] {entry}")
                        list_missing += 1

            self.log(f"[check] Done. Index Found: {found}, Index Missing: {missing}")
            if list_entries is not None:
                self.log(f"[check] textures.list Found: {list_found}, Missing: {list_missing}")
            self.set_status(f"Check complete. Index found {found}, missing {missing}.")

        except Exception as e:
            messagebox.showerror("Check Error", str(e))
            self.set_status("Check failed.")

    def add_paths_to_index(self) -> None:
        try:
            index_path = self.get_index_path()
            paths = self.get_paths()
            if not paths:
                messagebox.showwarning("No Paths", "Add one or more texture paths first.")
                return

            hashes = read_resindex(index_path)
            hash_set = set(hashes)
            if self.backup_var.get():
                backup = make_backup(index_path)
                self.log(f"[backup] {backup}")

            self.log()
            self.log("[add] Adding paths to index...")
            added = 0
            existed = 0
            for raw_path in paths:
                aliases = build_aliases(
                    raw_path,
                    png_alias=self.png_alias_var.get(),
                    tga_alias=self.tga_alias_var.get(),
                )

                for alias in aliases:
                    h = resource_hash(alias)
                    if h in hash_set:
                        self.log(f"[exists] 0x{h:08X}  {alias}")
                        existed += 1
                    else:
                        hash_set.add(h)
                        self.log(f"[add]    0x{h:08X}  {alias}")
                        added += 1

            new_hashes = sorted(hash_set)
            write_resindex(index_path, new_hashes)
            self.log("[add] Done.")
            self.log(f"      Original entries: {len(hashes)}")
            self.log(f"      New entries:      {len(new_hashes)}")
            self.log(f"      Added:            {added}")
            self.log(f"      Already existed:  {existed}")

            list_message = ""
            if self.update_texture_list_var.get():
                self.log()
                self.log("[list] Updating textures.list...")
                list_added, list_existed, list_count = self.add_paths_to_texture_list_file(paths)
                self.log("[list] Done.")
                self.log(f"       New list entries: {list_count}")
                self.log(f"       Added:            {list_added}")
                self.log(f"       Already existed:  {list_existed}")
                list_message = (
                    f"\n\ntextures.list:\n"
                    f"Added: {list_added}\n"
                    f"Already existed: {list_existed}\n"
                    f"New entry count: {list_count}"
                )

            self.set_status(f"Added {added} hash(es). New count: {len(new_hashes)}.")

            messagebox.showinfo(
                "Patch Complete",
                f"Finished patching resindex.idx.\n\n"
                f"Index hashes added: {added}\n"
                f"Index hashes already existed: {existed}\n"
                f"New index entry count: {len(new_hashes)}"
                f"{list_message}",
            )

        except Exception as e:
            messagebox.showerror("Patch Error", str(e))
            self.set_status("Patch failed.")

    def remove_paths_from_index(self) -> None:
        try:
            index_path = self.get_index_path()
            paths = self.get_paths()
            if not paths:
                messagebox.showwarning("No Paths", "Add one or more texture paths first.")
                return

            confirm = messagebox.askyesno(
                "Remove Hashes?",
                "This will remove the selected path hashes from resindex.idx.\n\n"
                "Only do this if you are sure the game no longer needs these resources.\n\n"
                "Continue?",
            )

            if not confirm:
                return

            hashes = read_resindex(index_path)
            hash_set = set(hashes)
            if self.backup_var.get():
                backup = make_backup(index_path)
                self.log(f"[backup] {backup}")

            self.log()
            self.log("[remove] Removing paths from index...")
            removed = 0
            missing = 0
            for raw_path in paths:
                aliases = build_aliases(
                    raw_path,
                    png_alias=self.png_alias_var.get(),
                    tga_alias=self.tga_alias_var.get(),
                )

                for alias in aliases:
                    h = resource_hash(alias)

                    if h in hash_set:
                        hash_set.remove(h)
                        self.log(f"[remove] 0x{h:08X}  {alias}")
                        removed += 1
                    else:
                        self.log(f"[missing] 0x{h:08X}  {alias}")
                        missing += 1

            new_hashes = sorted(hash_set)
            write_resindex(index_path, new_hashes)
            self.log("[remove] Done.")
            self.log(f"         Original entries: {len(hashes)}")
            self.log(f"         New entries:      {len(new_hashes)}")
            self.log(f"         Removed:          {removed}")
            self.log(f"         Missing:          {missing}")

            list_message = ""
            if self.update_texture_list_var.get():
                self.log()
                self.log("[list] Removing entries from textures.list...")
                list_removed, list_missing, list_count = self.remove_paths_from_texture_list_file(paths)
                self.log("[list] Done.")
                self.log(f"       New list entries: {list_count}")
                self.log(f"       Removed:          {list_removed}")
                self.log(f"       Missing:          {list_missing}")
                list_message = (
                    f"\n\ntextures.list:\n"
                    f"Removed: {list_removed}\n"
                    f"Missing: {list_missing}\n"
                    f"New entry count: {list_count}"
                )

            self.set_status(f"Removed {removed} hash(es). New count: {len(new_hashes)}.")
            messagebox.showinfo(
                "Remove Complete",
                f"Finished updating resindex.idx.\n\n"
                f"Index hashes removed: {removed}\n"
                f"Index hashes missing: {missing}\n"
                f"New index entry count: {len(new_hashes)}"
                f"{list_message}",
            )

        except Exception as e:
            messagebox.showerror("Remove Error", str(e))
            self.set_status("Remove failed.")

    def validate_texture_list(self) -> None:
        try:
            texture_list_path = self.get_texture_list_path(required=True)
            assert texture_list_path is not None
            entries = read_textures_list(texture_list_path)
            duplicates = len(entries) - len(set(entries))
            extension_entries = [entry for entry in entries if Path(entry).suffix.lower() in {".3dst", ".png", ".tga"}]

            self.log("[validate] textures.list checked.")
            self.log(f"           Entries:             {len(entries)}")
            self.log(f"           Duplicate entries:   {duplicates}")
            self.log(f"           Extension entries:   {len(extension_entries)}")

            if duplicates or extension_entries:
                message = (
                    "textures.list loaded, but may need cleanup.\n\n"
                    f"Entries: {len(entries)}\n"
                    f"Duplicates: {duplicates}\n"
                    f"Entries still using .3dst/.png/.tga: {len(extension_entries)}"
                )
                messagebox.showwarning("textures.list Check", message)
                self.set_status("textures.list checked with warnings.")
            else:
                messagebox.showinfo("Valid textures.list", "textures.list appears valid.")
                self.set_status("textures.list validated successfully.")

        except Exception as e:
            messagebox.showerror("textures.list Validation Error", str(e))
            self.set_status("textures.list validation failed.")

    def dump_hashes(self) -> None:
        try:
            index_path = self.get_index_path()
            hashes = read_resindex(index_path)

            output = filedialog.asksaveasfilename(
                title="Save hash dump",
                defaultextension=".txt",
                filetypes=[
                    ("Text files", "*.txt"),
                    ("All files", "*.*"),
                ],
                initialfile="resindex_hash_dump.txt",
            )

            if not output:
                return

            output_path = Path(output)
            with output_path.open("w", encoding="utf-8") as f:
                f.write(f"Source: {index_path}\n")
                f.write(f"Entries: {len(hashes)}\n\n")

                for h in hashes:
                    f.write(f"0x{h:08X}\n")

            self.log(f"[dump] Wrote hash dump: {output_path}")
            self.set_status(f"Dumped {len(hashes)} hashes.")

        except Exception as e:
            messagebox.showerror("Dump Error", str(e))
            self.set_status("Dump failed.")

def main() -> None:
    app = ResIndexGUI()
    app.mainloop()

if __name__ == "__main__":
    main()
