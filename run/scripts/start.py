

import ctypes
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

_STATE_DIR = Path(__file__).parent.parent.parent / ".run_state"
_SESSION_MODES = ("full", "main", "monitor", "impersonation")
_CELERY_HEALTHCHECK_INTERVAL_SECONDS = 15


def load_env() -> None:
    env_path = Path(__file__).parent.parent.parent / ".env"
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
    except ImportError:
        if env_path.exists():
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        os.environ[key.strip()] = value.strip()


_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def create_kill_on_close_job():
    if os.name != "nt":
        return None

    try:
        kernel32 = ctypes.windll.kernel32

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None

        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        ok = kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(job)
            return None

        return job
    except OSError:
        return None


def assign_to_job(job, proc: subprocess.Popen) -> None:
    if job is None:
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0001 | 0x0100, False, proc.pid)
        if not handle:
            return
        kernel32.AssignProcessToJobObject(job, handle)
        kernel32.CloseHandle(handle)
    except OSError:
        pass


def terminate_process(proc: subprocess.Popen | None, name: str) -> None:
    if not proc or proc.poll() is not None:
        return
    print(f"[Startup] Stopping {name} (PID: {proc.pid})")

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        return

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        print(f"[Startup] Force killing {name} (PID: {proc.pid})")
        proc.kill()


def is_pid_alive(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
        )
        return str(pid) in result.stdout

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def kill_pid(pid: int, name: str) -> None:
    print(f"[Startup] Stopping {name} (PID: {pid})")
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def _state_path(mode: str) -> Path:
    return _STATE_DIR / f"{mode}.json"


def read_state(mode: str) -> dict | None:
    path = _state_path(mode)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_state(mode: str, pids: dict) -> None:
    _STATE_DIR.mkdir(exist_ok=True)
    _state_path(mode).write_text(json.dumps(pids), encoding="utf-8")


def delete_state(mode: str) -> None:
    try:
        _state_path(mode).unlink()
    except FileNotFoundError:
        pass


def active_session(mode: str) -> dict | None:
    state = read_state(mode)
    if not state:
        return None
    if any(pid and is_pid_alive(pid) for pid in state.values()):
        return state
    delete_state(mode)
    return None


def stop_session(mode: str) -> bool:
    state = read_state(mode)
    if not state:
        return False
    stopped = False
    for role, pid in state.items():
        if pid and is_pid_alive(pid):
            kill_pid(pid, f"{mode}:{role}")
            stopped = True
    delete_state(mode)
    return stopped


def _celery_state_path() -> Path:
    return _STATE_DIR / "celery.json"


def read_celery_state() -> dict | None:
    path = _celery_state_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_celery_state(state: dict) -> None:
    _STATE_DIR.mkdir(exist_ok=True)
    _celery_state_path().write_text(json.dumps(state), encoding="utf-8")


def delete_celery_state() -> None:
    try:
        _celery_state_path().unlink()
    except FileNotFoundError:
        pass


def acquire_celery(mode: str, worker_cmd: list, beat_cmd: list, env: dict) -> tuple[int, int]:
    state = read_celery_state()
    if state and state.get("worker") and state.get("beat") \
            and is_pid_alive(state["worker"]) and is_pid_alive(state["beat"]):
        sessions = sorted(set(state.get("sessions", [])) | {mode})
        write_celery_state({**state, "sessions": sessions})
        print(f"[Startup] Reusing existing Celery worker (PID: {state['worker']}) "
              f"and beat (PID: {state['beat']}).")
        return state["worker"], state["beat"]

    print("[Startup] Launching Celery worker...")
    worker_proc = subprocess.Popen(worker_cmd, env=env)
    print(f"[Startup] Celery worker started (PID: {worker_proc.pid})")

    print("[Startup] Launching Celery beat scheduler...")
    beat_proc = subprocess.Popen(beat_cmd, env=env)
    print(f"[Startup] Celery beat started (PID: {beat_proc.pid})")

    write_celery_state({"worker": worker_proc.pid, "beat": beat_proc.pid, "sessions": [mode]})
    return worker_proc.pid, beat_proc.pid


def release_celery(mode: str) -> None:
    state = read_celery_state()
    if not state:
        return

    sessions = [session for session in state.get("sessions", []) if session != mode]
    if sessions:
        write_celery_state({**state, "sessions": sessions})
        return

    if state.get("worker") and is_pid_alive(state["worker"]):
        kill_pid(state["worker"], "Celery worker")
    if state.get("beat") and is_pid_alive(state["beat"]):
        kill_pid(state["beat"], "Celery beat")
    delete_celery_state()


