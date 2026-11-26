#!/usr/bin/env python3
"""
DPT Dump Tool – matches manual dpt.py success path

Manual that works:
  python dpt.py classes.dex OoooooOooo out_dir
  (real multi-dex files + Oooo → restored/)

Protected APK often has only a STUB classes.dex (few methods).
Real DEX must come from a folder (like your Dumper/ folder).

Flow:
  1. APK path (for Oooo list + final inject target)
  2. Select Oooo from assets
  3. Choose DEX source:
       [1] DEX inside APK  (only if not stub)
       [2] DEX folder path (manual style – recommended)
  4. Real patch via dpt_core primitives
  5. Only inject if applied>0 and hash changed
  6. Add as classes2/3/4… without removing existing
  7. Clean temp
"""

from __future__ import annotations

import sys
import os
import re
import shutil
import hashlib
import zipfile
import tempfile
import traceback
import zipimport
from pathlib import Path
from typing import List, Tuple

ARCHIVE_NAME = "@DPTMOD"
COMMAND_NAME = "dptdump"
MIN_PYTHON = (3, 8)

FIXED_OUTPUT_CANDIDATES = [
    Path("/storage/emulated/0/@TMHMOD"),
    Path("/sdcard/@TMHMOD"),
    Path("/storage/emulated/0/TMHMOD"),
    Path.home() / "@TMHMOD",
]

class C:
    R = "\033[0m"; BD = "\033[1m"
    g = "\033[38;5;46m"; c = "\033[38;5;51m"
    y = "\033[38;5;226m"; r = "\033[38;5;196m"
    w = "\033[38;5;255m"; d = "\033[38;5;240m"

def ok(m): print(f"  {C.g}\u2713{C.R}  {m}")
def err(m): print(f"  {C.r}\u2717{C.R}  {m}", file=sys.stderr)
def info(m): print(f"  {C.c}\u2022{C.R}  {m}")
def warn(m): print(f"  {C.y}!{C.R}  {m}")

def banner():
    print()
    print(C.c + "  " + "\u2550"*58 + C.R)
    print(f"  {C.BD}{C.w}  DPT DUMP  \u2013  REAL DEX Restorer{C.R}")
    print(C.c + "  " + "\u2550"*58 + C.R)
    print()

def sdir() -> Path:
    return Path(__file__).resolve().parent

def archive_path() -> Path:
    return sdir() / ARCHIVE_NAME

def get_fixed_output_dir() -> Path:
    for p in FIXED_OUTPUT_CANDIDATES:
        try:
            p.mkdir(parents=True, exist_ok=True)
            t = p / ".write_test"
            t.write_text("ok", encoding="utf-8")
            t.unlink(missing_ok=True)
            return p
        except Exception:
            continue
    fb = sdir() / "FixedAPKs"
    fb.mkdir(parents=True, exist_ok=True)
    return fb

def input_path(label: str) -> str:
    raw = input(f"  {C.c}\u00bb{C.R} {label}: ").strip()
    return raw.strip('"').strip("'").replace("\\ ", " ")

def load_dpt():
    ap = archive_path()
    if not ap.exists():
        err(f"Archive missing: {ap}")
        sys.exit(1)
    s = str(ap.resolve())
    if s not in sys.path:
        sys.path.insert(0, s)
    # zipimport: prefer exec_module style if available, else load_module
    importer = zipimport.zipimporter(s)
    try:
        spec = importer.find_spec("dpt_core")
        if spec and spec.loader:
            import importlib.util
            mod = importlib.util.module_from_spec(spec)
            sys.modules["dpt_core"] = mod
            spec.loader.exec_module(mod)
        else:
            mod = importer.load_module("dpt_core")
            sys.modules["dpt_core"] = mod
    except Exception:
        mod = importer.load_module("dpt_core")
        sys.modules["dpt_core"] = mod
    ok("Loaded: dpt_core")
    return mod

def is_termux() -> bool:
    prefix = os.environ.get("PREFIX", "")
    return "com.termux" in prefix or Path("/data/data/com.termux").exists()

