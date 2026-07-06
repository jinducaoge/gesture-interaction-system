import asyncio
import os
import signal
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class ManagedProcess:
    name: str
    proc: asyncio.subprocess.Process
    cmd: List[str]
    cwd: Optional[str] = None


class RosProcessManager:
    """
    管理 ros2 launch / ros2 run 等子进程：
    - start_ros2_launch: 异步启动 launch，并支持 extra_env 注入环境变量（例如 CAM_TYPE=usb）
    - stop: 对整个进程组发送 SIGINT 优雅退出，超时后 SIGKILL
    - is_running / list
    """

    def __init__(
        self,
        ros_setup_cmd: Optional[str] = None,
        stop_timeout_sec: float = 5.0,
    ) -> None:
        """
        ros_setup_cmd 示例：
          - "source /opt/ros/humble/setup.bash && source /path/to/workspace/install/setup.bash"
        如果你不传，就默认不 source（前提是你运行 FastAPI 的环境本身已 source 过）
        """
        self.ros_setup_cmd = ros_setup_cmd
        self.stop_timeout_sec = stop_timeout_sec
        self._procs: Dict[str, ManagedProcess] = {}
        self.on_log = None

    def _build_bash_cmd(self, ros_cmd: str) -> List[str]:
        if self.ros_setup_cmd:
            full = f"{self.ros_setup_cmd} && {ros_cmd}"
        else:
            full = ros_cmd
        return ["bash", "-lc", full]

    def is_running(self, name: str) -> bool:
        mp = self._procs.get(name)
        if not mp:
            return False
        return mp.proc.returncode is None

    def list(self) -> List[str]:
        return [k for k in self._procs.keys() if self.is_running(k)]

    async def _read_stream(self, name: str, stream: asyncio.StreamReader) -> None:
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                try:
                    text = line.decode("utf-8", errors="ignore").rstrip()
                except Exception:
                    text = str(line)

                if self.on_log is not None:
                    try:
                        await self.on_log(name, text)
                    except Exception:
                        print(f"[{name}] {text}")
                else:
                    print(f"[{name}] {text}")
        except asyncio.CancelledError:
            return

    async def _wait_process_stable(self, proc: asyncio.subprocess.Process, grace: float = 1.0) -> tuple[bool, int | None]:
        await asyncio.sleep(grace)
        if proc.returncode is not None:
            return False, proc.returncode
        return True, None

    def bind_log_pusher(self, cb):
        self.on_log = cb

    async def start_ros2_launch(
        self,
        name: str,
        package: str,
        launch_file: str,
        *,
        args: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        stream_logs: bool = True,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> bool:
        if self.is_running(name):
            return True

        args = args or []
        ros_cmd = " ".join(["ros2", "launch", package, launch_file] + args)
        cmd = self._build_bash_cmd(ros_cmd)

        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE if stream_logs else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.STDOUT if stream_logs else asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )

        self._procs[name] = ManagedProcess(name=name, proc=proc, cmd=cmd, cwd=cwd)

        if stream_logs and proc.stdout is not None:
            asyncio.create_task(self._read_stream(name, proc.stdout))

        ok, returncode = await self._wait_process_stable(proc, grace=1.0)
        if not ok:
            self._procs.pop(name, None)
            print(f"[{name}] process exited during startup grace period, returncode={returncode}")
            return False

        return True

    async def start_command(
        self,
        name: str,
        cmd: List[str],
        *,
        cwd: Optional[str] = None,
        stream_logs: bool = True,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> bool:
        if self.is_running(name):
            return True

        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE if stream_logs else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.STDOUT if stream_logs else asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )

        self._procs[name] = ManagedProcess(name=name, proc=proc, cmd=cmd, cwd=cwd)

        if stream_logs and proc.stdout is not None:
            asyncio.create_task(self._read_stream(name, proc.stdout))

        ok, returncode = await self._wait_process_stable(proc, grace=1.0)
        if not ok:
            self._procs.pop(name, None)
            print(f"[{name}] process exited during startup grace period, returncode={returncode}")
            return False

        return True

    async def stop(self, name: str) -> bool:
        mp = self._procs.get(name)
        if not mp:
            return True

        proc = mp.proc
        if proc.returncode is not None:
            self._procs.pop(name, None)
            return True

        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            self._procs.pop(name, None)
            return True

        try:
            os.killpg(pgid, signal.SIGINT)
        except ProcessLookupError:
            self._procs.pop(name, None)
            return True

        try:
            await asyncio.wait_for(proc.wait(), timeout=self.stop_timeout_sec)
        except asyncio.TimeoutError:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()

        self._procs.pop(name, None)
        return True

    async def stop_all(self) -> None:
        names = list(self._procs.keys())
        for n in names:
            await self.stop(n)