def ensure_celery_alive(mode: str, worker_cmd: list, beat_cmd: list, env: dict) -> None:
    state = read_celery_state()
    if not state or mode not in state.get("sessions", []):
        return

    if (state.get("worker") and is_pid_alive(state["worker"])) and \
            (state.get("beat") and is_pid_alive(state["beat"])):
        return

    state = read_celery_state()
    if not state or mode not in state.get("sessions", []):
        return

    if not (state.get("worker") and is_pid_alive(state["worker"])):
        print("[Startup] WARNING: Celery worker died unexpectedly - restarting it.")
        worker_proc = subprocess.Popen(worker_cmd, env=env)
        state["worker"] = worker_proc.pid
        print(f"[Startup] Celery worker restarted (PID: {worker_proc.pid})")

    if not (state.get("beat") and is_pid_alive(state["beat"])):
        print("[Startup] WARNING: Celery beat died unexpectedly - restarting it.")
        beat_proc = subprocess.Popen(beat_cmd, env=env)
        state["beat"] = beat_proc.pid
        print(f"[Startup] Celery beat restarted (PID: {beat_proc.pid})")

    write_celery_state(state)


def celery_watchdog_loop(mode: str, worker_cmd: list, beat_cmd: list, env: dict, stop_event: threading.Event) -> None:
    while not stop_event.wait(_CELERY_HEALTHCHECK_INTERVAL_SECONDS):
        ensure_celery_alive(mode, worker_cmd, beat_cmd, env)


def check_conflict(mode: str) -> bool:
    if mode == "full":
        for other in ("main", "monitor", "impersonation"):
            if active_session(other):
                print(f"[Startup] ERROR: Cannot start the full application because '{other}' is already running.")
                print("[Startup] Stop the existing process first, or use --force.")
                return True
        return False

    if active_session("full"):
        print(f"[Startup] ERROR: Cannot start '{mode}' because the full application is already running.")
        print("[Startup] Stop the existing process first, or use --force.")
        return True

    if active_session(mode):
        print(f"[Startup] ERROR: '{mode}' is already running.")
        print("[Startup] Stop the existing process first, or use --force.")
        return True

    return False


def print_usage() -> None:
    print("Usage: python -m run start [main|monitor|impersonation] [--no-reload] [-f|--force]")
    print()
    print("  (no mode)    Run everything: Celery worker, Celery beat, the")
    print("               monitor service, the main app server, and the")
    print("               dedicated impersonation worker - mirrors running")
    print("               every service in docker-compose.yml at once.")
    print("  main         Run only the main app server (+ worker/beat).")
    print("  monitor      Run only the monitor service (+ worker/beat).")
    print("  impersonation")
    print("               Run only the dedicated impersonation worker")
    print("               (+ worker/beat) - a single uvicorn process (no")
    print("               --workers/--reload-based multiprocessing) with")
    print("               IMPERSONATION_WORKER=1 set for only that process,")
    print("               mirroring the impersonation-worker service in")
    print("               docker-compose.yml. Runs on IMPERSONATION_PORT")
    print("               (default 8010). .env is never modified.")
    print()
    print("  main, monitor, and impersonation are narrower alternatives to the")
    print("  full app (no mode), for when you only need that one piece - they")
    print("  can run at the same time as each other in separate terminals,")
    print("  sharing one Celery worker/beat pair with each other and with the")
    print("  full app, torn down once no session needs it anymore. None of")
    print("  them can run at the same time as the full application (no mode),")
    print("  since the full app already includes all three.")
    print()
    print("  --no-reload   Disable uvicorn's auto-reload on file changes.")
    print("  -f, --force   Stop every existing session (main, monitor, full,")
    print("                worker, beat) first, then run the requested command.")


