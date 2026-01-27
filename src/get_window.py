import time
import platform
import os
import subprocess
import json
import sys

this_os = platform.system()

# --- Platform Specific Imports ---
if this_os == 'Windows':
    import ctypes
    import ctwin32
    import ctwin32.ntdll
    import ctwin32.user
    import pygetwindow as gw
elif this_os == 'Darwin':
    from AppKit import NSWorkspace
    import Quartz
elif this_os == 'Linux':
    import psutil
    # Try to import X11 libraries safely; they might not exist on a pure Wayland setup
    try:
        from ewmh import EWMH
        import Xlib.display
        # Only initialize X11 atoms if we can connect to a display
        try:
            _disp = Xlib.display.Display()
            NET_WM_NAME = _disp.intern_atom('_NET_WM_NAME')
        except:
            NET_WM_NAME = None
            EWMH = None
    except ImportError:
        EWMH = None
        NET_WM_NAME = None


# --- Helper: Check for Wayland ---
def is_wayland():
    return os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland'


# --- Main Public Functions ---

def get_active_window():
    if this_os == 'Windows':
        return win_get_active_window()
    elif this_os == 'Darwin':
        return darwin_get_active_window()
    elif this_os == 'Linux':
        if is_wayland():
            return linux_wayland_get_active_window()
        return linux_x11_get_active_window()
    raise NotImplementedError(f'Platform {this_os} not supported')

def get_list_of_all_windows():
    if this_os == 'Windows':
        return win_get_list_of_all_windows()
    elif this_os == 'Darwin':
        return darwin_get_list_of_all_windows()
    elif this_os == 'Linux':
        if is_wayland():
            return linux_wayland_get_list_of_all_windows()
        return linux_x11_get_list_of_all_windows()
    raise NotImplementedError(f'Platform {this_os} not supported')


# --- Linux Wayland Implementation ---

def _run_cmd(cmd):
    """Helper to run shell commands and return output string."""
    try:
        return subprocess.check_output(cmd, shell=True, text=True).strip()
    except subprocess.CalledProcessError:
        return None

def linux_wayland_get_active_window():
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').upper()
    
    # GNOME Support (via gdbus)
    if 'GNOME' in desktop:
        # Note: newer GNOME versions might restrict 'Eval' for security.
        cmd = """
        gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval "
            var w = global.display.focus_window;
            if (w) {
                JSON.stringify({app: w.get_wm_class(), title: w.get_title()});
            } else {
                JSON.stringify({app: '', title: ''});
            }
        "
        """
        output = _run_cmd(cmd)
        if output:
            try:
                # Output format is (true, '{"app":...}')
                json_str = output.split("'", 1)[1].rsplit("'", 1)[0]
                json_str = json_str.replace('\\"', '"') # Cleanup escaped quotes
                data = json.loads(json_str)
                return (data.get('app', 'Unknown'), data.get('title', 'Unknown'))
            except:
                pass

    # KDE Plasma Support (via qdbus)
    elif 'KDE' in desktop:
        # Get Active Window ID
        win_id = _run_cmd("qdbus org.kde.KWin /KWin org.kde.KWin.activeWindow")
        if win_id:
            # Get Info for ID
            info = _run_cmd(f"qdbus org.kde.KWin /KWin queryWindowInfo {win_id}")
            if info:
                info_map = {}
                for line in info.split('\n'):
                    if ':' in line:
                        key, val = line.split(':', 1)
                        info_map[key.strip()] = val.strip()
                return (info_map.get('resourceClass', 'Unknown'), info_map.get('caption', 'Unknown'))

    return ('Unknown (Wayland)', 'Wayland Active Window Detection Failed')


def linux_wayland_get_list_of_all_windows():
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').upper()
    ret = set()

    # GNOME Support
    if 'GNOME' in desktop:
        cmd = """
        gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval "
            var wins = global.display.get_tab_list(0, null);
            var res = [];
            wins.forEach(function(w) {
                res.push({app: w.get_wm_class(), title: w.get_title()});
            });
            JSON.stringify(res);
        "
        """
        output = _run_cmd(cmd)
        if output:
            try:
                # Parse: (true, '[{...}, {...}]')
                json_str = output.split("'", 1)[1].rsplit("'", 1)[0]
                json_str = json_str.replace('\\"', '"')
                data = json.loads(json_str)
                for item in data:
                    ret.add((item.get('app', 'Unknown'), item.get('title', 'Unknown')))
            except:
                pass
    
    # KDE Support
    elif 'KDE' in desktop:
        # KDE doesn't have a simple 'list all' via qdbus without a helper script.
        # Returning active window as a fallback to avoid crash/empty
        active = linux_wayland_get_active_window()
        if active[0] != 'Unknown (Wayland)':
            ret.add(active)
            
    if not ret:
        ret.add(('Unknown', 'Wayland: List Windows Not Fully Supported'))
        
    return ret


