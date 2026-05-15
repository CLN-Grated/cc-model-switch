import json
import os
import subprocess
import sys

def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = get_app_dir()
PROFILES_DIR = os.path.join(APP_DIR, "profiles")
SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")

IS_WINDOWS = os.name == "nt"
IME_PREVIOUS_STATE = None
_paste_buf = ""

ENV_KEYS = [
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_REASONING_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
]


def load_profiles():
    profiles = []
    if not os.path.isdir(PROFILES_DIR):
        return profiles
    for f in sorted(os.listdir(PROFILES_DIR)):
        if f.endswith(".json"):
            path = os.path.join(PROFILES_DIR, f)
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                data["_file"] = f
                profiles.append(data)
    return profiles


def enter_alt_screen():
    sys.stdout.write("\033[?1049h\033[H")
    sys.stdout.flush()


def leave_alt_screen():
    sys.stdout.write("\033[?1049l")
    sys.stdout.flush()


def get_ime_api():
    import ctypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    imm32 = ctypes.WinDLL("imm32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    user32.SendMessageW.restype = ctypes.c_void_p
    imm32.ImmGetContext.argtypes = [ctypes.c_void_p]
    imm32.ImmGetContext.restype = ctypes.c_void_p
    imm32.ImmReleaseContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    imm32.ImmGetDefaultIMEWnd.argtypes = [ctypes.c_void_p]
    imm32.ImmGetDefaultIMEWnd.restype = ctypes.c_void_p
    imm32.ImmGetOpenStatus.argtypes = [ctypes.c_void_p]
    imm32.ImmGetOpenStatus.restype = ctypes.c_bool
    imm32.ImmSetOpenStatus.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    imm32.ImmGetConversionStatus.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong)]
    imm32.ImmSetConversionStatus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
    kernel32.GetConsoleWindow.restype = ctypes.c_void_p
    return ctypes, user32, imm32, kernel32


def get_ime_windows(ctypes, user32, kernel32):
    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("flags", ctypes.c_uint),
            ("hwndActive", ctypes.c_void_p),
            ("hwndFocus", ctypes.c_void_p),
            ("hwndCapture", ctypes.c_void_p),
            ("hwndMenuOwner", ctypes.c_void_p),
            ("hwndMoveSize", ctypes.c_void_p),
            ("hwndCaret", ctypes.c_void_p),
            ("rcCaret", ctypes.c_long * 4),
        ]

    hwnds = []
    foreground = user32.GetForegroundWindow()
    if foreground:
        hwnds.append(foreground)

    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(info)
    if user32.GetGUIThreadInfo(0, ctypes.byref(info)):
        for hwnd in (info.hwndFocus, info.hwndActive):
            if hwnd:
                hwnds.append(hwnd)

    console = kernel32.GetConsoleWindow()
    if console:
        hwnds.append(console)
    return list(dict.fromkeys(hwnds))