def main() -> int:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print_usage()
        return 0

    load_env()

    no_reload = "--no-reload" in args

    only_main = "main" in args
    only_monitor = "monitor" in args
    only_impersonate = "impersonation" in args
    if sum([only_main, only_monitor, only_impersonate]) > 1:
        print("[Startup] ERROR: pass at most one of 'main', 'monitor', or 'impersonation' - omit all to run everything.")
        return 1
    run_app = not only_monitor and not only_impersonate
    run_monitor = not only_main and not only_impersonate
    run_impersonate = not only_main and not only_monitor
    mode = "main" if only_main else "monitor" if only_monitor else "impersonation" if only_impersonate else "full"

    force = "-f" in args or "--force" in args
    if force:
        print("[Startup] --force: stopping all existing sessions first...")
        stopped_any = False
        for session_mode in _SESSION_MODES:
            if stop_session(session_mode):
                stopped_any = True

        celery_state = read_celery_state()
        if celery_state:
            for role in ("worker", "beat"):
                pid = celery_state.get(role)
                if pid and is_pid_alive(pid):
                    kill_pid(pid, f"Celery {role}")
                    stopped_any = True
            delete_celery_state()

        if stopped_any:
            time.sleep(1)
        else:
            print("[Startup] Nothing was running.")

    if check_conflict(mode):
        return 1

    port = os.getenv("PORT", "8000")
    host = os.getenv("HOST", "0.0.0.0")
    monitor_port = os.getenv("MONITOR_PORT", "8001")
    impersonation_port = os.getenv("IMPERSONATION_PORT", "8010")

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")

    worker_concurrency = os.getenv("CELERY_WORKER_CONCURRENCY", "2")

    worker_cmd = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "apps.app.celery_app",
        "worker",
        "--loglevel=info",
    ]
    if os.name == "nt":
        worker_cmd += ["--pool=threads", f"--concurrency={worker_concurrency}"]
    else:
        worker_cmd.append(f"--concurrency={worker_concurrency}")

    beat_cmd = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "apps.app.celery_app",
        "beat",
        "--loglevel=info",
    ]

    monitor_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "apps.monitor.main:app",
        *([] if no_reload else ["--reload", "--reload-dir", "apps"]),
        "--host",
        host,
        "--port",
        monitor_port,
        "--forwarded-allow-ips=",
    ]

    app_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "apps.app.main:app",
        *([] if no_reload else ["--reload", "--reload-dir", "apps/app"]),
        "--host",
        host,
        "--port",
        port,
    ]

    impersonation_env = env.copy()
    impersonation_env["IMPERSONATION_WORKER"] = "1"

    impersonation_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "apps.app.main:app",
        *([] if no_reload else ["--reload", "--reload-dir", "apps/app"]),
        "--host",
        host,
        "--port",
        impersonation_port,
    ]

    if no_reload:
        print("[Startup] --no-reload: app/monitor will not auto-reload on file changes.")

    job = create_kill_on_close_job()
    if os.name == "nt" and job is None:
        print("[Startup] WARNING: could not create a Windows job object - "
              "if this process ends abnormally, monitor/app may be left "
              "running instead of being cleaned up automatically.")

    monitor_proc = None
    app_proc = None
    impersonation_proc = None
    celery_watchdog_stop = threading.Event()
    celery_watchdog_thread = None
    try:
        acquire_celery(mode, worker_cmd, beat_cmd, env)

        celery_watchdog_thread = threading.Thread(
            target=celery_watchdog_loop,
            args=(mode, worker_cmd, beat_cmd, env, celery_watchdog_stop),
            daemon=True,
        )
        celery_watchdog_thread.start()

        if run_monitor:
            print(f"[Startup] Launching monitor service on http://{host}:{monitor_port}...")
            monitor_proc = subprocess.Popen(monitor_cmd, env=env)
            assign_to_job(job, monitor_proc)
            print(f"[Startup] Monitor service started (PID: {monitor_proc.pid})")
        else:
            print("[Startup] Skipping monitor service.")

        if run_impersonate:
            print(f"[Startup] Launching impersonation worker (single process, "
                  f"IMPERSONATION_WORKER=1) on http://{host}:{impersonation_port}...")
            impersonation_proc = subprocess.Popen(impersonation_cmd, env=impersonation_env)
            assign_to_job(job, impersonation_proc)
            print(f"[Startup] Impersonation worker started (PID: {impersonation_proc.pid})")
        else:
            print("[Startup] Skipping impersonation worker.")

        if run_app:
            print(f"[Startup] Starting server on http://{host}:{port}")
            app_proc = subprocess.Popen(app_cmd, env=env)
            assign_to_job(job, app_proc)

            pids = {"main": app_proc.pid}
            if monitor_proc is not None:
                pids["monitor"] = monitor_proc.pid
            if impersonation_proc is not None:
                pids["impersonation"] = impersonation_proc.pid
            write_state(mode, pids)

            return app_proc.wait()

        if run_impersonate:
            write_state(mode, {"impersonation": impersonation_proc.pid})
            return impersonation_proc.wait()

        print("[Startup] Skipping main app server ('monitor' mode).")
        write_state(mode, {"monitor": monitor_proc.pid})
        return monitor_proc.wait()
    finally:
        celery_watchdog_stop.set()
        if celery_watchdog_thread is not None:
            celery_watchdog_thread.join(timeout=5)
        terminate_process(app_proc, "App server")
        terminate_process(monitor_proc, "Monitor service")
        terminate_process(impersonation_proc, "Impersonation worker")
        release_celery(mode)
        delete_state(mode)
        if job is not None:
            ctypes.windll.kernel32.CloseHandle(job)


if __name__ == "__main__":
    sys.exit(main())