# --- Linux X11 Implementation (Original Logic) ---

def linux_x11_get_list_of_all_windows():
    if not EWMH:
        return {('Error', 'Missing X11 libs (ewmh)')}
        
    ret = set()
    ewmh = EWMH()
    for window in ewmh.getClientList():
        try:
            win_pid = ewmh.getWmPid(window)
        except TypeError:
            win_pid = False
        if win_pid:
            try:
                app = psutil.Process(win_pid).name()
            except psutil.NoSuchProcess:
                app = 'Unknown'
        else:
            app = 'Unknown'
        wm_name = window.get_wm_name()
        if not wm_name and NET_WM_NAME:
            try:
                wm_name = window.get_full_property(NET_WM_NAME, 0).value
            except:
                pass
        if not wm_name:
            try:
                wm_name = f'class:{window.get_wm_class()[0]}'
            except:
                wm_name = 'Unknown'
        if isinstance(wm_name, bytes):
            wm_name = wm_name.decode('utf-8', errors='ignore')
        ret.add((app, wm_name))
    return ret

def linux_x11_get_active_window():
    if not EWMH:
        return ('Error', 'Missing X11 libs (ewmh)')

    ewmh = EWMH()
    active_window = ewmh.getActiveWindow()
    if not active_window:
        return '', ''
    try:
        win_pid = ewmh.getWmPid(active_window)
    except (TypeError, Xlib.error.XResourceError):
        win_pid = False
        
    wm_name = active_window.get_wm_name()
    if not wm_name and NET_WM_NAME:
        try:
            wm_name = active_window.get_full_property(NET_WM_NAME, 0).value
        except:
            pass
    if not wm_name:
        try:
            wm_name = f'class:{active_window.get_wm_class()[0]}'
        except:
            wm_name = 'Unknown'
            
    if isinstance(wm_name, bytes):
        wm_name = wm_name.decode('utf-8', errors='ignore')
        
    if win_pid:
        try:
            active_app = psutil.Process(win_pid).name()
        except psutil.NoSuchProcess:
            active_app = 'Unknown'
    else:
        return '', wm_name
    return (active_app, wm_name)


# --- MacOS Implementation (Unchanged) ---

def darwin_get_active_window():
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListExcludeDesktopElements | Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
    for window in windows:
        if window[Quartz.kCGWindowLayer] == 0:
            return window[Quartz.kCGWindowOwnerName], window.get(Quartz.kCGWindowName, 'unknown')
    return '', ''

def darwin_get_list_of_all_windows():
    apps = []
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListExcludeDesktopElements | Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)

    for window in windows:
        apps.append((window[Quartz.kCGWindowOwnerName],
                    window.get(Quartz.kCGWindowName, 'unknown')))
    apps = list(set(apps))
    apps = sorted(apps, key=lambda x: x[0])
    return apps


# --- Windows Implementation (Unchanged) ---

def win_get_app_name(hwnd):
    """Get application name given hwnd."""
    try:
        _, pid = ctwin32.user.GetWindowThreadProcessId(hwnd)
        spii = ctwin32.ntdll.SYSTEM_PROCESS_ID_INFORMATION()
        buffer = ctypes.create_unicode_buffer(0x1000)
        spii.ProcessId = pid
        spii.ImageName.MaximumLength = len(buffer)
        spii.ImageName.Buffer = ctypes.addressof(buffer)
        ctwin32.ntdll.NtQuerySystemInformation(ctwin32.SystemProcessIdInformation, ctypes.byref(spii), ctypes.sizeof(spii), None)
        name = str(spii.ImageName)
        dot = name.rfind('.')
        slash = name.rfind('\\')
        exe = name[slash+1:dot]
    except:
        return 'unknown'
    else:
        return exe

def win_get_list_of_all_windows():
    ret = set()
    for item in gw.getAllWindows():
        ret.add((win_get_app_name(item._hWnd), item.title))
    ret = sorted(list(ret), key=lambda x: x[0])
    return ret

def win_get_active_window():
    active_window = gw.getActiveWindow()
    if active_window is None:
        return '', ''
    return (win_get_app_name(active_window._hWnd), active_window.title)


# --- Main ---

if __name__ == "__main__":
    print("\n----- All Windows -----\n")
    try:
        for item in get_list_of_all_windows():
            print(item)
    except Exception as e:
        print(f"Error listing windows: {e}")

    print("\n----- Current Window -----\n")
    try:
        print(get_active_window())
    except Exception as e:
        print(f"Error getting active window: {e}")