def use_ime_english_mode():
    global IME_PREVIOUS_STATE
    if not IS_WINDOWS:
        return
    try:
        ctypes, user32, imm32, kernel32 = get_ime_api()

        WM_IME_CONTROL = 0x0283
        IMC_GETCONVERSIONMODE = 0x0001
        IMC_SETCONVERSIONMODE = 0x0002
        IMC_GETOPENSTATUS = 0x0005
        IMC_SETOPENSTATUS = 0x0006
        IME_CMODE_NATIVE = 0x0001
        IME_CMODE_FULLSHAPE = 0x0008

        hwnds = get_ime_windows(ctypes, user32, kernel32)
        for hwnd in hwnds:
            himc = imm32.ImmGetContext(hwnd)
            if himc:
                conversion = ctypes.c_ulong()
                sentence = ctypes.c_ulong()
                try:
                    if IME_PREVIOUS_STATE is None and imm32.ImmGetConversionStatus(himc, ctypes.byref(conversion), ctypes.byref(sentence)):
                        IME_PREVIOUS_STATE = {
                            "open": bool(imm32.ImmGetOpenStatus(himc)),
                            "conversion": conversion.value,
                            "sentence": sentence.value,
                        }
                    imm32.ImmSetOpenStatus(himc, False)
                    if imm32.ImmGetConversionStatus(himc, ctypes.byref(conversion), ctypes.byref(sentence)):
                        conversion.value &= ~IME_CMODE_NATIVE
                        conversion.value &= ~IME_CMODE_FULLSHAPE
                        imm32.ImmSetConversionStatus(himc, conversion.value, sentence.value)
                finally:
                    imm32.ImmReleaseContext(hwnd, himc)

            ime_hwnd = imm32.ImmGetDefaultIMEWnd(hwnd)
            if not ime_hwnd:
                continue
            open_status = bool(user32.SendMessageW(ime_hwnd, WM_IME_CONTROL, IMC_GETOPENSTATUS, 0))
            conversion = int(user32.SendMessageW(ime_hwnd, WM_IME_CONTROL, IMC_GETCONVERSIONMODE, 0))
            if IME_PREVIOUS_STATE is None:
                IME_PREVIOUS_STATE = {"open": open_status, "conversion": conversion, "sentence": 0}
            user32.SendMessageW(ime_hwnd, WM_IME_CONTROL, IMC_SETOPENSTATUS, 0)
            conversion &= ~IME_CMODE_NATIVE
            conversion &= ~IME_CMODE_FULLSHAPE
            user32.SendMessageW(ime_hwnd, WM_IME_CONTROL, IMC_SETCONVERSIONMODE, conversion)
    except Exception:
        pass


def restore_ime_mode():
    if not IS_WINDOWS or IME_PREVIOUS_STATE is None:
        return
    try:
        ctypes, user32, imm32, kernel32 = get_ime_api()

        WM_IME_CONTROL = 0x0283
        IMC_SETCONVERSIONMODE = 0x0002
        IMC_SETOPENSTATUS = 0x0006

        for hwnd in get_ime_windows(ctypes, user32, kernel32):
            himc = imm32.ImmGetContext(hwnd)
            if himc:
                try:
                    imm32.ImmSetConversionStatus(himc, IME_PREVIOUS_STATE["conversion"], IME_PREVIOUS_STATE["sentence"])
                    imm32.ImmSetOpenStatus(himc, IME_PREVIOUS_STATE["open"])
                finally:
                    imm32.ImmReleaseContext(hwnd, himc)

            ime_hwnd = imm32.ImmGetDefaultIMEWnd(hwnd)
            if not ime_hwnd:
                continue
            user32.SendMessageW(ime_hwnd, WM_IME_CONTROL, IMC_SETCONVERSIONMODE, IME_PREVIOUS_STATE["conversion"])
            user32.SendMessageW(ime_hwnd, WM_IME_CONTROL, IMC_SETOPENSTATUS, int(IME_PREVIOUS_STATE["open"]))
    except Exception:
        pass


