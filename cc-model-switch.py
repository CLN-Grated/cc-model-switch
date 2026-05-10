"""Claude Code 模型切换器 - 用方向键切换预设配置"""

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILES_DIR = os.path.join(SCRIPT_DIR, "profiles")
SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")

IS_WINDOWS = os.name == "nt"
IME_PREVIOUS_STATE = None

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
    os.makedirs(PROFILES_DIR, exist_ok=True)
    profiles = []
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
    sys.stdout.write("\033[H\033[J")
    sys.stdout.write("\033[96m═══ Claude Code 模型切换器 ═══\033[0m\n\n")

    if not profiles:
        sys.stdout.write("\033[90m暂无配置文件\033[0m\n")
        sys.stdout.write("\033[92m按 a 创建新配置文件\033[0m\n\n")
        sys.stdout.write("\033[36ma 创建新配置文件  |  Ctrl+C / q 取消\033[0m\n")
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
    sys.stdout.write("\033[36m↑ ↓ 切换  |  Enter 确认  |  a 创建新配置文件  |  Ctrl+C / q 取消  |  绿色为当前使用\033[0m\n")
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
    sys.stdout.write("\033[H\033[J")
    print("\033[96m── 确认切换配置 ──\033[0m\n")
    print(f"  名称: {profile.get('name', '未知')}")
    print(f"  配置文件: {profile.get('_file', '-')}")
    print(f"  写入位置: {SETTINGS_PATH}")
    print("\n  将应用的环境变量:")
    for key in ENV_KEYS:
        print(f"    {key}: {format_value(key, profile.get(key))}")
    print()
    confirm = input("  按 Enter 确认切换，输入其他内容返回菜单: ")
    return confirm == ""


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
        if first == b"a":
            return "add"
        if first == b"\xe0":
            second = msvcrt.getch()
            if second == b"H":
                return "up"
            elif second == b"P":
                return "down"
        return "unknown"
    else:
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = ch + sys.stdin.read(2)
                if seq == "\x1b[A":
                    return "up"
                elif seq == "\x1b[B":
                    return "down"
                return "unknown"
            elif ch == "\r" or ch == "\n":
                return "enter"
            elif ch == "q":
                return "quit"
            elif ch == "a":
                return "add"
            elif ch == "\x03":
                return "ctrl-c"
            return "unknown"
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def prompt_input(label, default=""):
    hint = f" [{default}]" if default else ""
    val = input(f"  {label}{hint}: ").strip()
    return val if val else default


def create_profile():
    sys.stdout.write("\033[H\033[J")
    sys.stdout.write("\033[96m── 创建新配置文件 ──\033[0m\n\n")
    name = prompt_input("名称")
    if not name:
        sys.stdout.write("\033[91m名称不能为空\033[0m\n")
        sys.stdout.flush()
        return None

    profile = {"name": name}
    model_val = ""
    for key in ENV_KEYS:
        default = model_val if model_val and key not in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN") else ""
        val = prompt_input(key, default)
        if val:
            profile[key] = val
        if key == "ANTHROPIC_MODEL" and val:
            model_val = val

    default_fname = name.lower().replace(" ", "-") + ".json"
    fname = prompt_input("文件名", default_fname)
    if fname in (".", "..") or "/" in fname or "\\" in fname or fname != os.path.basename(fname):
        sys.stdout.write("\033[91m文件名不能包含路径或 ..\033[0m\n")
        sys.stdout.flush()
        return None
    if not fname.endswith(".json"):
        fname += ".json"

    path = os.path.join(PROFILES_DIR, fname)
    if os.path.exists(path):
        confirm = prompt_input(f"{fname} 已存在，覆盖？(y/N)").lower()
        if confirm != "y":
            return None

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
