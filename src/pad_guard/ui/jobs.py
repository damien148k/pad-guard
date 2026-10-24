"""Background jobs of the interface: ``analyze``, ``rerun`` and ``draft-profile`` run as the CLI.

The command is ``python -m pad_guard <command> … --progress-json <file>``: exactly the code and the
run.json of a terminal run. One job at a time. It goes on when the browser is closed; its state is
written in a job file next to the settings, so that the page finds it again, and so does the
server after a restart (a job whose process is gone without its end line is « interrompue »).
Cancelling kills the whole process tree (the video measurement uses worker processes).

The screen of the job is built here from the progress lines: steps, counters, journal. Nothing
about the verdict: it is read in the « done » line the CLI writes from verdict.json.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ANALYZE_STAGES = [  # (stage of --progress-json, label, files written)
    ("probe", "Lecture du fichier", "probe.json"),
    ("measure_video", "Mesures image", "measurements_video.jsonl"),
    ("measure_audio", "Mesures audio", "measurements_audio.jsonl"),
    ("structure", "Structure", "structure.json"),
    ("rules", "Règles", "events.json · verdict.json"),
    ("report", "Rapport", "rapport.pdf · rapport.md"),
]
RERUN_STAGES = ANALYZE_STAGES[3:]
DRAFT_STAGES = [("read", "Lecture du PDF", "texte et images des pages"),
                ("extract", "Extraction par l'IA locale", "propositions citées"),
                ("write", "Brouillon", "profiles/drafts/")]
STAGES = {"analyze": ANALYZE_STAGES, "rerun": RERUN_STAGES, "draft": DRAFT_STAGES}
OK_EXIT = {"analyze": (0, 4), "rerun": (0, 4), "draft": (0,)}  # 4: the analysis ran, verdict NON-CONFORME
STILL_ACTIVE = 259


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def mmss(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        import ctypes  # noqa: PLC0415

        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        try:
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:
        import signal  # noqa: PLC0415

        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass


@dataclass
class Job:
    id: str
    kind: str  # analyze | rerun | draft
    title: str
    args: list[str]  # arguments of pad-guard
    command: str  # as run.json records it
    progress_file: str
    log_dir: str
    workdir: str | None = None  # analysis directory (analyze, rerun)
    run_id: str | None = None  # its name under the analyses root
    draft: str | None = None  # draft written (draft)
    state: str = "running"  # running | done | failed | cancelled | interrupted
    pid: int | None = None
    started_at: str = ""
    started: float = 0.0  # time.time()
    ended: float | None = None
    exit_code: int | None = None

    @property
    def stdout(self) -> Path:
        return Path(self.log_dir) / f"{self.id}.stdout.log"

    @property
    def stderr(self) -> Path:
        return Path(self.log_dir) / f"{self.id}.stderr.log"


def read_progress(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a line being written
    return out


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def error_lines(job: Job, limit: int = 12) -> list[str]:
    """Last lines the CLI wrote to stderr: its user-facing messages (French)."""
    if not job.stderr.is_file():
        return []
    lines = [_ANSI.sub("", x).rstrip() for x in job.stderr.read_text(encoding="utf-8", errors="replace").splitlines()]
    return [x for x in lines if x.strip()][-limit:]


def snapshot(job: Job) -> dict[str, Any]:
    """What the « Analyse » screen shows, from the progress lines of the CLI."""
    lines = read_progress(Path(job.progress_file))
    stages = STAGES[job.kind]
    keys = [k for k, _, _ in stages]
    starts: dict[str, float] = {}
    for x in lines:
        stage = "write" if job.kind == "draft" and x["stage"] == "done" else x["stage"]
        if stage in keys and stage not in starts:
            starts[stage] = x["t"]
    end_line = next((x for x in reversed(lines) if x["stage"] == "done"), None)
    last_t = lines[-1]["t"] if lines else 0.0
    now_t = (job.ended or time.time()) - job.started
    current = max((k for k in starts), key=keys.index, default=None)
    finished = job.state == "done"
    rows = []
    for i, (key, label, files) in enumerate(stages):
        if key not in starts:
            state = "todo"
        elif finished or keys.index(key) < keys.index(current):
            state = "done"
        elif job.state == "running":
            state = "active"
        else:
            state = "failed" if job.state in ("failed", "interrupted") else "stopped"
        later = [starts[k] for k in keys[i + 1:] if k in starts]
        info = ""
        if state == "done":
            info = mmss((later[0] if later else last_t) - starts[key])
        rows.append({"key": key, "label": label, "files": files, "state": state, "info": info})

    counter_stage = "measure_video" if job.kind == "analyze" else "extract" if job.kind == "draft" else None
    counts = [x for x in lines if x["stage"] == counter_stage and x.get("total")]
    done_n = counts[-1]["done"] if counts else 0
    total_n = counts[-1]["total"] if counts else None
    pct = None
    remaining = None
    if total_n:
        pct = 100.0 if finished else min(100.0, 100.0 * done_n / total_n)
        first = counts[0]
        rate = (done_n - first["done"]) / (counts[-1]["t"] - first["t"]) if counts[-1]["t"] > first["t"] else 0
        if job.state == "running" and current == counter_stage and rate > 0:
            remaining = "~" + mmss((total_n - done_n) / rate)
    for row in rows:
        if row["state"] == "active" and row["key"] == counter_stage and total_n:
            row["info"] = f"{done_n * 100 // total_n} %"

    journal = [{"t": mmss(0), "msg": f"démarrage · {job.title}", "tone": "grey"}]
    for x in lines:
        if x["stage"] in (counter_stage,) and "msg" not in x:
            continue
        if x["stage"] == "done":
            continue
        if x.get("msg"):
            journal.append({"t": mmss(x["t"]), "msg": x["msg"], "tone": ""})
    result = None
    if end_line is not None:
        result = {k: end_line.get(k) for k in ("status", "indicative", "draft")}
        result["label"] = end_line.get("msg", "")
        tail = ("verdict calculé par les règles : " + result["label"]) if job.kind != "draft" else end_line.get("msg", "")
        journal.append({"t": mmss(end_line["t"]), "msg": "terminé · " + tail, "tone": "green"})
    errors = error_lines(job) if job.state in ("failed", "interrupted") else []
    if job.state == "cancelled":
        journal.append({"t": mmss(now_t), "msg": "annulé à la demande : le dossier est incomplet", "tone": "red"})
    elif job.state == "interrupted":
        journal.append({"t": mmss(now_t), "msg": "interrompu (serveur ou processus arrêté avant la fin)", "tone": "red"})
    journal += [{"t": "", "msg": e, "tone": "red"} for e in errors]
    return {
        "id": job.id, "kind": job.kind, "title": job.title, "state": job.state, "command": job.command,
        "workdir": job.workdir, "run_id": job.run_id, "draft": result.get("draft") if result else job.draft,
        "started_at": job.started_at, "elapsed": mmss(now_t), "remaining": remaining,
        "pct": pct, "done": done_n, "total": total_n, "stages": rows, "journal": journal,
        "result": result, "errors": errors, "exit_code": job.exit_code,
    }


class JobManager:
    """One job at a time; its record in ``<dir>/<id>.json`` survives the server."""

    def __init__(self, directory: Path):
        self.dir = directory
        self.lock = threading.Lock()
        self.job: Job | None = None
        self.proc: subprocess.Popen | None = None
        self._recover()

    # --- persistence ----------------------------------------------------------------------

    def _save(self, job: Job) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"{job.id}.json").write_text(json.dumps(asdict(job), ensure_ascii=False, indent=2), encoding="utf-8")
        if job.workdir:  # the analysis directory knows how it was launched (and if it ended)
            (Path(job.workdir) / "ui_job.json").write_text(
                json.dumps({"id": job.id, "state": job.state, "command": job.command, "exit_code": job.exit_code},
                           ensure_ascii=False, indent=2), encoding="utf-8")

    def _recover(self) -> None:
        records = sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime) if self.dir.is_dir() else []
        if not records:
            return
        try:
            job = Job(**json.loads(records[-1].read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            return
        self.job = job
        if job.state == "running":
            if pid_alive(job.pid):
                threading.Thread(target=self._follow_pid, args=(job,), daemon=True).start()
            else:
                self._ended_without_us(job)

    def _ended_without_us(self, job: Job) -> None:
        done = any(x["stage"] == "done" for x in read_progress(Path(job.progress_file)))
        job.state = "done" if done else "interrupted"
        job.ended = job.ended or time.time()
        self._save(job)

    def _follow_pid(self, job: Job) -> None:
        while pid_alive(job.pid) and job.state == "running":
            time.sleep(1)
        if job.state == "running":
            self._ended_without_us(job)

    # --- jobs -----------------------------------------------------------------------------

    def current(self) -> Job | None:
        return self.job

    def busy(self) -> bool:
        return self.job is not None and self.job.state == "running"

    def start(self, kind: str, title: str, args: list[str], progress_file: Path, workdir: Path | None = None,
              run_id: str | None = None) -> Job:
        with self.lock:
            if self.busy():
                from pad_guard.ui.server import ApiError  # noqa: PLC0415

                raise ApiError(f"une tâche est déjà en cours : {self.job.title}", status=409)
            job_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
            full = [*args, "--progress-json", str(progress_file)]
            job = Job(id=job_id, kind=kind, title=title, args=full,
                      command=subprocess.list2cmdline(["pad-guard", *args]), progress_file=str(progress_file),
                      log_dir=str(self.dir), workdir=str(workdir) if workdir else None, run_id=run_id,
                      started_at=now_iso(), started=time.time())
            self.dir.mkdir(parents=True, exist_ok=True)
            progress_file.parent.mkdir(parents=True, exist_ok=True)
            progress_file.write_text("", encoding="utf-8")
            env = {**os.environ, "NO_COLOR": "1", "COLUMNS": "200", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            with job.stdout.open("wb") as out, job.stderr.open("wb") as err:
                self.proc = subprocess.Popen([sys.executable, "-m", "pad_guard", *full], stdout=out, stderr=err,
                                             stdin=subprocess.DEVNULL, env=env, creationflags=flags,
                                             start_new_session=os.name != "nt")
            job.pid = self.proc.pid
            self.job = job
            self._save(job)
            threading.Thread(target=self._wait, args=(job, self.proc), daemon=True).start()
            return job

    def _wait(self, job: Job, proc: subprocess.Popen) -> None:
        code = proc.wait()
        with self.lock:
            if job.state == "running":
                job.exit_code = code
                job.state = "done" if code in OK_EXIT[job.kind] else "failed"
            job.ended = job.ended or time.time()
            self._save(job)

    def cancel(self) -> Job | None:
        with self.lock:
            job = self.job
            if job is None or job.state != "running":
                return job
            job.state = "cancelled"
            job.ended = time.time()
            if job.pid:
                kill_tree(job.pid)
            self._save(job)
            return job

    def wait(self, timeout: float = 600) -> Job | None:
        """Tests: wait for the end of the current job."""
        limit = time.time() + timeout
        while self.busy() and time.time() < limit:
            time.sleep(0.2)
        return self.job