def install_cmd() -> bool:
    if not is_termux():
        warn("Termux nahi \u2013 command install skip")
        return False
    prefix = os.environ.get("PREFIX") or "/data/data/com.termux/files/usr"
    bd = Path(prefix) / "bin"
    if not bd.is_dir():
        return False
    py = sys.executable or "python3"
    main_abs = Path(__file__).resolve()
    content = f'#!/data/data/com.termux/files/usr/bin/sh\nexec "{py}" "{main_abs}" "$@"\n'
    try:
        wp = bd / COMMAND_NAME
        wp.write_text(content, encoding="utf-8")
        wp.chmod(0o755)
        ok(f"Command installed: {wp}")
        return True
    except Exception as e:
        err(f"Install failed: {e}")
        return False

def first_run() -> bool:
    return not (sdir() / ".dpt_installed").exists()

def mark_installed():
    try:
        (sdir() / ".dpt_installed").write_text("1\n", encoding="utf-8")
    except Exception:
        pass

def sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()[:12]

def list_apk_entries(apk: Path) -> List[str]:
    with zipfile.ZipFile(str(apk), "r") as zf:
        return zf.namelist()

def _dex_num(name: str) -> int:
    m = re.match(r"^classes(\d*)\.dex$", os.path.basename(name), re.I)
    if not m:
        return 10**9
    s = m.group(1)
    return 0 if not s else int(s)

def list_existing_dex_names(entries: List[str]) -> List[str]:
    dex = [e for e in entries if re.match(r"^classes\d*\.dex$", os.path.basename(e), re.I)]
    root = [e for e in dex if "/" not in e.replace("\\", "/")]
    return sorted(root or dex, key=lambda n: _dex_num(n))

def list_asset_candidates(entries: List[str]) -> List[str]:
    """Prefer assets/ and Oooo-like names; still show others as fallback."""
    preferred, other = [], []
    for e in entries:
        el = e.replace("\\", "/")
        base = os.path.basename(el)
        if not base or el.endswith("/"):
            continue
        if el.startswith("assets/") or "/assets/" in el:
            preferred.append(e)
        elif re.search(r"O+|ooo", base, re.I):
            preferred.append(e)
        elif not base.lower().endswith((".dex", ".so", ".png", ".jpg", ".xml")) and "res/" not in el:
            other.append(e)
    # put Oooo names first inside preferred
    def score(x):
        b = os.path.basename(x).lower()
        if "ooo" in b: return 0
        if b.endswith(".ajm"): return 1
        return 2
    preferred.sort(key=score)
    seen, out = set(), []
    for x in preferred + other:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def extract_entry(apk: Path, entry: str, dest: Path) -> bytes:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(apk), "r") as zf:
        data = zf.read(entry)
    dest.write_bytes(data)
    return data

def next_add_names(existing: List[str], count: int) -> List[str]:
    used = {_dex_num(e) for e in existing}
    names = []
    n = 2 if 0 in used else 0
    while len(names) < count:
        if n == 1:
            n = 2
            continue
        if n in used:
            n += 1
            continue
        names.append("classes.dex" if n == 0 else f"classes{n}.dex")
        used.add(n)
        n += 1
    return names