def draw_menu(profiles, index, current_index=None):
    use_ime_english_mode()
    sys.stdout.write("\033[H")
    sys.stdout.write("\033[96m═══ Claude Code 模型切换器 ═══\033[0m\n\n")

    if not profiles:
        sys.stdout.write("\033[90m暂无配置文件\033[0m\n")
        sys.stdout.write("\033[92m按 a 创建新配置文件\033[0m\n\n")
        sys.stdout.write("\033[36ma 新增  |  q 取消\033[0m\n")
        sys.stdout.write("\033[J")
        sys.stdout.flush()
        return

    height = os.get_terminal_size().lines if sys.stdout.isatty() else 24
    visible_count = max(1, (height - 5) // 4)
    start = max(0, min(index - visible_count // 2, len(profiles) - visible_count))
    end = min(len(profiles), start + visible_count)

    for i, p in enumerate(profiles[start:end], start):
        if i == index and i == current_index:
            marker = "\033[92m>\033[0m"
        elif i == index:
            marker = "\033[93m>\033[0m"
        else:
            marker = " "
        raw_name = p.get("name", "未命名")
        if i == current_index:
            name = "\033[92m" + raw_name + "\033[0m"
        elif i == index:
            name = "\033[93m" + raw_name + "\033[0m"
        else:
            name = raw_name
        fname = p.get("_file", "")
        sys.stdout.write(f"{marker} [{name}] \033[90m{fname}\033[0m\n")
        sys.stdout.write(f"  \033[90mURL: {p.get('ANTHROPIC_BASE_URL', '-')}\033[0m\n")
        sys.stdout.write(f"  \033[90m模型: {p.get('ANTHROPIC_MODEL', '-')}\033[0m\n\n")
    if len(profiles) > visible_count:
        sys.stdout.write(f"\033[90m显示 {start + 1}-{end} / {len(profiles)}\033[0m\n")
    sys.stdout.write("\033[36m↑ ↓ 切换  |  Enter 确认  |  a 新增  |  e 编辑  |  c 复制  |  q 取消  |  绿色为当前使用\033[0m\n")
    sys.stdout.write("\033[J")
    sys.stdout.flush()


def apply_profile(profile):
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    env = data.get("env", {})
    for key in ENV_KEYS:
        env.pop(key, None)
    for key in ENV_KEYS:
        if key in profile:
            env[key] = profile[key]
    data["env"] = env

    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def format_value(key, value):
    if value is None or value == "":
        return "-"
    if "TOKEN" in key or "KEY" in key:
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}...{value[-4:]}"
    return value


def confirm_profile(profile):
    sys.stdout.write("\033[H")
    print("\033[96m── 确认切换配置 ──\033[0m\n")
    print(f"  名称: {profile.get('name', '未知')}")
    print(f"  配置文件: {profile.get('_file', '-')}")
    print(f"  写入位置: {SETTINGS_PATH}")
    print("\n  将应用的环境变量:")
    for key in ENV_KEYS:
        print(f"    {key}: {format_value(key, profile.get(key))}")
    sys.stdout.write("\n  \033[90m按 Enter 确认切换，其他键取消\033[0m")
    sys.stdout.write("\033[J")
    sys.stdout.flush()
    return read_char() in ("\r", "\n")


def read_key():
    use_ime_english_mode()
    if IS_WINDOWS:
        import msvcrt
        first = msvcrt.getch()
        if first in (b"\x03",):
            return "ctrl-c"
        if first in (b"\r", b"\n"):
            return "enter"
        if first == b"q":
            return "quit"
        if first == b"c":
            return "copy"
        if first == b"e":
            return "edit"
        if first == b"a":
            return "add"
        if first == b"v":
            return "paste"
        if first == b"\x1b":
            return "quit"
        if first == b"\xe0":
            second = msvcrt.getch()
            if second == b"H":
                return "up"
            elif second == b"P":
                return "down"
        # Paste detection: JSON object start + chars arriving in batch
        if first == b"{" and msvcrt.kbhit():
            global _paste_buf
            buf = bytearray(first)
            while msvcrt.kbhit():
                buf.extend(msvcrt.getch())
            _paste_buf = buf.decode("utf-8", errors="replace")
            return "paste"
        return "unknown"
    else:
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                import select
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    seq = ch + sys.stdin.read(2)
                    if seq == "\x1b[A":
                        return "up"
                    elif seq == "\x1b[B":
                        return "down"
                return "quit"
            elif ch == "\r" or ch == "\n":
                return "enter"
            elif ch == "q":
                return "quit"
            elif ch == "c":
                return "copy"
            elif ch == "a":
                return "add"
            elif ch == "e":
                return "edit"
            elif ch == "v":
                return "paste"
            elif ch == "\x03":
                return "ctrl-c"
            return "unknown"
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_char():
    if IS_WINDOWS:
        import msvcrt
        ch = msvcrt.getch()
        if ch == b"\xe0":
            msvcrt.getch()
            return None
        if ch == b"\x03":
            raise KeyboardInterrupt
        try:
            return ch.decode("utf-8")
        except UnicodeDecodeError:
            return ch.decode("utf-8", errors="replace")
    else:
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                import select
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    seq = ch + sys.stdin.read(2)
                    if seq in ("\x1b[A", "\x1b[B"):
                        return None
                return "\x1b"
            if ch == "\x03":
                raise KeyboardInterrupt
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def prompt_input_esc(label, default=""):
    hint = f" [{default}]" if default else ""
    sys.stdout.write(f"  {label}{hint}: ")
    sys.stdout.flush()
    buf = ""
    while True:
        ch = read_char()
        if ch is None:
            continue
        if ch in ("\r", "\n"):
            break
        if ch == "\x1b":
            return None
        if ch in ("\x7f", "\x08"):
            if buf:
                buf = buf[:-1]
                sys.stdout.write("\b \b")
                sys.stdout.flush()
        else:
            buf += ch
            sys.stdout.write(ch)
            sys.stdout.flush()
    sys.stdout.write("\n")
    sys.stdout.flush()
    return buf if buf else default


def confirm_esc(prompt_text=""):
    if prompt_text:
        sys.stdout.write(prompt_text)
        sys.stdout.flush()
    ch = read_char()
    return ch in ("\r", "\n")


def create_profile():
    sys.stdout.write("\033[H")
    sys.stdout.write("\033[96m── 创建新配置文件 ──\033[0m\n\n")
    name = prompt_input_esc("名称")
    if not name:
        return None

    profile = {"name": name}
    model_val = ""
    for key in ENV_KEYS:
        default = model_val if model_val and key not in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN") else ""
        val = prompt_input_esc(key, default)
        if val is None:
            return None
        if val:
            profile[key] = val
        if key == "ANTHROPIC_MODEL" and val:
            model_val = val

    default_fname = name.lower().replace(" ", "-") + ".json"
    fname = prompt_input_esc("文件名", default_fname)
    if fname is None:
        return None
    if fname in (".", "..") or "/" in fname or "\\" in fname or fname != os.path.basename(fname):
        sys.stdout.write("\033[91m文件名不能包含路径或 ..\033[0m\n")
        sys.stdout.flush()
        return None
    if not fname.endswith(".json"):
        fname += ".json"

    path = os.path.join(PROFILES_DIR, fname)
    if os.path.exists(path):
        confirm = prompt_input_esc(f"{fname} 已存在，覆盖？(y/N)")
        if confirm is None or confirm.lower() != "y":
            return None

    os.makedirs(PROFILES_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return fname


def confirm_edit_profile(old_profile, new_profile, old_fname, new_fname):
    use_ime_english_mode()
    sys.stdout.write("\033[H")
    sys.stdout.write("\033[96m── 确认修改配置 ──\033[0m\n\n")

    changes = []
    old_name = old_profile.get("name", "")
    new_name = new_profile.get("name", "")
    if old_name != new_name:
        changes.append(("name", old_name, new_name))

    for key in ENV_KEYS:
        old_val = old_profile.get(key, "")
        new_val = new_profile.get(key, "")
        if old_val != new_val:
            changes.append(("env", key, old_val, new_val))

    fname_changed = old_fname != new_fname

    if not changes and not fname_changed:
        sys.stdout.write("  \033[90m未检测到变更\033[0m\n\n")
        sys.stdout.write("\033[J")
        sys.stdout.flush()
        return True

    for c in changes:
        if c[0] == "name":
            sys.stdout.write(f"  \033[93m名称:\033[0m {c[1]} \033[90m→\033[0m \033[92m{c[2]}\033[0m\n\n")

    env_changes = [c for c in changes if c[0] == "env"]
    if env_changes:
        sys.stdout.write(f"  \033[93m字段变更:\033[0m\n")
        for c in env_changes:
            _, key, old_val, new_val = c
            sys.stdout.write(f"    {key}:\n")
            sys.stdout.write(f"      \033[90m{format_value(key, old_val)}\033[0m \033[36m→\033[0m \033[92m{format_value(key, new_val)}\033[0m\n")
        sys.stdout.write("\n")

    if fname_changed:
        sys.stdout.write(f"  \033[93m文件名:\033[0m\n")
        sys.stdout.write(f"    \033[90m{old_fname}\033[0m \033[36m→\033[0m \033[94m{new_fname}\033[0m\n\n")

    sys.stdout.write("  \033[90m按 Enter 确认修改，Esc 取消\033[0m")
    sys.stdout.write("\033[J")
    sys.stdout.flush()
    return read_char() in ("\r", "\n")


def edit_profile(profile):
    sys.stdout.write("\033[H")
    sys.stdout.write("\033[96m── 编辑配置文件 ──\033[0m\n\n")

    old_fname = profile.get("_file", "")
    new_profile = {}

    name = prompt_input_esc("名称", profile.get("name", ""))
    if not name:
        return None
    new_profile["name"] = name

    model_val = ""
    for key in ENV_KEYS:
        default = profile.get(key, "")
        if model_val and key not in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"):
            default = model_val
        val = prompt_input_esc(key, default)
        if val is None:
            return None
        if val:
            new_profile[key] = val
        if key == "ANTHROPIC_MODEL" and val:
            model_val = val

    old_base = old_fname[:-5] if old_fname.endswith(".json") else old_fname
    fname = prompt_input_esc("文件名", old_base)
    if fname is None:
        return None
    if fname in (".", "..") or "/" in fname or "\\" in fname or fname != os.path.basename(fname):
        sys.stdout.write("\033[91m文件名不能包含路径或 ..\033[0m\n")
        sys.stdout.flush()
        return None
    if not fname.endswith(".json"):
        fname += ".json"
    if fname.lower() == old_fname.lower():
        fname = old_fname

    if not confirm_edit_profile(profile, new_profile, old_fname, fname):
        return None

    path = os.path.join(PROFILES_DIR, fname)
    if fname != old_fname and os.path.exists(path):
        confirm = prompt_input_esc(f"{fname} 已存在，覆盖？(y/N)")
        if confirm is None or confirm.lower() != "y":
            return None

    os.makedirs(PROFILES_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(new_profile, f, indent=2, ensure_ascii=False)
        f.write("\n")

    if fname != old_fname and old_fname:
        try:
            os.remove(os.path.join(PROFILES_DIR, old_fname))
        except OSError as e:
            sys.stdout.write(f"\033[93m警告: 旧文件删除失败: {e}\033[0m\n")
            sys.stdout.flush()

    return fname, old_fname


def export_profile(profile):
    use_ime_english_mode()
    sys.stdout.write("\033[H")
    sys.stdout.write("\033[96m── 导出配置文件 ──\033[0m\n\n")

    export_data = {k: v for k, v in profile.items() if k == "name" or k in ENV_KEYS}
    text = json.dumps(export_data, ensure_ascii=False, separators=(",", ":"))

    try:
        subprocess.run(["clip"], input=text, text=True, encoding="utf-8", check=True)
        sys.stdout.write("  \033[92m已复制到剪贴板\033[0m\n\n")
    except Exception:
        sys.stdout.write("  \033[93m剪贴板不可用，请手动复制:\033[0m\n\n")

    sys.stdout.write(f"  \033[90m{text}\033[0m\n\n")
    sys.stdout.write("\033[J")
    sys.stdout.write("  \033[36m按任意键返回菜单\033[0m")
    sys.stdout.flush()
    read_char()


def import_from_text(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        sys.stdout.write(f"\033[91mJSON 解析失败: {e}\033[0m\n")
        sys.stdout.flush()
        return None

    if not isinstance(data, dict):
        sys.stdout.write("\033[91m无效格式: 需要 JSON 对象\033[0m\n")
        sys.stdout.flush()
        return None

    name = data.get("name", "").strip()
    if not name:
        sys.stdout.write("\033[91m缺少 name 字段\033[0m\n")
        sys.stdout.flush()
        return None

    profile = {"name": name}
    has_env = False
    for key in ENV_KEYS:
        val = data.get(key)
        if val and isinstance(val, str) and val.strip():
            profile[key] = val.strip()
            has_env = True

    if not has_env:
        sys.stdout.write("\033[91m未检测到有效的环境变量字段\033[0m\n")
        sys.stdout.flush()
        return None

    sys.stdout.write("\033[H")
    sys.stdout.write("\033[96m── 导入配置文件 ──\033[0m\n\n")
    sys.stdout.write(f"  \033[93m名称:\033[0m {name}\n")
    for key in ENV_KEYS:
        if key in profile:
            sys.stdout.write(f"  \033[93m{key}:\033[0m {format_value(key, profile[key])}\n")
    sys.stdout.write("\n")
    sys.stdout.write("\033[J")
    sys.stdout.flush()

    default_fname = name.lower().replace(" ", "-") + ".json"
    fname = prompt_input_esc("文件名", default_fname)
    if fname is None:
        return None
    if fname in (".", "..") or "/" in fname or "\\" in fname or fname != os.path.basename(fname):
        sys.stdout.write("\033[91m文件名不能包含路径或 ..\033[0m\n")
        sys.stdout.flush()
        return None
    if not fname.endswith(".json"):
        fname += ".json"

    path = os.path.join(PROFILES_DIR, fname)
    if os.path.exists(path):
        confirm = prompt_input_esc(f"{fname} 已存在，覆盖？(y/N)")
        if confirm is None or confirm.lower() != "y":
            return None

    os.makedirs(PROFILES_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return fname


def main():
    profiles = load_profiles()

    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        current = json.load(f).get("env", {})

    keys = {"ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"}
    idx = 0
    current_idx = None
    for i, p in enumerate(profiles):
        if all(current.get(k) == p.get(k) for k in keys):
            idx = i
            current_idx = i
            break

    use_ime_english_mode()
    enter_alt_screen()
    draw_menu(profiles, idx, current_idx)

    while True:
        key = read_key()

        if key == "down":
            if not profiles:
                continue
            idx = (idx + 1) % len(profiles)
            draw_menu(profiles, idx, current_idx)
        elif key == "up":
            if not profiles:
                continue
            idx = (idx - 1 + len(profiles)) % len(profiles)
            draw_menu(profiles, idx, current_idx)
        elif key == "enter":
            if not profiles:
                continue
            profile = profiles[idx]
            if confirm_profile(profile):
                break
            draw_menu(profiles, idx, current_idx)
        elif key in ("ctrl-c", "quit"):
            restore_ime_mode()
            leave_alt_screen()
            sys.exit(0)
        elif key == "add":
            fname = create_profile()
            profiles = load_profiles()
            current_idx = next((i for i, p in enumerate(profiles) if all(current.get(k) == p.get(k) for k in keys)), None)
            if fname:
                idx = next((i for i, p in enumerate(profiles) if p.get("_file") == fname), 0)
            draw_menu(profiles, idx, current_idx)
        elif key == "edit":
            if not profiles:
                continue
            result = edit_profile(profiles[idx])
            if result is not None:
                new_fname, old_fname = result
                profiles = load_profiles()
                current_idx = next((i for i, p in enumerate(profiles) if all(current.get(k) == p.get(k) for k in keys)), None)
                idx = next((i for i, p in enumerate(profiles) if p.get("_file") == new_fname), 0)
            draw_menu(profiles, idx, current_idx)
        elif key == "copy":
            if not profiles:
                continue
            export_profile(profiles[idx])
            draw_menu(profiles, idx, current_idx)
        elif key == "paste":
            global _paste_buf
            if _paste_buf:
                result = import_from_text(_paste_buf)
                _paste_buf = ""
            else:
                try:
                    r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                                       capture_output=True, text=True, encoding="utf-8", timeout=5)
                    result = import_from_text(r.stdout.strip()) if r.returncode == 0 else None
                except Exception:
                    result = None
            if result is not None:
                profiles = load_profiles()
                current_idx = next((i for i, p in enumerate(profiles) if all(current.get(k) == p.get(k) for k in keys)), None)
                idx = next((i for i, p in enumerate(profiles) if p.get("_file") == result), 0)
            draw_menu(profiles, idx, current_idx)

    if not profiles:
        restore_ime_mode()
        leave_alt_screen()
        sys.exit(0)

    profile = profiles[idx]
    restore_ime_mode()
    leave_alt_screen()
    apply_profile(profile)
    print(f"\033[92m已切换到: {profile.get('name', '未知')}\033[0m")
    print(f"  \033[90m配置文件: {profile.get('_file', '-')}\033[0m")
    print(f"  \033[90m写入位置: {SETTINGS_PATH}\033[0m")
    print("  \033[90m已应用环境变量:\033[0m")
    for key in ENV_KEYS:
        print(f"    \033[90m{key}: {format_value(key, profile.get(key))}\033[0m")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        restore_ime_mode()
        leave_alt_screen()
        sys.exit(0)
