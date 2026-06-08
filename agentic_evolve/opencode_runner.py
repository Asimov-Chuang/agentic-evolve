from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    error: str | None = None
    pid: int | None = None
    stopped_reason: str | None = None


class OpenCodeRunner:
    def __init__(self, command: str, args: list[str], verbose: bool = False):
        self.command = command
        self.args = args
        self.verbose = verbose

    def _build_command(self, workspace_dir: str, prompt: str) -> list[str]:
        workspace = str(Path(workspace_dir).resolve())
        args = list(self.args)

        # opencode run ignores subprocess cwd; must pass --dir explicitly.
        if "--dir" not in args:
            args.extend(["--dir", workspace])

        return [self.command, *args, prompt]

    def run(
        self,
        workspace_dir: str,
        prompt: str,
        timeout_seconds: int,
        *,
        pid_holder: list[int] | None = None,
    ) -> RunResult:
        workspace = Path(workspace_dir).resolve()
        workspace.mkdir(parents=True, exist_ok=True)

        prompt_path = workspace / "prompt.md"
        stdout_path = workspace / "agent_stdout.log"
        stderr_path = workspace / "agent_stderr.log"

        prompt_path.write_text(prompt, encoding="utf-8")

        cmd = self._build_command(str(workspace), prompt)
        workspace_str = str(workspace)

        try:
            if self.verbose:
                return self._run_streaming(
                    cmd, workspace_str, stdout_path, stderr_path, timeout_seconds, pid_holder
                )
            return self._run_captured(
                cmd, workspace_str, stdout_path, stderr_path, timeout_seconds, pid_holder
            )
        except FileNotFoundError:
            msg = f"Command not found: {self.command}"
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text(msg + "\n", encoding="utf-8")
            return RunResult(
                success=False,
                returncode=-1,
                stdout="",
                stderr=msg,
                error=msg,
            )

    def _run_captured(
        self,
        cmd: list[str],
        workspace_dir: str,
        stdout_path: Path,
        stderr_path: Path,
        timeout_seconds: int,
        pid_holder: list[int] | None = None,
    ) -> RunResult:
        try:
            process = subprocess.Popen(
                cmd,
                cwd=workspace_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            pid = process.pid
            if pid_holder is not None:
                pid_holder.clear()
                pid_holder.append(pid)
            try:
                stdout, stderr = process.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                stdout, stderr = process.communicate()
                exc.stdout = stdout
                exc.stderr = stderr
                result = self._timeout_result(exc, stdout_path, stderr_path, timeout_seconds)
                result.pid = pid
                return result
            stdout_path.write_text(stdout or "", encoding="utf-8")
            stderr_path.write_text(stderr or "", encoding="utf-8")
            return RunResult(
                success=process.returncode == 0,
                returncode=process.returncode or 0,
                stdout=stdout or "",
                stderr=stderr or "",
                pid=pid,
            )
        except subprocess.TimeoutExpired as exc:
            return self._timeout_result(exc, stdout_path, stderr_path, timeout_seconds)

    def _run_streaming(
        self,
        cmd: list[str],
        workspace_dir: str,
        stdout_path: Path,
        stderr_path: Path,
        timeout_seconds: int,
        pid_holder: list[int] | None = None,
    ) -> RunResult:
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        with open(stdout_path, "w", encoding="utf-8") as stdout_file, open(
            stderr_path, "w", encoding="utf-8"
        ) as stderr_file:
            process = subprocess.Popen(
                cmd,
                cwd=workspace_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            pid = process.pid
            if pid_holder is not None:
                pid_holder.clear()
                pid_holder.append(pid)

            def pump(stream, log_file, chunks, out_stream):
                assert stream is not None
                for line in iter(stream.readline, ""):
                    chunks.append(line)
                    log_file.write(line)
                    log_file.flush()
                    out_stream.write(line)
                    out_stream.flush()
                stream.close()

            threads = [
                threading.Thread(
                    target=pump,
                    args=(process.stdout, stdout_file, stdout_chunks, sys.stdout),
                    daemon=True,
                ),
                threading.Thread(
                    target=pump,
                    args=(process.stderr, stderr_file, stderr_chunks, sys.stderr),
                    daemon=True,
                ),
            ]
            for thread in threads:
                thread.start()

            try:
                returncode = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                for thread in threads:
                    thread.join(timeout=1)
                msg = f"OpenCode timed out after {timeout_seconds}s"
                stderr_file.write(msg + "\n")
                stderr_file.flush()
                sys.stderr.write(msg + "\n")
                sys.stderr.flush()
                stderr_chunks.append(msg + "\n")
                return RunResult(
                    success=False,
                    returncode=-1,
                    stdout="".join(stdout_chunks),
                    stderr="".join(stderr_chunks),
                    error=msg,
                    pid=pid,
                )

            for thread in threads:
                thread.join()

        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)
        return RunResult(
            success=returncode == 0,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            pid=pid,
        )

    def _timeout_result(
        self,
        exc: subprocess.TimeoutExpired,
        stdout_path: Path,
        stderr_path: Path,
        timeout_seconds: int,
    ) -> RunResult:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        msg = f"OpenCode timed out after {timeout_seconds}s"
        stderr = f"{stderr}\n{msg}".strip()
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr + "\n", encoding="utf-8")
        return RunResult(
            success=False,
            returncode=-1,
            stdout=stdout,
            stderr=stderr,
            error=msg,
        )
