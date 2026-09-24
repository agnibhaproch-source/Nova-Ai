"""Sandbox harness (docs/24 §3).

Protocol: the runner writes one JSON object to stdin
    {"code": str, "timeout_seconds": int, "files": [{"name": str, "content_b64": str}]}
The harness writes main.py (+ input/) to the /work tmpfs, runs it with runpy under an alarm,
captures fd-level stdout/stderr to files, and prints ONE JSON result line to the real stdout:
    {"exit_code", "stdout", "stderr", "timed_out", "truncated", "images": [{name, content_b64}]}
If the process is killed (OOM, hard timeout) no result line is printed; the runner falls back.
"""

import base64
import glob
import json
import os
import runpy
import signal
import sys
import traceback

WORK = "/work"
OUT = f"{WORK}/out"
CAP = 64 * 1024
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 1024 * 1024


class _Timeout(BaseException):
    pass


def _alarm(*_: object) -> None:
    raise _Timeout


def _install_show_shim() -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return
    count = {"n": 0}

    def show(*_a: object, **_k: object) -> None:
        for num in plt.get_fignums():
            if count["n"] >= MAX_IMAGES:
                break
            count["n"] += 1
            plt.figure(num).savefig(f"{OUT}/figure{count['n']}.png", dpi=100, bbox_inches="tight")
        plt.close("all")

    plt.show = show


def _read_capped(path: str) -> tuple[str, bool]:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            data = f.read(CAP)
    except OSError:
        return "", False
    text = data.decode(errors="replace")
    return (text + "\n[output truncated]", True) if size > CAP else (text, False)


def main() -> int:
    payload = json.loads(sys.stdin.buffer.readline() or b"{}")
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(f"{WORK}/input", exist_ok=True)
    with open(f"{WORK}/main.py", "w") as f:
        f.write(payload.get("code", ""))
    for item in payload.get("files", []):
        name = os.path.basename(item["name"])
        with open(f"{WORK}/input/{name}", "wb") as f:
            f.write(base64.b64decode(item["content_b64"]))

    real_stdout = os.dup(1)
    out_fd = os.open(f"{WORK}/.stdout", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    err_fd = os.open(f"{WORK}/.stderr", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.dup2(out_fd, 1)
    os.dup2(err_fd, 2)
    sys.stdin = open(os.devnull)  # noqa: SIM115

    exit_code, timed_out = 0, False
    _install_show_shim()
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(int(payload.get("timeout_seconds", 10)))
    sys.argv = ["main.py"]
    sys.path.insert(0, WORK)
    os.chdir(WORK)
    try:
        runpy.run_path(f"{WORK}/main.py", run_name="__main__")
    except _Timeout:
        timed_out, exit_code = True, 124
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException:
        lines = traceback.format_exc().splitlines()
        print("\n".join(ln for ln in lines if "/opt/runner/" not in ln), file=sys.stderr)
        exit_code = 1
    finally:
        signal.alarm(0)
    try:
        import matplotlib.pyplot as plt

        if plt.get_fignums() and not timed_out:
            plt.show()
    except Exception:
        pass
    sys.stdout.flush()
    sys.stderr.flush()

    stdout, t1 = _read_capped(f"{WORK}/.stdout")
    stderr, t2 = _read_capped(f"{WORK}/.stderr")
    images = []
    for path in sorted(glob.glob(f"{OUT}/*.png"))[:MAX_IMAGES]:
        if os.path.getsize(path) <= MAX_IMAGE_BYTES:
            with open(path, "rb") as f:
                images.append(
                    {"name": os.path.basename(path), "content_b64": base64.b64encode(f.read()).decode()}
                )
    result = {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "truncated": t1 or t2,
        "images": images,
    }
    os.write(real_stdout, ("\n" + json.dumps(result) + "\n").encode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
