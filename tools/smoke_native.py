"""Launch a packaged client in an isolated data root and inspect its native window."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


def x11_window(pid: int, environment: dict) -> list[str]:
    # Xlib inspection uses the isolated display, never the real desktop.
    script = r'''
import ctypes,json,os
lib=ctypes.CDLL('libX11.so.6')
lib.XOpenDisplay.argtypes=[ctypes.c_char_p];lib.XOpenDisplay.restype=ctypes.c_void_p
lib.XDefaultRootWindow.argtypes=[ctypes.c_void_p];lib.XDefaultRootWindow.restype=ctypes.c_ulong
lib.XQueryTree.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(ctypes.c_ulong),ctypes.POINTER(ctypes.c_ulong),ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),ctypes.POINTER(ctypes.c_uint)]
lib.XFetchName.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(ctypes.c_char_p)]
lib.XFree.argtypes=[ctypes.c_void_p]
lib.XCloseDisplay.argtypes=[ctypes.c_void_p]
display=lib.XOpenDisplay(os.environ['DISPLAY'].encode())
if not display:raise SystemExit(1)
found=[]
def walk(window,depth=0):
    title=ctypes.c_char_p()
    if lib.XFetchName(display,window,ctypes.byref(title)) and title.value:
        found.append(title.value.decode(errors='replace'));lib.XFree(title)
    root,parent=ctypes.c_ulong(),ctypes.c_ulong();children=ctypes.POINTER(ctypes.c_ulong)();count=ctypes.c_uint()
    if depth<3 and lib.XQueryTree(display,window,ctypes.byref(root),ctypes.byref(parent),ctypes.byref(children),ctypes.byref(count)):
        for i in range(count.value):walk(children[i],depth+1)
        if children:lib.XFree(children)
walk(lib.XDefaultRootWindow(display));lib.XCloseDisplay(display)
print(json.dumps(found))
'''
    response = subprocess.run([sys.executable, "-c", script], env=environment,
                              capture_output=True, text=True, check=True, timeout=5)
    return json.loads(response.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="smoke-results")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    candidates = list((ROOT / "build").rglob("Nimbus.app")) if sys.platform == "darwin" else list((ROOT / "build").rglob("Nimbus v*"))
    source = next((p for p in candidates if p.is_dir()), None)
    if source is None:
        raise SystemExit("Packaged application not found")
    desktop_sockets = {str(p): (p.stat().st_dev, p.stat().st_ino)
                       for p in (Path("/tmp/.X0-lock"), Path("/tmp/.X11-unix/X0")) if p.exists()}
    app = display = None
    with tempfile.TemporaryDirectory(prefix="nimbus-native-check-") as temporary:
        temporary = Path(temporary)
        directory = temporary / source.name
        shutil.copytree(source, directory)
        environment = os.environ.copy()
        environment.pop("NIMBUS_SERVER", None)
        environment.pop("WAYLAND_DISPLAY", None)
        environment.pop("DBUS_SESSION_BUS_ADDRESS", None)
        environment["HOME"] = str(temporary / "home")
        environment["XDG_CACHE_HOME"] = str(temporary / "cache")
        environment["XDG_CONFIG_HOME"] = str(temporary / "config")
        Path(environment["HOME"]).mkdir()
        port = free_port()
        binary = directory / "Contents/MacOS/Nimbus" if sys.platform == "darwin" else directory / "Nimbus"
        data_root = binary.parent
        (data_root / "config.json").write_text(json.dumps({"license_key": "", "phone_access": False,
            "proxy_enabled": False, "browser_profile": "chrome152", "port": port}), encoding="utf-8")
        try:
            if sys.platform != "darwin":
                number = next(n for n in range(99, 199) if not Path(f"/tmp/.X{n}-lock").exists() and not Path(f"/tmp/.X11-unix/X{n}").exists())
                authority = temporary / "xauthority"
                authority.touch(mode=0o600)
                environment.update(DISPLAY=f":{number}", XAUTHORITY=str(authority), GDK_BACKEND="x11",
                    WEBKIT_DISABLE_COMPOSITING_MODE="1", WEBKIT_DISABLE_DMABUF_RENDERER="1")
                display = subprocess.Popen(["Xvfb", f":{number}", "-screen", "0", "1280x900x24", "-nolisten", "tcp", "-auth", str(authority)],
                                           env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for _ in range(40):
                    if Path(f"/tmp/.X11-unix/X{number}").exists(): break
                    if display.poll() is not None: raise RuntimeError("Isolated display failed")
                    time.sleep(.1)
            with (output / "application.log").open("wb") as log:
                dom_report = output / "native-dom.json"
                app = subprocess.Popen([str(binary), str(port), "--check-ui", str(dom_report)], cwd=data_root, env=environment,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            deadline = time.monotonic() + 90
            release = None
            while time.monotonic() < deadline:
                if app.poll() is not None: raise RuntimeError("Native client exited")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/changelog", timeout=2) as response:
                        release = json.load(response)
                    break
                except OSError: time.sleep(.25)
            if not release: raise RuntimeError("Native client API did not start")
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
                assert response.status == 200
            window = False
            for _ in range(60):
                if sys.platform == "darwin":
                    import Quartz
                    windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
                    found = [w for w in windows if w.get('kCGWindowOwnerPID') == app.pid and w.get('kCGWindowLayer') == 0]
                    if found:
                        window = True
                        subprocess.run(["screencapture", "-x", "-l", str(found[0]['kCGWindowNumber']), str(output / "native-window.png")], check=True, timeout=5)
                        break
                else:
                    if "Nimbus" in x11_window(app.pid, environment):
                        window = True
                        screenshot = "import gi; gi.require_version('Gdk','3.0'); from gi.repository import Gdk; root=Gdk.get_default_root_window(); image=Gdk.pixbuf_get_from_window(root,0,0,1280,900); image.savev(" + repr(str(output / "native-window.png")) + ",'png',[],[])"
                        subprocess.run([sys.executable, "-c", screenshot], env=environment, check=True, timeout=10)
                        break
                time.sleep(.5)
            if not window: raise RuntimeError("Native window not found")
            # The toolkit creates its window before WebKit paints the page.
            # Wait for actual rendered pixels instead of accepting a black frame.
            from PIL import Image
            image_path = output / "native-window.png"
            rendered = False
            for _ in range(240):
                time.sleep(.25)
                if dom_report.exists():
                    checked = json.loads(dom_report.read_text(encoding="utf-8"))
                    if not checked.get("ok"):
                        raise RuntimeError("Native DOM failed: " + checked.get("error", "unknown"))
                if sys.platform == "darwin":
                    subprocess.run(["screencapture", "-x", "-l", str(found[0]['kCGWindowNumber']), str(image_path)], check=True, timeout=5)
                else:
                    subprocess.run([sys.executable, "-c", screenshot], env=environment, check=True, timeout=10)
                with Image.open(image_path) as image:
                    colors = image.convert("RGB").resize((160, 100)).getcolors(16000)
                    rendered = colors is None or len(colors) > 20
                if rendered:
                    break
            if not rendered and not dom_report.exists():
                raise RuntimeError("Native window stayed blank")
            deadline = time.monotonic() + 90
            while not dom_report.exists() and time.monotonic() < deadline:
                if app.poll() is not None:
                    break
                time.sleep(.25)
            if not dom_report.exists() or not json.loads(dom_report.read_text(encoding="utf-8")).get("ok"):
                raise RuntimeError("Native DOM verification failed")
            (output / "results.json").write_text(json.dumps({"nativeWindow": window,
                "renderedPixels": rendered, "release": release['version'], "api": True,
                "platform": sys.platform}), encoding="utf-8")
            print("Native package: API and window passed")
        finally:
            for process in (app, display):
                if process is not None and process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=15)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            assert all(Path(p).exists() and (Path(p).stat().st_dev, Path(p).stat().st_ino) == stat
                       for p, stat in desktop_sockets.items()), "Desktop display changed"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
