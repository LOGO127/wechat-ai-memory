from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from .base import SourceError
from .wechat4_crypto import PAGE_SIZE, verify_account_key


ProgressCallback = Callable[[int, int, str], None]


_SHA512_HOOK = r"""
let installed = false;

function install(module) {
if (installed) return;
installed = true;
const constants = Memory.scanSync(module.base, module.size, "22 ae 28 d7 98 2f 8a 42");
if (constants.length === 0) {
  send("ERROR:SHA-512 constants were not found");
  throw new Error("SHA-512 constants were not found");
}
const table = constants[0].address;
let reference = null;
for (const opcode of ["48 8d", "4c 8d"]) {
  for (const modrm of ["05", "0d", "15", "1d", "25", "2d", "35", "3d"]) {
    if (reference !== null) break;
    for (const result of Memory.scanSync(module.base, module.size, opcode + " " + modrm)) {
      const displacement = result.address.add(3).readS32();
      if (result.address.add(7).add(displacement).equals(table)) {
        reference = result.address;
        break;
      }
    }
  }
}
if (reference === null) {
  send("ERROR:SHA-512 code reference was not found");
  throw new Error("SHA-512 code reference was not found");
}

let entry = null;
for (let offset = 0; offset < 8192; offset++) {
  const address = reference.sub(offset);
  try {
    if (new Uint8Array(address.sub(1).readByteArray(1))[0] === 0xcc) {
      entry = address;
      break;
    }
  } catch (_) {}
}
if (entry === null) {
  send("ERROR:SHA-512 function entry was not found");
  throw new Error("SHA-512 function entry was not found");
}

function recoverKey(pointer, pad) {
  try {
    const block = new Uint8Array(pointer.readByteArray(128));
    for (let index = 32; index < 128; index++) {
      if (block[index] !== pad) return null;
    }
    let value = "";
    for (let index = 0; index < 32; index++) {
      value += ("0" + (block[index] ^ pad).toString(16)).slice(-2);
    }
    return value;
  } catch (_) {
    return null;
  }
}

const seen = {};
Interceptor.attach(entry, {
  onEnter() {
    const value = recoverKey(this.context.rdx, 0x36);
    if (value !== null && seen[value] === undefined) {
      seen[value] = true;
      send("KEY:" + value);
    }
  }
});
send("READY");
}

const loaded = Process.findModuleByName("Weixin.dll");
if (loaded !== null) {
  install(loaded);
} else {
  Process.attachModuleObserver({
    onAdded(module) {
      if (module.name.toLowerCase() === "weixin.dll") install(module);
    }
  });
}
"""


