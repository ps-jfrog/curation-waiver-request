#!/usr/bin/env python3
import os, sys, time, re, shlex, datetime, select, pty, fcntl, termios, struct

# --- Config (override via env) ---
JF_CMD = os.environ.get("JF_CMD", "jf")
REQ_FILE = os.environ.get("REQ_FILE", "requirements.txt")
REPO_RESOLVE = os.environ.get("RT_REPO_REMOTE", "curation-blocked-py-virtual")
LOG_LEVEL = os.environ.get("JFROG_CLI_LOG_LEVEL", "DEBUG")
TERM = os.environ.get("TERM", "xterm-256color")
NO_COLOR = os.environ.get("NO_COLOR", "1")
TIMEOUT_SEC = int(os.environ.get("TIMEOUT_SEC", "120"))
DEFAULT_REASON = f"pipeline waiver request - {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
WAIVER_REASON = os.environ.get("WAIVER_REASON", DEFAULT_REASON)

# --- PTY helpers ---
def set_winsize(fd, rows=60, cols=200):
    try: fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception: pass

def spawn_pty(cmd: str, extra_env=None):
    env = os.environ.copy()
    if extra_env: env.update(extra_env)
    pid, mfd = pty.fork()
    if pid == 0:
        argv = ["/bin/bash", "-lc", cmd]
        os.execvpe(argv[0], argv, env)
    set_winsize(mfd)
    return pid, mfd

def child_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def read_some(mfd, buf, echo=True):
    try:
        chunk = os.read(mfd, 8192).decode("utf-8", "ignore")
    except OSError:
        return False
    if not chunk:
        return False
    if echo:
        sys.stdout.write(chunk); sys.stdout.flush()
    buf.append(chunk)
    return True

def wait_for_regex(mfd, pattern, buf, timeout):
    rx = re.compile(pattern, re.I | re.S)
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([mfd], [], [], 0.1)
        if r:
            if not read_some(mfd, buf, echo=True):
                break
            if rx.search("".join(buf)):
                return True
    return False

def send_text(mfd, s, pause=0.25):
    try: os.write(mfd, s.encode("utf-8")); time.sleep(pause); return True
    except OSError: return False

def send_enter(mfd, pause=0.4):
    try: os.write(mfd, b"\r"); time.sleep(pause); return True
    except OSError: return False

# --- Main ---
def main():
    print(f"Using JFrog at: {os.environ.get('JF_RT_URL', 'https://psazuse.jfrog.io')}")
    print(f"BUILD_NAME={os.environ.get('BUILD_NAME','py-cli-req')}  BUILD_ID={os.environ.get('BUILD_ID','(auto)')}")
    print(f"REQ_FILE={REQ_FILE}  REPO_RESOLVE={REPO_RESOLVE}")

    common_env = {
        "JFROG_CLI_LOG_LEVEL": LOG_LEVEL,
        "NO_COLOR": NO_COLOR,
        "TERM": TERM,
        "JF_HOST": os.environ.get("JF_HOST", "psazuse.jfrog.io"),
        "JF_RT_URL": os.environ.get("JF_RT_URL", f"https://{os.environ.get('JF_HOST','psazuse.jfrog.io')}"),
        "BUILD_NAME": os.environ.get("BUILD_NAME", "py-cli-req"),
        "BUILD_ID": os.environ.get("BUILD_ID", f"cmd.{datetime.datetime.now():%Y-%m-%d-%H-%M}"),
    }

    # 1) pip config
    print("Preparing pip config...")
    pid, mfd = spawn_pty(f"{JF_CMD} pipc --repo-resolve={shlex.quote(REPO_RESOLVE)}", common_env)
    t_end = time.time() + 30
    buf = []
    while time.time() < t_end:
        r, _, _ = select.select([mfd], [], [], 0.1)
        if r:
            if not read_some(mfd, buf): break
    try: os.close(mfd)
    except Exception: pass
    print("pip config created.\n")

    # 2) curation + waiver
    print("Running curation audit + waiver flow in a real TTY...\n")
    pid, mfd = spawn_pty(f"{JF_CMD} ca --requirements-file={shlex.quote(REQ_FILE)} --format=table --threads=100", common_env)
    buf = []

    # A) Wait for the Y/N prompt and capture the "Found N blocked packages"
    wait_for_regex(mfd, r"Found\s+(\d+)\s+blocked packages", buf, timeout=min(30, TIMEOUT_SEC))
    m = re.search(r"Found\s+(\d+)\s+blocked packages", "".join(buf), re.I)
    expected = int(m.group(1)) if m else 1

    if not wait_for_regex(mfd, r"Do you want to request a waiver.*\[\s*n\s*\]\?", buf, timeout=min(30, TIMEOUT_SEC)):
        sys.stderr.write("\n[ERROR] Did not reach the Y/N waiver prompt.\n"); sys.exit(1)

    # B) Keystrokes: y, Enter, accept [all], reason, confirm
    send_text(mfd, "y", pause=0.2)
    send_enter(mfd, pause=0.6)
    send_enter(mfd, pause=0.6)  # accept [all]
    time.sleep(0.4)
    send_text(mfd, WAIVER_REASON, pause=0.3)
    send_enter(mfd, pause=0.6)
    send_enter(mfd, pause=0.4)  # final confirm (some builds)

    # C) Read until we’ve seen: "Waiver request submitted" AND >= expected WAIVER IDs, or EOF, or timeout
    submitted_rx = re.compile(r"Waiver request submitted", re.I)
    id_rx = re.compile(r"^\s*│\s*[^\|]+?\s*│\s*(?:pending|approved|rejected)\s*│[^\|]*?\s*│\s*(\d+)\s*│\s*$", re.I | re.M)

    end = time.time() + min(90, TIMEOUT_SEC)  # leave most of the budget here
    saw_submitted = False
    ids = set()
    transcript = "".join(buf)

    while time.time() < end:
        r, _, _ = select.select([mfd], [], [], 0.2)
        if r:
            if not read_some(mfd, buf, echo=True):
                break
            transcript = "".join(buf)
            if submitted_rx.search(transcript):
                saw_submitted = True
            # harvest IDs from the (possibly wrapped) result table — this regex matches the row that contains the numeric ID cell
            for m in id_rx.finditer(transcript):
                ids.add(m.group(1))
            if saw_submitted and len(ids) >= expected:
                break
        # If the child already exited, stop looping
        if not child_alive(pid):
            break

    # Drain a bit more output
    t_tail = time.time() + 2
    while time.time() < t_tail:
        r, _, _ = select.select([mfd], [], [], 0.1)
        if not r: break
        if not read_some(mfd, buf, echo=True): break

    try: os.close(mfd)
    except Exception: pass

    transcript = "".join(buf)
    if not saw_submitted or len(ids) < expected:
        sys.stderr.write(
            f"\n[ERROR] Waiver table incomplete: saw_submitted={saw_submitted}, "
            f"waiver_ids_found={len(ids)}, expected={expected}.\n"
            "Full transcript above. Increase TIMEOUT_SEC if network is slow, "
            "or ensure the CLI prints the final results table.\n"
        )
        sys.exit(1)

    print(f"\n✅ Collected {len(ids)}/{expected} waiver IDs: {', '.join(sorted(ids))}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrupted by user.")