def inject_dex_into_apk(src_apk: Path, dex_files: List[Tuple[str, bytes]], out_apk: Path):
    out_apk.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(src_apk), "r") as zin:
        existing = set(zin.namelist())
        with zipfile.ZipFile(str(out_apk), "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename in ("AndroidManifest.xml", "resources.arsc") or info.filename.endswith(".so"):
                    zout.writestr(info, data, compress_type=zipfile.ZIP_STORED)
                else:
                    zout.writestr(info, data, compress_type=info.compress_type)
            for arcname, data in dex_files:
                if arcname in existing:
                    warn(f"Skip existing: {arcname}")
                    continue
                zi = zipfile.ZipInfo(arcname)
                zi.compress_type = zipfile.ZIP_STORED
                zout.writestr(zi, data)
                ok(f"Added: {arcname} ({len(data)} bytes)")

def collect_dex_from_folder(folder: Path) -> List[Tuple[str, bytes]]:
    files = []
    for p in sorted(folder.iterdir(), key=lambda x: _dex_num(x.name)):
        if p.is_file() and p.suffix.lower() == ".dex":
            files.append((p.name, p.read_bytes()))
    return files

def collect_dex_from_apk(apk: Path) -> List[Tuple[str, bytes]]:
    out = []
    with zipfile.ZipFile(str(apk), "r") as zf:
        names = [n for n in zf.namelist()
                 if re.match(r"^classes\d*\.dex$", os.path.basename(n), re.I)
                 and "/" not in n.replace("\\", "/")]
        if not names:
            names = [n for n in zf.namelist() if n.lower().endswith(".dex")]
        names = sorted(names, key=lambda n: _dex_num(n))
        for n in names:
            out.append((os.path.basename(n), zf.read(n)))
    return out

def real_dump_list(dpt, dex_list: List[Tuple[str, bytes]], oooo_path: Path) -> List[Tuple[str, bytes, int, int]]:
    """
    Same logic as successful manual dpt.py loop.
    Returns only DEX with applied > 0 and hash changed.
    """
    dcount, methods = dpt.parse_oooo(str(oooo_path))
    if not methods:
        err("Oooo parse failed / empty methods")
        return []
    ok(f"Oooo: dex_count={dcount}, methods={len(methods)}")
    blocks = dpt.build_oooo_blocks(methods)

    results = []
    for name, original in dex_list:
        h_before = sha1(original)
        info(f"--- {name}  sha1={h_before}  size={len(original)}")
        try:
            dex_map, skipped = dpt.analyze_dex_spec_with_dupe_skip(original)
        except Exception as e:
            warn(f"{name}: parse fail ({e}) \u2013 skip")
            continue
        ok(f"{name}: mapped={len(dex_map)} (skipped dup={skipped})")

        best_i, best_c = dpt.best_match_block(dex_map, blocks)
        if best_i < 0 or best_c == 0:
            warn(f"{name}: overlap=0 \u2013 NO dump (not adding protected copy)")
            continue
        ok(f"{name}: Oooo dex_index={best_i} overlap={best_c}")

        patched, applied, attempted = dpt.patch_one_dex(original, dex_map, blocks[best_i])
        h_after = sha1(patched)
        if applied <= 0:
            warn(f"{name}: applied=0 \u2013 skip")
            continue
        if h_before == h_after:
            warn(f"{name}: hash unchanged \u2013 skip")
            continue
        ok(f"{name}: DUMPED applied={applied}/{attempted}  {h_before} \u2192 {h_after}")
        results.append((name, patched, applied, attempted))
    return results


def run_dump_flow():
    out_dir = get_fixed_output_dir()
    info(f"Output folder: {C.c}{out_dir}{C.R}")
    print()

    apk_s = input_path("APK path")
    if not apk_s:
        err("Empty path"); return
    apk = Path(apk_s).expanduser().resolve()
    if not apk.is_file():
        err(f"APK not found: {apk}"); return

    print()
    info(f"APK: {apk.name}")
    try:
        entries = list_apk_entries(apk)
    except Exception as e:
        err(f"Cannot open APK: {e}"); return

    existing_dex = list_existing_dex_names(entries)
    info("Existing DEX in APK: " + (", ".join(os.path.basename(x) for x in existing_dex) or "(none)"))

    # --- Oooo select (assets first) ---
    assets = list_asset_candidates(entries)
    if not assets:
        err("Oooo/asset file nahi mili"); return

    print()
    print(C.y + "  " + "\u2500"*50 + C.R)
    print(f"  {C.BD}Select Oooo file:{C.R}")
    print(C.y + "  " + "\u2500"*50 + C.R)
    for i, a in enumerate(assets, 1):
        mark = "  << Oooo?" if "ooo" in os.path.basename(a).lower() else ""
        print(f"  {C.y}[{i}]{C.R}  {a}{C.g}{mark}{C.R}")
    print(C.y + "  " + "\u2500"*50 + C.R)
    print()
    sel = input(f"  {C.c}\u00bb{C.R} Number: ").strip()
    try:
        idx = int(sel)
        if not (1 <= idx <= len(assets)):
            raise ValueError
    except ValueError:
        err("Invalid selection"); return
    oooo_entry = assets[idx - 1]
    ok(f"Selected Oooo: {oooo_entry}")

    # --- DEX source (THIS was the bug) ---
    print()
    print(C.y + "  " + "\u2500"*50 + C.R)
    print(f"  {C.BD}DEX source (manual jaisa):{C.R}")
    print(C.y + "  " + "\u2500"*50 + C.R)
    print(f"  {C.y}[1]{C.R}  APK ke andar se DEX")
    print(f"  {C.y}[2]{C.R}  Folder path (jahan classes.dex / classes2.dex hain)")
    print(C.y + "  " + "\u2500"*50 + C.R)
    print()
    print(f"  {C.d}Note: Protected APK mein aksar stub classes.dex hota hai.")
    print(f"  {C.d}Manual success ke liye option [2] use karo – Dumper folder.{C.R}")
    print()
    src_choice = input(f"  {C.c}\u00bb{C.R} Select: ").strip()

    work = Path(tempfile.mkdtemp(prefix="dpt_work_"))
    try:
        oooo_path = work / "oooo.bin"
        extract_entry(apk, oooo_entry, oooo_path)
        ok(f"Oooo size: {oooo_path.stat().st_size} bytes")

        if src_choice == "2":
            folder_s = input_path("DEX folder path")
            if not folder_s:
                err("Empty folder"); return
            folder = Path(folder_s).expanduser().resolve()
            if not folder.is_dir():
                err(f"Not a folder: {folder}"); return
            dex_list = collect_dex_from_folder(folder)
            if not dex_list:
                err("Folder mein koi .dex nahi"); return
            ok(f"Folder DEX: {', '.join(n for n,_ in dex_list)}")
        else:
            dex_list = collect_dex_from_apk(apk)
            if not dex_list:
                err("APK mein DEX nahi"); return
            ok(f"APK DEX: {', '.join(n for n,_ in dex_list)}")
            if len(dex_list) == 1:
                warn("Sirf 1 DEX mili – agar stub hai to overlap=0 aa sakta hai.")
                warn("Tab option [2] se real classes*.dex folder do.")

        dpt = load_dpt()
        print()
        info("REAL dump (same as: python dpt.py classes.dex Oooo out)...")
        print()

        dumped = real_dump_list(dpt, dex_list, oooo_path)

        if not dumped:
            print()
            err("Koi DEX real-dump nahi hui (overlap=0 / applied=0).")
            err("Protected stub DEX ko ADD nahi kiya.")
            err("Solution: option [2] – wahi folder do jahan manual dpt.py successful tha.")
            return

        print()
        ok(f"Real dumped: {len(dumped)}")
        new_names = next_add_names(existing_dex, len(dumped))
        inject_list: List[Tuple[str, bytes]] = []
        for (orig, data, applied, attempted), new_name in zip(dumped, new_names):
            info(f"  {orig} (patched {applied}/{attempted}) \u2192 {new_name}")
            inject_list.append((new_name, data))

        out_apk = out_dir / (apk.stem + "-dumped.apk")
        k = 1
        while out_apk.exists():
            out_apk = out_dir / f"{apk.stem}-dumped({k}).apk"
            k += 1

        print()
        info("Building APK...")
        inject_dex_into_apk(apk, inject_list, out_apk)

        print()
        print(C.g + "  " + "\u2550"*58 + C.R)
        print(f"  {C.g}{C.BD}\u2713  REAL DUMP + INJECT OK{C.R}")
        print(C.g + "  " + "\u2550"*58 + C.R)
        print(f"  {C.d}Output :{C.R}  {C.c}{out_apk}{C.R}")
        print(f"  {C.d}Added  :{C.R}  {', '.join(n for n,_ in inject_list)}")
        print(C.g + "  " + "\u2550"*58 + C.R)

    except KeyboardInterrupt:
        warn("Cancelled")
    except Exception as e:
        err(f"Error: {e}")
        traceback.print_exc()
    finally:
        try:
            if work.exists():
                shutil.rmtree(work, ignore_errors=True)
                info("Temp cleaned")
        except Exception:
            pass


def main():
    if sys.version_info[:2] < MIN_PYTHON:
        err(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required")
        sys.exit(1)
    banner()
    if not archive_path().exists():
        err(f"'{ARCHIVE_NAME}' missing next to main.py")
        sys.exit(1)
    if first_run():
        info("First run \u2013 setup...")
        install_cmd()
        ok(f"Output: {get_fixed_output_dir()}")
        mark_installed()
        print()
        print(C.g + "  " + "\u2550"*58 + C.R)
        print(f"  {C.g}{C.BD}\u2713  SETUP COMPLETE{C.R}")
        print(C.g + "  " + "\u2550"*58 + C.R)
        print(f"  {C.w}Command: {C.c}{COMMAND_NAME}{C.R}")
        print(C.g + "  " + "\u2550"*58 + C.R)
        print()
    run_dump_flow()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(); warn("Bye")
    except Exception as e:
        err(f"Fatal: {e}")
        traceback.print_exc()
