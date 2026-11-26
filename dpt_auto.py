
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DPT AUTO - TMHMOD
Three tools:
1. Unpack APK
2. Fix APK
3. Merge DEX

Original DPT and its modules are not modified.
"""

from __future__ import annotations

import os
import re
import sys
import shlex
import hashlib
import zipfile
import tempfile
import subprocess

from pathlib import Path
from datetime import datetime


# ============================================================
# CONFIGURATION
# ============================================================

APP_NAME = "DPT AUTO"
COMMAND_NAME = "tmhdpt"

OUTPUT_DIRS = [
    Path("/storage/emulated/0/@TMHMOD"),
    Path("/sdcard/@TMHMOD"),
]

DEX_MAGIC = b"dex\n"


# ============================================================
# TERMINAL UI
# ============================================================

class UI:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    CYAN = "\033[38;5;51m"
    GREEN = "\033[38;5;46m"
    YELLOW = "\033[38;5;226m"
    RED = "\033[38;5;196m"
    WHITE = "\033[38;5;255m"
    PURPLE = "\033[38;5;141m"

    @staticmethod
    def line(char="═", color=None):
        color = color or UI.CYAN
        print(f"{color}{char * 58}{UI.RESET}")

    @staticmethod
    def info(message):
        print(f"  {UI.CYAN}◆{UI.RESET}  {message}")

    @staticmethod
    def success(message):
        print(f"  {UI.GREEN}✔{UI.RESET}  {message}")

    @staticmethod
    def warning(message):
        print(f"  {UI.YELLOW}!{UI.RESET}  {message}")

    @staticmethod
    def error(message):
        print(f"  {UI.RED}✘{UI.RESET}  {message}")

    @staticmethod
    def banner():
        print()
        UI.line()
        print(
            f"  {UI.BOLD}{UI.WHITE}"
            "             TMHMOD  |  DPT AUTO"
            f"{UI.RESET}"
        )
        print(
            f"  {UI.DIM}"
            "          DEX MANAGEMENT SYSTEM"
            f"{UI.RESET}"
        )
        UI.line()
        print()


# ============================================================
# SHORTCUT INSTALLER
# ============================================================

def install_shortcut():
    prefix = os.environ.get("PREFIX")

    if not prefix:
        UI.warning("Termux PREFIX not detected. Shortcut setup skipped.")
        return False

    bin_dir = Path(prefix) / "bin"

    try:
        bin_dir.mkdir(parents=True, exist_ok=True)

        launcher = bin_dir / COMMAND_NAME

        python_path = shlex.quote(sys.executable)
        script_path = shlex.quote(str(Path(__file__).resolve()))

        content = (
            "#!/data/data/com.termux/files/usr/bin/sh\n"
            f"exec {python_path} {script_path} \"$@\"\n"
        )

        if not launcher.exists() or launcher.read_text(
            encoding="utf-8", errors="ignore"
        ) != content:
            launcher.write_text(content, encoding="utf-8")
            launcher.chmod(0o755)

        return True

    except Exception as exc:
        UI.error(f"Shortcut installation failed: {exc}")
        return False


# ============================================================
# COMMON HELPERS
# ============================================================

def ask_path(label):
    try:
        value = input(
            f"\n  {UI.CYAN}›{UI.RESET} {label}: "
        ).strip()
    except (KeyboardInterrupt, EOFError):
        return None

    value = value.strip('"').strip("'")

    if not value:
        return None

    return Path(value).expanduser().resolve()


def pause():
    try:
        input(f"\n  {UI.DIM}Press Enter to continue...{UI.RESET}")
    except (KeyboardInterrupt, EOFError):
        pass


def output_directory():
    for folder in OUTPUT_DIRS:
        try:
            folder.mkdir(parents=True, exist_ok=True)

            test = folder / ".tmhdpt_test"
            test.write_text("ok", encoding="utf-8")
            test.unlink()

            return folder

        except Exception:
            continue

    raise RuntimeError(
        "Output folder unavailable. Run termux-setup-storage first."
    )


def unique_output(folder, name):
    path = folder / name

    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    index = 1

    while True:
        candidate = folder / f"{stem}({index}){suffix}"

        if not candidate.exists():
            return candidate

        index += 1


def valid_dex(data):
    return (
        len(data) >= 0x70
        and data.startswith(DEX_MAGIC)
    )


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def dex_number(name):
    base = Path(name).name.lower()

    match = re.fullmatch(r"classes(\d*)\.dex", base)

    if not match:
        return 10**9

    number = match.group(1)

    return 1 if not number else int(number)


# ============================================================
# APK DEX HELPERS
# ============================================================

def get_root_dex_names(zip_file):
    names = []

    for name in zip_file.namelist():
        normalized = name.replace("\\", "/")

        if "/" in normalized:
            continue

        if re.fullmatch(
            r"classes\d*\.dex",
            normalized,
            re.IGNORECASE
        ):
            names.append(name)

    return sorted(names, key=dex_number)


def collect_apk_dex(apk):
    results = []

    with zipfile.ZipFile(apk, "r") as zf:
        entries = [
            name for name in zf.namelist()
            if name.lower().endswith(".dex")
            and not name.endswith("/")
        ]

        entries.sort(
            key=lambda name: (
                dex_number(name),
                name.lower()
            )
        )

        for name in entries:
            data = zf.read(name)

            if not valid_dex(data):
                UI.warning(f"Invalid DEX skipped: {name}")
                continue

            results.append((name, data))

    return results


def collect_folder_dex(folder):
    results = []

    files = [
        path for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() == ".dex"
    ]

    files.sort(
        key=lambda path: (
            dex_number(path.name),
            str(path).lower()
        )
    )

    for path in files:
        data = path.read_bytes()

        if not valid_dex(data):
            UI.warning(f"Invalid DEX skipped: {path.name}")
            continue

        results.append((path.name, data))

    return results


def assign_dex_names(existing_entries, count):
    used = set()

    for name in existing_entries:
        normalized = name.replace("\\", "/")

        if "/" in normalized:
            continue

        if re.fullmatch(
            r"classes\d*\.dex",
            normalized,
            re.IGNORECASE
        ):
            used.add(dex_number(normalized))

    names = []
    number = 2

    while len(names) < count:
        if number not in used:
            names.append(f"classes{number}.dex")
            used.add(number)

        number += 1

    return names


# ============================================================
# APK BUILD ENGINE
# ============================================================

def is_old_signature(name):
    normalized = name.replace("\\", "/").lower()

    if not normalized.startswith("meta-inf/"):
        return False

    filename = normalized.rsplit("/", 1)[-1]

    return (
        filename == "manifest.mf"
        or filename.endswith(".sf")
        or filename.endswith(".rsa")
        or filename.endswith(".dsa")
        or filename.endswith(".ec")
    )


def build_apk(original_apk, dex_items, output_apk):
    if not dex_items:
        raise ValueError("No valid DEX files to add.")

    with zipfile.ZipFile(original_apk, "r") as zin:

        existing = zin.namelist()

        root_dex = get_root_dex_names(zin)

        if len(root_dex) != 1 or Path(root_dex[0]).name.lower() != "classes.dex":
            raise ValueError(
                "Original APK must contain only one root classes.dex."
            )

        new_names = assign_dex_names(existing, len(dex_items))

        for name in new_names:
            if name in existing:
                raise ValueError(f"DEX name collision: {name}")

        with zipfile.ZipFile(
            output_apk,
            "w",
            allowZip64=True
        ) as zout:

            zout.comment = zin.comment

            # Preserve original APK entries.
            # Old v1 signature files are omitted because the APK changes.
            for item in zin.infolist():

                if is_old_signature(item.filename):
                    continue

                data = zin.read(item.filename)

                zout.writestr(
                    item,
                    data,
                    compress_type=item.compress_type
                )

            # Add new DEX entries.
            for (source_name, data), new_name in zip(
                dex_items,
                new_names
            ):
                if not valid_dex(data):
                    raise ValueError(
                        f"Invalid DEX data: {source_name}"
                    )

                item = zipfile.ZipInfo(new_name)
                item.compress_type = zipfile.ZIP_STORED

                zout.writestr(item, data)

                UI.success(
                    f"{source_name}  →  {new_name}"
                )

    # Verify the completed archive.
    with zipfile.ZipFile(output_apk, "r") as check:

        bad = check.testzip()

        if bad:
            raise RuntimeError(
                f"APK archive verification failed: {bad}"
            )

        final_names = get_root_dex_names(check)

        for name in new_names:
            if name not in final_names:
                raise RuntimeError(
                    f"Added DEX missing from final APK: {name}"
                )

    return new_names


# ============================================================
# ORIGINAL DPT DISCOVERY
# ============================================================

def find_original_dpt():
    base = Path(__file__).resolve().parent

    preferred = [
        base / "Dumper" / "dpt.py",
        base / "Dumper" / "DPT.py",
        base / "dpt.py",
        base / "DPT.py",
    ]

    for path in preferred:
        if path.is_file():
            return path

    candidates = []

    for path in base.rglob("*.py"):
        if path.name.lower() not in ("dpt.py",):
            continue

        if path.resolve() == Path(__file__).resolve():
            continue

        candidates.append(path)

    if candidates:
        return sorted(
            candidates,
            key=lambda p: (
                len(p.relative_to(base).parts),
                str(p).lower()
            )
        )[0]

    return None


# ============================================================
# UNPACK APK - OOOO SELECTION
# ============================================================

def find_oooo_candidates(entries):
    preferred = []
    others = []

    ignored = {
        ".dex", ".so", ".png", ".jpg", ".jpeg",
        ".webp", ".gif", ".xml", ".arsc",
        ".ttf", ".otf", ".mp3", ".mp4"
    }

    for name in entries:
        normalized = name.replace("\\", "/")

        if normalized.endswith("/"):
            continue

        base = Path(normalized).name

        if not base:
            continue

        suffix = Path(base).suffix.lower()

        if suffix in ignored:
            continue

        lower = base.lower()

        if (
            normalized.lower().startswith("assets/")
            or "/assets/" in normalized.lower()
            or "ooo" in lower
        ):
            preferred.append(name)

        elif "res/" not in normalized.lower():
            others.append(name)

    def score(name):
        base = Path(name).name.lower()

        if "ooo" in base:
            return 0

        if base.endswith(".ajm"):
            return 1

        return 2

    preferred.sort(key=score)
    others.sort(key=score)

    result = []
    seen = set()

    for name in preferred + others:
        if name not in seen:
            seen.add(name)
            result.append(name)

    return result


def select_oooo(entries):
    candidates = find_oooo_candidates(entries)

    if not candidates:
        UI.error("No candidate files found in APK.")
        return None

    print()
    UI.line("─")

    print(f"  {UI.BOLD}SELECT OOOO FILE{UI.RESET}")
    print()

    for index, name in enumerate(candidates, 1):
        marker = (
            f" {UI.GREEN}● OOOO?{UI.RESET}"
            if "ooo" in Path(name).name.lower()
            else ""
        )

        print(
            f"  {UI.YELLOW}[{index}]{UI.RESET} "
            f"{name}{marker}"
        )

    UI.line("─")

    try:
        choice = int(input("\n  Select number: ").strip())

        if not 1 <= choice <= len(candidates):
            raise ValueError

        return candidates[choice - 1]

    except ValueError:
        UI.error("Invalid selection.")
        return None


# ============================================================
# OPTION 1 - UNPACK APK
# ============================================================

def unpack_apk():
    UI.banner()

    dpt_script = find_original_dpt()

    if not dpt_script:
        UI.error("Original dpt.py not found.")
        UI.info("Expected original DPT script in this folder or its subfolder.")
        return

    UI.success(f"Original DPT: {dpt_script}")

    apk = ask_path("Enter APK path")

    if not apk or not apk.is_file():
        UI.error("APK file not found.")
        return

    if not zipfile.is_zipfile(apk):
        UI.error("Invalid APK/ZIP file.")
        return

    try:
        with zipfile.ZipFile(apk, "r") as zf:

            original_dex = get_root_dex_names(zf)

            if (
                len(original_dex) != 1
                or Path(original_dex[0]).name.lower() != "classes.dex"
            ):
                UI.error(
                    "Expected exactly one original root classes.dex."
                )
                return

            oooo_entry = select_oooo(zf.namelist())

            if not oooo_entry:
                return

            dex_data = zf.read(original_dex[0])
            oooo_data = zf.read(oooo_entry)

        if not valid_dex(dex_data):
            UI.error("Original APK DEX is invalid.")
            return

        if not oooo_data:
            UI.error("Selected Oooo file is empty.")
            return

        with tempfile.TemporaryDirectory(
            prefix="tmhdpt_unpack_"
        ) as temporary:

            work = Path(temporary)

            input_dir = work / "input"
            oooo_dir = work / "selected"
            output_dir = work / "output"

            input_dir.mkdir()
            oooo_dir.mkdir()
            output_dir.mkdir()

            dex_path = input_dir / Path(original_dex[0]).name
            dex_path.write_bytes(dex_data)

            # Preserve exact Oooo filename.
            oooo_path = oooo_dir / Path(oooo_entry).name
            oooo_path.write_bytes(oooo_data)

            UI.success("Temporary input files ready.")
            UI.info("Executing original DPT...")

            env = os.environ.copy()

            module_paths = [
                str(dpt_script.parent),
                str(dpt_script.parent.parent),
            ]

            old_path = env.get("PYTHONPATH", "")

            if old_path:
                module_paths.append(old_path)

            env["PYTHONPATH"] = os.pathsep.join(module_paths)

            command = [
                sys.executable,
                str(dpt_script),
                str(dex_path),
                str(oooo_path),
                str(output_dir),
            ]

            result = subprocess.run(
                command,
                cwd=str(dpt_script.parent),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace"
            )

            print()

            if result.stdout:
                print(result.stdout.rstrip())

            if result.returncode != 0:
                UI.error("Original DPT execution failed.")
                return

            # Require positive restoration confirmation.
            applied_values = re.findall(
                r"applied\s*=\s*(\d+)",
                result.stdout or "",
                re.IGNORECASE
            )

            if (
                not applied_values
                or not any(int(value) > 0 for value in applied_values)
            ):
                UI.error("No positive restoration confirmation found.")
                UI.warning("Output copy alone is not treated as restoration.")
                return

            restored_dir = output_dir / "restored"

            if not restored_dir.is_dir():
                UI.error("DPT restored folder not found.")
                return

            restored_files = sorted(
                restored_dir.rglob("*.dex"),
                key=lambda p: dex_number(p.name)
            )

            if not restored_files:
                UI.error("No restored DEX file found.")
                return

            restored_items = []

            for path in restored_files:
                data = path.read_bytes()

                if not valid_dex(data):
                    continue

                if sha256(data) == sha256(dex_data):
                    UI.warning(
                        f"Unchanged DEX skipped: {path.name}"
                    )
                    continue

                restored_items.append((path.name, data))

            if not restored_items:
                UI.error("No changed valid DEX was produced.")
                return

            output_folder = output_directory()

            final_apk = unique_output(
                output_folder,
                apk.stem + "-DPT-AUTO.apk"
            )

            UI.info("Building final APK...")

            build_apk(
                apk,
                restored_items,
                final_apk
            )

            print()
            UI.line()
            UI.success("UNPACK APK COMPLETED")
            print(f"  Output: {final_apk}")
            UI.line()

    except Exception as exc:
        UI.error(f"Unpack failed: {exc}")


# ============================================================
# COMMON FIX / MERGE OPERATION
# ============================================================

def add_dex_to_original(original_apk, dex_items, output_suffix):
    if not original_apk or not original_apk.is_file():
        UI.error("Original APK not found.")
        return

    if not zipfile.is_zipfile(original_apk):
        UI.error("Original APK is not a valid ZIP archive.")
        return

    if not dex_items:
        UI.error("No valid DEX files found.")
        return

    try:
        with zipfile.ZipFile(original_apk, "r") as zf:
            original_dex = get_root_dex_names(zf)

        if (
            len(original_dex) != 1
            or Path(original_dex[0]).name.lower() != "classes.dex"
        ):
            UI.error(
                "Original APK must contain only one root classes.dex."
            )
            return

        output_folder = output_directory()

        output_apk = unique_output(
            output_folder,
            original_apk.stem + output_suffix + ".apk"
        )

        print()
        UI.info(f"DEX files selected: {len(dex_items)}")

        for name, data in dex_items:
            UI.info(f"{name}  |  {len(data)} bytes")

        print()
        UI.info("Adding DEX files without replacing original DEX...")

        new_names = build_apk(
            original_apk,
            dex_items,
            output_apk
        )

        print()
        UI.line()
        UI.success("APK CREATED SUCCESSFULLY")
        print(f"  {UI.CYAN}Output:{UI.RESET} {output_apk}")
        print(f"  {UI.CYAN}Added:{UI.RESET} {', '.join(new_names)}")
        UI.line()

    except Exception as exc:
        UI.error(f"APK build failed: {exc}")


# ============================================================
# OPTION 2 - FIX APK
# ============================================================

def fix_apk():
    UI.banner()

    print(f"  {UI.BOLD}FIX APK{UI.RESET}")
    print(
        f"  {UI.DIM}"
        "Copy DEX files from corrupt APK into original APK."
        f"{UI.RESET}"
    )

    corrupt_apk = ask_path("Enter CORRUPT APK path")

    if not corrupt_apk or not corrupt_apk.is_file():
        UI.error("Corrupt APK not found.")
        return

    if not zipfile.is_zipfile(corrupt_apk):
        UI.error("Corrupt APK archive cannot be opened.")
        return

    UI.info("Reading DEX files from corrupt APK...")

    try:
        dex_items = collect_apk_dex(corrupt_apk)

    except Exception as exc:
        UI.error(f"Cannot read corrupt APK: {exc}")
        return

    if not dex_items:
        UI.error("No valid DEX files found in corrupt APK.")
        return

    UI.success(f"Found {len(dex_items)} valid DEX file(s).")

    original_apk = ask_path("Enter ORIGINAL APK path")

    if not original_apk:
        UI.error("Original APK path is required.")
        return

    if original_apk.resolve() == corrupt_apk.resolve():
        UI.error("Both APK paths must be different.")
        return

    add_dex_to_original(
        original_apk,
        dex_items,
        "-FIXED"
    )


# ============================================================
# OPTION 3 - MERGE DEX
# ============================================================

def merge_dex():
    UI.banner()

    print(f"  {UI.BOLD}MERGE DEX{UI.RESET}")
    print(
        f"  {UI.DIM}"
        "Add all DEX files from a folder into an original APK."
        f"{UI.RESET}"
    )

    folder = ask_path("Enter DEX folder path")

    if not folder or not folder.is_dir():
        UI.error("Valid DEX folder not found.")
        return

    UI.info("Scanning folder for DEX files...")

    try:
        dex_items = collect_folder_dex(folder)

    except Exception as exc:
        UI.error(f"Folder reading failed: {exc}")
        return

    if not dex_items:
        UI.error("No valid .dex files found in folder.")
        return

    UI.success(f"Found {len(dex_items)} valid DEX file(s).")

    original_apk = ask_path("Enter ORIGINAL APK path")

    if not original_apk:
        UI.error("Original APK path is required.")
        return

    add_dex_to_original(
        original_apk,
        dex_items,
        "-MERGED"
    )


# ============================================================
# MAIN MENU
# ============================================================

def main_menu():
    while True:
        UI.banner()

        print(
            f"  {UI.DIM}Select an operation to continue{UI.RESET}"
        )
        print()

        print(
            f"  {UI.CYAN}[1]{UI.RESET}  "
            f"{UI.BOLD}UNPACK APK{UI.RESET}"
        )
        print(
            f"  {UI.DIM}     Oooo selection + original DPT restoration"
            f"{UI.RESET}"
        )
        print()

        print(
            f"  {UI.CYAN}[2]{UI.RESET}  "
            f"{UI.BOLD}FIX APK{UI.RESET}"
        )
        print(
            f"  {UI.DIM}     Transfer DEX from corrupt APK"
            f"{UI.RESET}"
        )
        print()

        print(
            f"  {UI.CYAN}[3]{UI.RESET}  "
            f"{UI.BOLD}MERGE DEX{UI.RESET}"
        )
        print(
            f"  {UI.DIM}     Transfer DEX from a folder"
            f"{UI.RESET}"
        )
        print()

        UI.line("─")

        print(
            f"  {UI.YELLOW}[0]{UI.RESET}  Exit"
        )

        UI.line("─")

        try:
            choice = input(
                f"\n  {UI.CYAN}TMHDPT {UI.RESET}› "
            ).strip()

        except (KeyboardInterrupt, EOFError):
            print()
            return

        if choice == "1":
            unpack_apk()
            pause()

        elif choice == "2":
            fix_apk()
            pause()

        elif choice == "3":
            merge_dex()
            pause()

        elif choice == "0":
            print()
            UI.success("DPT AUTO closed.")
            return

        else:
            UI.error("Invalid option.")
            pause()


# ============================================================
# ENTRY POINT
# ============================================================

def main():
    if sys.version_info < (3, 8):
        print("Python 3.8 or newer is required.")
        return

    # Automatically install/maintain Termux shortcut.
    installed = install_shortcut()

    if installed:
        UI.success("Termux command ready: tmhdpt")

    main_menu()


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print()
        UI.warning("Operation cancelled.")

    except Exception as exc:
        UI.error(f"Unexpected error: {exc}")