def capture_account_key(
    account_dir: Path,
    executable: Path | None = None,
    timeout: float = 300.0,
    progress: ProgressCallback | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> bytes:
    try:
        import frida
    except ImportError as exc:
        raise SourceError('WeChat access requires the optional "frida" package') from exc

    target = account_dir / "db_storage" / "message" / "message_0.db"
    if not target.is_file():
        raise SourceError(f"Cannot find the WeChat message database: {target}")
    with target.open("rb") as stream:
        first_page = stream.read(PAGE_SIZE)

    executable = executable or find_wechat_executable()
    _stop_wechat()
    if progress:
        progress(1, 4, "微信已关闭，正在准备安全读取")

    device = frida.get_local_device()
    deadline = time.monotonic() + timeout
    session = None
    attached_pid: int | None = None
    last_error: Exception | None = None
    subprocess.Popen([str(executable)], close_fds=True)
    while time.monotonic() < deadline and session is None:
        pid = _main_wechat_pid()
        if pid is None:
            time.sleep(0.04)
            continue
        try:
            session = device.attach(pid)
            attached_pid = pid
        except Exception as attach_error:  # Frida raises backend-specific attach errors.
            last_error = attach_error
            time.sleep(0.04)
    if session is None:
        detail = f": {last_error}" if last_error else ""
        raise SourceError(f"Could not attach while WeChat was starting{detail}")
    if progress:
        progress(2, 4, "已连接微信启动进程，正在定位数据库派生过程")

    found = threading.Event()
    ready = threading.Event()
    raw_key: bytes | None = None
    hook_error: str | None = None

    def on_message(message: dict, _data: object) -> None:
        nonlocal raw_key, hook_error
        if message.get("type") == "error":
            hook_error = str(message.get("description") or "Frida hook failed")
            ready.set()
            return
        payload = message.get("payload")
        if payload == "READY":
            ready.set()
            return
        if isinstance(payload, str) and payload.startswith("ERROR:"):
            hook_error = payload[6:]
            ready.set()
            return
        if not isinstance(payload, str) or not payload.startswith("KEY:"):
            return
        try:
            candidate = bytes.fromhex(payload[4:])
        except ValueError:
            return
        if verify_account_key(candidate, first_page):
            raw_key = candidate
            found.set()

    script = session.create_script(_SHA512_HOOK)
    script.on("message", on_message)
    try:
        script.load()
        if not ready.wait(min(15.0, timeout)):
            raise SourceError("Timed out while locating WeChat's database key derivation")
        if hook_error:
            raise SourceError(hook_error)
        needs_login = attached_pid is not None and _enter_remembered_account(attached_pid)
        if progress:
            label = "请在微信窗口扫码或确认登录" if needs_login else "正在验证本机账户数据库密钥"
            progress(3, 4, label)
        while not found.is_set() and time.monotonic() < deadline:
            if cancelled and cancelled():
                raise SourceError("连接已取消")
            found.wait(0.2)
        if raw_key is None:
            raise SourceError(
                "等待微信登录超时，未读取到数据库密钥。请重新连接，并在 5 分钟内完成扫码或手机确认。"
            )
    finally:
        try:
            script.unload()
        except Exception:
            pass
        try:
            session.detach()
        except Exception:
            pass

    if progress:
        progress(4, 4, "数据库密钥验证成功")
    return raw_key


def find_wechat_executable() -> Path:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_Process -Filter \"Name='Weixin.exe'\" | "
        "Sort-Object WorkingSetSize -Descending | Select-Object -First 1 -ExpandProperty ExecutablePath",
    ]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False)
    path = Path(result.stdout.strip()) if result.stdout.strip() else None
    if path and path.is_file():
        return path

    candidates = [
        Path(r"C:\Program Files\Tencent\Weixin\Weixin.exe"),
        Path(r"C:\Program Files (x86)\Tencent\Weixin\Weixin.exe"),
    ]
    for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        candidates.append(Path(f"{drive}:\\Weixin\\Weixin.exe"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SourceError("Cannot find Weixin.exe. Start WeChat once, then try again.")


def _stop_wechat() -> None:
    subprocess.run(
        ["taskkill", "/F", "/IM", "Weixin.exe"],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _main_wechat_pid(minimum_working_set=0) is None:
            return
        time.sleep(0.1)
    raise SourceError("WeChat did not close in time")


def _main_wechat_pid(minimum_working_set: int = 20 * 1024 * 1024) -> int | None:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-Process Weixin -ErrorAction SilentlyContinue | "
        f"Where-Object {{$_.WorkingSet64 -gt {minimum_working_set}}} | "
        "Sort-Object WorkingSet64 -Descending | Select-Object -First 1 -ExpandProperty Id",
    ]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False)
    value = result.stdout.strip()
    return int(value) if value.isdigit() else None


def _enter_remembered_account(pid: int) -> bool:
    if os.name != "nt":
        return False
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise SourceError('WeChat access requires the optional "pywinauto" package') from exc

    deadline = time.monotonic() + 20
    login_window_visible = False
    invoked = False
    last_invoke = 0.0
    while time.monotonic() < deadline:
        try:
            windows = Desktop(backend="uia").windows(process=pid, visible_only=True)
            has_login_window = False
            for window in windows:
                if "LoginWindow" in window.class_name():
                    login_window_visible = True
                    has_login_window = True
                buttons = window.descendants(control_type="Button")
                candidates = [
                    button
                    for button in buttons
                    if button.is_enabled() and button.rectangle().width() >= 140
                ]
                if not candidates:
                    continue
                now = time.monotonic()
                if now - last_invoke < 1.5:
                    continue
                target = max(candidates, key=lambda button: button.rectangle().width())
                try:
                    target.invoke()
                except Exception:
                    target.click_input()
                invoked = True
                last_invoke = now
            if invoked and not has_login_window:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return login_window_visible
