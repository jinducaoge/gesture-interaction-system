import asyncio
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from orchestrator.ros_process_manager import RosProcessManager
from services.sign_text_service import SignTextService
from services.sign_session_store import SignSessionStore
from services.playback_service import PlaybackSpeakerService
from services.voice_mapper_service import VoiceMapperService
from services.dialog_service import DialogService
from services.voice_session_store import VoiceSessionStore
logger = logging.getLogger("orchestrator.task_hub")
@dataclass
class LaunchConfig:
    name: str
    package: str
    launch_file: str
    args: List[str]
    cwd: Optional[str]
    env: Dict[str, str]
EMPTY_SIGN_TEXT = "（本次未识别到词）"
def _env_get(key: str, default: str) -> str:
    v = os.getenv(key)
    return v if (v is not None and v != "") else default
def _env_get_opt(key: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(key)
    return v if (v is not None and v != "") else default
class TaskFlags:
    def __init__(self) -> None:
        self.kp_running = False
        self.sign_running = False
        self.voice_running = False
        self.chat_running = False
class TaskHub:
    PROC_REC_PUB = "rec_pub_true"
    PROC_KP = "kp_launch"
    PROC_VOICE = "voice_launch"
    PROC_VOICE_SUB = "voice_asr_subscriber"
    PROC_CHAT = "chat_launch"
    PROC_SIGN = "sign_runtime"
    PROC_SIGN_ISO = "sign_iso_launch"
    def __init__(self) -> None:
        ros_setup_cmd = os.getenv("ROS_SETUP_CMD", "")
        self.ros = RosProcessManager(ros_setup_cmd=ros_setup_cmd, stop_timeout_sec=5.0)
        self.flags = TaskFlags()
        self._push_evt = None
        self._serial = None
        self._recognized_words: List[str] = []
        self._recognized_events: List[dict] = []
        self._recent_logs = deque(maxlen=200)
        self._recent_sign_logs = deque(maxlen=100)
        self._recent_voice_logs = deque(maxlen=100)
        self.project_root = Path(__file__).resolve().parent.parent
        self.default_sign_script = self.project_root / "ros_nodes" / "hand_subscriber.py"
        self.default_voice_script = self.project_root / "ros_nodes" / "asr_subscriber.py"
        self.sign_store = SignSessionStore(_env_get_opt("SIGN_SESSION_BASE_DIR", str(self.project_root / "data" / "sign_sessions")))
        self.voice_store = VoiceSessionStore(_env_get_opt("VOICE_SESSION_BASE_DIR", str(self.project_root / "data" / "voice_sessions")))
        self.sign_text_service = SignTextService()
        self.voice_mapper_service = VoiceMapperService()
        self.dialog_service = DialogService(self.voice_mapper_service)
        self.playback_service = PlaybackSpeakerService.from_env()
        self.current_sign_session_id: Optional[str] = None
        self.current_voice_session_id: Optional[str] = None
        self._sign_summary_tasks: dict[str, asyncio.Task] = {}
        self._latest_voice_text = ""
        self._latest_voice_tokens = ""
        self._latest_voice_ids: list[int] = []
        self._voice_records: list[dict[str, Any]] = []
        self.kp_cfg = LaunchConfig(
            name=self.PROC_KP,
            package=_env_get("KP_LAUNCH_PACKAGE", "hand_lmk_detection"),
            launch_file=_env_get("KP_LAUNCH_FILE", "hand_lmk_detection.launch.py"),
            args=[],
            cwd=_env_get_opt("KP_LAUNCH_CWD", None),
            env={"CAM_TYPE": _env_get("CAM_TYPE", "usb")},
        )
        self.voice_cfg = LaunchConfig(
            name=self.PROC_VOICE,
            package=_env_get("VOICE_LAUNCH_PACKAGE", "sensevoice_ros2"),
            launch_file=_env_get("VOICE_LAUNCH_FILE", "sensevoice_ros2.launch.py"),
            args=[
                _env_get("VOICE_LAUNCH_ARG_MODEL", 'audio_asr_model:="sense-voice-small-fp16.gguf"'),
                _env_get("VOICE_LAUNCH_ARG_LANGUAGE", 'language:="zh"'),
                _env_get("VOICE_LAUNCH_ARG_MICPHONE", 'micphone_name:="plughw:0,0"'),
            ],
            cwd=_env_get_opt("VOICE_LAUNCH_CWD", None),
            env={},
        )
        self.chat_cfg = LaunchConfig(
            name=self.PROC_CHAT,
            package=_env_get("CHAT_LAUNCH_PACKAGE", "your_chat_pkg"),
            launch_file=_env_get("CHAT_LAUNCH_FILE", "sign_chat.launch.py"),
            args=[],
            cwd=_env_get_opt("CHAT_LAUNCH_CWD", None),
            env={},
        )
    def bind_pusher(self, push_evt):
        self._push_evt = push_evt
        async def _on_log(name: str, text: str):
            line = f"[{name}] {text}"
            self._recent_logs.append(line)
            if name == self.PROC_SIGN:
                self._recent_sign_logs.append(line)
            if name in {self.PROC_VOICE, self.PROC_VOICE_SUB}:
                self._recent_voice_logs.append(line)
            handled = await self._handle_special_log(name, text)
            if not handled and self._push_evt is not None:
                await self._push_evt({"type": "ros_log", "payload": {"proc": name, "line": text}, "ts": time.time()})
        self.ros.bind_log_pusher(_on_log)
    def bind_serial_service(self, serial_service) -> None:
        self._serial = serial_service
    def _tail_recent_logs(self, limit: int = 20, proc_name: str | None = None) -> list[str]:
        source = self._recent_logs
        if proc_name == self.PROC_SIGN:
            source = self._recent_sign_logs
        elif proc_name in {self.PROC_VOICE, self.PROC_VOICE_SUB}:
            source = self._recent_voice_logs
        return list(source)[-limit:]
    def _recent_log_block(self, limit: int = 20, proc_name: str | None = None) -> str:
        recent = self._tail_recent_logs(limit=limit, proc_name=proc_name)
        PLACEHOLDER
    async def _push_sign_diag(self, message: str, level: str = "warning") -> None:
        if self._push_evt is not None:
            await self._push_evt({"type": "sign_diag", "payload": {"level": level, "message": message}, "ts": time.time()})
    async def _push_voice_diag(self, message: str, level: str = "info") -> None:
        if self._push_evt is not None:
            await self._push_evt({"type": "voice_diag", "payload": {"level": level, "message": message}, "ts": time.time()})
    async def _push_voice_state(self, running: bool) -> None:
        if self._push_evt is not None:
            await self._push_evt({
                "type": "voice_state",
                "payload": {
                    "running": bool(running),
                    "session_id": self.current_voice_session_id or "",
                    "latest_text": self._latest_voice_text,
                    "latest_tokens": self._latest_voice_tokens,
                    "latest_ids": list(self._latest_voice_ids),
                },
                "ts": time.time(),
            })
    async def _handle_special_log(self, name: str, text: str) -> bool:
        if name == self.PROC_SIGN:
            prefix_map = {
                "[SIGN_RESULT]": self._handle_sign_result_line,
                "[SIGN_STATE]": self._handle_sign_state_line,
            }
            for prefix, handler in prefix_map.items():
                idx = text.find(prefix)
                if idx >= 0:
                    payload_text = text[idx + len(prefix):].strip()
                    try:
                        payload = json.loads(payload_text) if payload_text else {}
                    except json.JSONDecodeError:
                        payload = {"raw": payload_text}
                    await handler(payload)
                    return True
        if name == self.PROC_VOICE_SUB:
            prefix_map = {
                "[VOICE_RESULT]": self._handle_voice_result_line,
                "[VOICE_STATE]": self._handle_voice_state_line,
                "[VOICE_ERROR]": self._handle_voice_error_line,
            }
            for prefix, handler in prefix_map.items():
                idx = text.find(prefix)
                if idx >= 0:
                    payload_text = text[idx + len(prefix):].strip()
                    try:
                        payload = json.loads(payload_text) if payload_text else {}
                    except json.JSONDecodeError:
                        payload = {"raw": payload_text}
                    await handler(payload)
                    return True
        return False
    async def _handle_sign_state_line(self, payload: dict) -> None:
        if self._push_evt is not None:
            await self._push_evt({"type": "sign_runtime_state", "payload": payload, "ts": time.time()})
    async def _handle_sign_result_line(self, payload: dict) -> None:
        await self.ingest_sign_result(payload)
    async def _handle_voice_state_line(self, payload: dict) -> None:
        await self._push_voice_diag(f"ASR订阅节点已启动：{payload}", level="info")
    async def _handle_voice_error_line(self, payload: dict) -> None:
        await self._push_voice_diag(f"ASR订阅回传异常：{payload}", level="warning")
    async def _handle_voice_result_line(self, payload: dict) -> None:
        await self.ingest_voice_result(payload)
    async def ingest_sign_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        label = str(payload.get("label", "")).strip()
        if not label or not self.flags.sign_running:
            return {}
        if self._recognized_words and self._recognized_words[-1] == label:
            return {}
        self._recognized_words.append(label)
        self._recognized_events.append(payload)
        self._schedule_word_tts(label)
        session = None
        if self.current_sign_session_id:
            try:
                session = self.sign_store.append_word(self.current_sign_session_id, label, payload)
            except Exception as exc:
                await self._push_sign_diag(f"写入手语 session 失败：{exc}", level="warning")
        raw_text = (session or {}).get("raw_text") or self._build_raw_text(self._recognized_words)
        word_count = int((session or {}).get("word_count") or len(self._recognized_words))
        event_payload = dict(payload)
        event_payload.update({"label": label, "session_id": self.current_sign_session_id or "", "raw_text": raw_text, "word_count": word_count})
        if self._push_evt is not None:
            await self._push_evt({"type": "sign_word", "payload": event_payload, "ts": time.time()})
            await self._push_evt({"type": "sign_sentence", "payload": {"text": raw_text or EMPTY_SIGN_TEXT, "session_id": self.current_sign_session_id or "", "word_count": word_count}, "ts": time.time()})
        return session or event_payload
    def _build_sign_runtime_cmd(self) -> List[str]:
        custom_cmd = os.getenv("SIGN_NODE_CMD", "").strip()
        if custom_cmd:
            return self.ros._build_bash_cmd(custom_cmd)
        script_path = os.getenv("SIGN_NODE_SCRIPT", str(self.default_sign_script))
        return self.ros._build_bash_cmd(f'python3 "{script_path}"')
    async def _start_sign_runtime(self) -> bool:
        cmd = self._build_sign_runtime_cmd()
        cwd = _env_get_opt("SIGN_NODE_CWD", str(self.project_root))
        extra_env = {}
        model_path = os.getenv("SIGN_MODEL_PATH", "").strip()
        label_path = os.getenv("SIGN_LABEL_PATH", "").strip()
        orch_http_base = _env_get("ORCH_HTTP_BASE", "http://127.0.0.1:8001").rstrip("/")
        sign_result_callback_url = _env_get("SIGN_RESULT_CALLBACK_URL", f"{orch_http_base}/sign/result")
        if model_path:
            extra_env["SIGN_MODEL_PATH"] = model_path
        if label_path:
            extra_env["SIGN_LABEL_PATH"] = label_path
        if sign_result_callback_url:
            extra_env["SIGN_RESULT_CALLBACK_URL"] = sign_result_callback_url
        report_timeout = os.getenv("SIGN_RESULT_REPORT_TIMEOUT_SEC", "0.4").strip()
        if report_timeout:
            extra_env["SIGN_RESULT_REPORT_TIMEOUT_SEC"] = report_timeout
        return await self.ros.start_command(name=self.PROC_SIGN, cmd=cmd, cwd=cwd, stream_logs=True, extra_env=extra_env)
    def _reset_sign_session_memory(self) -> None:
        self._recognized_words.clear()
        self._recognized_events.clear()
    def _create_sign_session(self, mode: str) -> dict[str, Any]:
        self._reset_sign_session_memory()
        session = self.sign_store.create_session(mode=mode)
        self.current_sign_session_id = session["session_id"]
        return session
    async def start_sign_iso(self) -> bool:
        if not self.flags.kp_running:
            await self.start_kp()
        self._create_sign_session("ISO")
        await self.publish_start_recording(True, rate_hz=10.0)
        self.flags.sign_running = True
        return True
    async def _sign_startup_diagnose(self) -> None:
        await asyncio.sleep(2.0)
        if self.flags.sign_running and not self._recognized_words:
            await self._push_sign_diag("手语识别已启动，但 2 秒内未收到任何识别词。请检查摄像头、KP 节点、/start_recording、模型路径和 ROS topic。", level="warning")
    async def start_sign(self, mode: str) -> bool:
        if not self.flags.kp_running:
            await self.start_kp()
        kp_alive = self.ros.is_running(self.kp_cfg.name)
        sign_alive = self.ros.is_running(self.PROC_SIGN)
        if not kp_alive or not sign_alive:
            raise RuntimeError(
                "手语识别依赖进程未正常运行。\n"
                f"kp_alive={kp_alive}, sign_alive={sign_alive}\n"
                f"最近日志：\n{self._recent_log_block(limit=20)}"
            )
        session = self._create_sign_session(mode)
        try:
            ok = await self.publish_start_recording(True, rate_hz=10.0)
            self.flags.sign_running = bool(ok)
            if not ok:
                self.sign_store.update_session(session["session_id"], status="error")
                raise RuntimeError(
                    f"/start_recording 发布失败。\n最近日志：\n{self._recent_log_block(limit=20)}"
                )
        except Exception:
            self.flags.sign_running = False
            raise
        asyncio.create_task(self._sign_startup_diagnose())
        return True
    async def stop_sign(self) -> dict[str, Any]:
        session_id = self.current_sign_session_id
        await self.publish_start_recording(False)
        self.flags.sign_running = False
        summary = await self._stop_session_without_ai()
        if session_id:
            self._start_sign_summary_background(session_id)
        return summary
    async def stop_sign_and_kp(self) -> bool:
        if self.flags.sign_running:
            await self._stop_session_without_ai()
        await self.publish_start_recording(False)
        ok_kp, ok_sign = await asyncio.gather(self.ros.stop(self.kp_cfg.name), self.ros.stop(self.PROC_SIGN))
        self.flags.sign_running = False
        self.flags.kp_running = False
        self._reset_sign_session_memory()
        return bool(ok_kp or ok_sign)
    async def stop_chat_stack(self) -> bool:
        try:
            return await self.stop_chat()
        except Exception:
            return True
    async def start_kp(self) -> bool:
        kp_ok = await self.ros.start_ros2_launch(name=self.kp_cfg.name, package=self.kp_cfg.package, launch_file=self.kp_cfg.launch_file, args=self.kp_cfg.args, cwd=self.kp_cfg.cwd, stream_logs=True, extra_env=self.kp_cfg.env)
        sign_ok = await self._start_sign_runtime()
        await asyncio.sleep(1.0)
        kp_alive = self.ros.is_running(self.kp_cfg.name)
        sign_alive = self.ros.is_running(self.PROC_SIGN)
        if not kp_ok or not sign_ok or not kp_alive or not sign_alive:
            if kp_alive:
                await self.ros.stop(self.kp_cfg.name)
            if sign_alive:
                await self.ros.stop(self.PROC_SIGN)
            self.flags.kp_running = False
            self.flags.sign_running = False
            raise RuntimeError(
                "启动关键点/手语识别运行时失败。\n"
                f"kp_ok={kp_ok}, sign_ok={sign_ok}, kp_alive={kp_alive}, sign_alive={sign_alive}\n"
                f"最近日志：\n{self._recent_log_block(limit=20)}"
            )
        self.flags.kp_running = True
        return True
    async def stop_kp(self) -> bool:
        if self.flags.sign_running:
            await self._stop_session_without_ai()
        ok_kp, ok_sign = await asyncio.gather(self.ros.stop(self.kp_cfg.name), self.ros.stop(self.PROC_SIGN))
        self.flags.kp_running = False
        self.flags.sign_running = False
        self._reset_sign_session_memory()
        return bool(ok_kp or ok_sign)
    def _reset_voice_session_memory(self) -> None:
        self._latest_voice_text = ""
        self._latest_voice_tokens = ""
        self._latest_voice_ids = []
        self._voice_records = []
    def _create_voice_session(self) -> dict[str, Any]:
        self._reset_voice_session_memory()
        session = self.voice_store.create_session()
        self.current_voice_session_id = session['session_id']
        return session
    def _build_voice_subscriber_cmd(self) -> List[str]:
        custom_cmd = os.getenv('VOICE_SUBSCRIBER_CMD', '').strip()
        if custom_cmd:
            return self.ros._build_bash_cmd(custom_cmd)
        script_path = os.getenv('VOICE_SUBSCRIBER_SCRIPT', str(self.default_voice_script))
        orch_http_base = _env_get('ORCH_HTTP_BASE', 'http://127.0.0.1:8001').rstrip('/')
        callback_url = _env_get('VOICE_RESULT_CALLBACK_URL', f'{orch_http_base}/voice/result')
        topic = _env_get('VOICE_RESULT_TOPIC', '/asr_text')
        timeout_sec = _env_get('VOICE_RESULT_REPORT_TIMEOUT_SEC', '0.5')
        return self.ros._build_bash_cmd(f'python3 "{script_path}" --topic "{topic}" --callback-url "{callback_url}" --timeout-sec {timeout_sec}')
    async def _start_voice_subscriber(self) -> bool:
        cmd = self._build_voice_subscriber_cmd()
        cwd = _env_get_opt('VOICE_SUBSCRIBER_CWD', str(self.project_root))
        return await self.ros.start_command(name=self.PROC_VOICE_SUB, cmd=cmd, cwd=cwd, stream_logs=True, extra_env={})
    async def start_voice(self) -> dict[str, Any]:
        if self.flags.voice_running:
            return self.get_current_voice_session()
        session = self._create_voice_session()
        launch_ok = await self.ros.start_ros2_launch(name=self.voice_cfg.name, package=self.voice_cfg.package, launch_file=self.voice_cfg.launch_file, args=self.voice_cfg.args, cwd=self.voice_cfg.cwd, stream_logs=True, extra_env=self.voice_cfg.env)
        sub_ok = await self._start_voice_subscriber()
        await asyncio.sleep(1.0)
        launch_alive = self.ros.is_running(self.voice_cfg.name)
        sub_alive = self.ros.is_running(self.PROC_VOICE_SUB)
        if not launch_ok or not sub_ok or not launch_alive or not sub_alive:
            await self.ros.stop(self.voice_cfg.name)
            await self.ros.stop(self.PROC_VOICE_SUB)
            self.flags.voice_running = False
            self.voice_store.update_session(session['session_id'], status='error')
            raise RuntimeError(
                "启动语音链路失败。\n"
                f"launch_ok={launch_ok}, sub_ok={sub_ok}, launch_alive={launch_alive}, sub_alive={sub_alive}\n"
                f"最近日志：\n{self._recent_log_block(limit=20, proc_name=self.PROC_VOICE_SUB)}"
            )
        self.flags.voice_running = True
        await self._push_voice_state(True)
        await self._push_voice_diag('语音链路已启动，等待“你好”后的 /asr_text 有效内容。', level='info')
        return self.get_current_voice_session()
    async def stop_voice(self) -> dict[str, Any]:
        await asyncio.gather(self.ros.stop(self.voice_cfg.name), self.ros.stop(self.PROC_VOICE_SUB))
        self.flags.voice_running = False
        session = self._build_empty_voice_session_resp()
        if self.current_voice_session_id:
            session = self.voice_store.close_session(self.current_voice_session_id)
        self.current_voice_session_id = None
        await self._push_voice_state(False)
        return self._voice_session_response(session)
    async def ingest_voice_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get('asr_text') or payload.get('text') or '').strip()
        if not text or not self.flags.voice_running:
            return {}
        if text == self._latest_voice_text:
            return {}
        self._latest_voice_text = text
        session = None
        if self.current_voice_session_id:
            session = self.voice_store.append_sentence(self.current_voice_session_id, text, payload)
            self._voice_records = list(session.get('records') or [])
        if self._push_evt is not None:
            await self._push_evt({
                'type': 'voice_sentence',
                'payload': {
                    'text': text,
                    'session_id': self.current_voice_session_id or '',
                    'records': self._voice_records[-20:],
                },
                'ts': time.time(),
            })
        return session or {'text': text}
    async def convert_voice_text(self, text: str | None = None) -> dict[str, Any]:
        sentence = (text or self._latest_voice_text or '').strip()
        if not sentence:
            raise RuntimeError('当前没有可转化的识别文本')
        result = await self.voice_mapper_service.convert_text(sentence)
        token_text = str(result.get('token_text') or '').strip()
        tokens = list(result.get('tokens') or [])
        self._latest_voice_tokens = token_text
        if self.current_voice_session_id:
            session = self.voice_store.save_convert_result(
                self.current_voice_session_id,
                latest_text=sentence,
                latest_tokens=token_text,
                convert_status=str(result.get('summary_status') or 'done'),
                convert_error=str(result.get('error') or ''),
            )
            self._voice_records = list(session.get('records') or [])
        payload = {
            'session_id': self.current_voice_session_id or '',
            'text': sentence,
            'tokens': tokens,
            'token_text': token_text,
            'convert_status': str(result.get('summary_status') or 'done'),
            'convert_error': str(result.get('error') or ''),
            'records': self._voice_records[-20:],
        }
        if self._push_evt is not None:
            await self._push_evt({'type': 'voice_convert_result', 'payload': payload, 'ts': time.time()})
        return payload
    async def send_voice_tokens(self, token_text: str | None = None) -> dict[str, Any]:
        text = (token_text or self._latest_voice_tokens or '').strip()
        if not text:
            raise RuntimeError('当前没有可发送的转化结果')
        tokens = [part.strip() for part in text.split() if part.strip()]
        mapped = self.voice_mapper_service.map_tokens_to_ids(tokens)
        ids = list(mapped.get('ids') or [])
        missing_tokens = list(mapped.get('missing_tokens') or [])
        send_result = {'accepted': False, 'reason': 'serial_not_bound'}
        send_status = 'failed'
        send_error = ''
        if missing_tokens:
            send_error = '以下词未找到编号映射：' + '、'.join(missing_tokens)
        elif self._serial is None:
            send_error = '串口服务未绑定'
        else:
            send_result = self._serial.enqueue_job(ids)
            send_status = 'queued' if send_result.get('accepted') else 'failed'
            send_error = str(send_result.get('error') or '')
        self._latest_voice_ids = ids
        if self.current_voice_session_id:
            session = self.voice_store.save_send_result(self.current_voice_session_id, latest_ids=ids, send_status=send_status, send_error=send_error, send_result=send_result)
            self._voice_records = list(session.get('records') or [])
        payload = {
            'session_id': self.current_voice_session_id or '',
            'token_text': text,
            'tokens': tokens,
            'ids': ids,
            'missing_tokens': missing_tokens,
            'send_status': send_status,
            'send_error': send_error,
            'send_result': send_result,
            'serial_device_hint': '/dev/ttyUSB*',
            'records': self._voice_records[-20:],
        }
        if self._push_evt is not None:
            await self._push_evt({'type': 'voice_send_result', 'payload': payload, 'ts': time.time()})
        return payload
    async def generate_chat_reply(self, text: str | None = None) -> dict[str, Any]:
        sentence = (text or '').strip()
        if not sentence:
            sign_session = self.get_current_sign_session()
            sentence = str(sign_session.get('summary_text') or sign_session.get('raw_text') or '').strip()
        if not sentence:
            raise RuntimeError('当前没有可用于生成回复的手语句子')
        result = await self.dialog_service.generate_reply(sentence)
        if not result.get('reply_text'):
            raise RuntimeError(str(result.get('error') or '生成回复失败'))
        return result

    async def convert_and_send_chat_text(self, text: str | None = None) -> dict[str, Any]:
        sentence = (text or '').strip()
        if not sentence:
            raise RuntimeError('当前没有可发送到机械臂的 对话回复')
        convert_result = await self.voice_mapper_service.convert_text_to_ids(sentence)
        token_text = str(convert_result.get('token_text') or '').strip()
        ids = list(convert_result.get('ids') or [])
        if not ids:
            raise RuntimeError(str(convert_result.get('error') or '回复转化编号为空'))
        send_result = {'accepted': False, 'reason': 'serial_not_bound'}
        send_status = 'failed'
        send_error = ''
        if self._serial is None:
            send_error = '串口服务未绑定'
        else:
            send_result = self._serial.enqueue_job(ids)
            send_status = 'queued' if send_result.get('accepted') else 'failed'
            send_error = str(send_result.get('error') or '')
        self._latest_voice_tokens = token_text
        self._latest_voice_ids = ids
        return {
            'text': sentence,
            'token_text': token_text,
            'tokens': list(convert_result.get('tokens') or []),
            'number_text': str(convert_result.get('number_text') or ''),
            'convert_status': str(convert_result.get('convert_status') or 'done'),
            'convert_error': str(convert_result.get('error') or ''),
            'ids': ids,
            'missing_tokens': list(convert_result.get('missing_tokens') or []),
            'send_status': send_status,
            'send_error': send_error,
            'send_result': send_result,
            'records': [],
            'session_id': self.current_voice_session_id or '',
        }

    async def start_chat(self) -> bool:
        ok = await self.ros.start_ros2_launch(name=self.chat_cfg.name, package=self.chat_cfg.package, launch_file=self.chat_cfg.launch_file, args=self.chat_cfg.args, cwd=self.chat_cfg.cwd, stream_logs=True, extra_env=self.chat_cfg.env)
        self.flags.chat_running = bool(ok)
        return ok
    async def stop_chat(self) -> bool:
        ok = await self.ros.stop(self.chat_cfg.name)
        self.flags.chat_running = False
        return ok
    async def publish_start_recording(self, enabled: bool, rate_hz: float = 10.0) -> bool:
        if enabled:
            try:
                await self.ros.stop(self.PROC_REC_PUB)
            except Exception:
                pass
            cmd = self.ros._build_bash_cmd(f'ros2 topic pub /start_recording std_msgs/msg/Bool "{{data: true}}" -r {rate_hz}')
            return await self.ros.start_command(name=self.PROC_REC_PUB, cmd=cmd, stream_logs=True)
        try:
            await self.ros.stop(self.PROC_REC_PUB)
        except Exception:
            pass
        cmd = self.ros._build_bash_cmd('ros2 topic pub -1 /start_recording std_msgs/msg/Bool "{data: false}"')
        return await self.ros.start_command(name='pub_start_recording_false_once', cmd=cmd, stream_logs=True)
    async def _stop_session_without_ai(self) -> dict[str, Any]:
        session_id = self.current_sign_session_id
        if not session_id:
            self._reset_sign_session_memory()
            return self._build_empty_session_resp()
        try:
            session = self.sign_store.get_session(session_id)
        except Exception:
            self.current_sign_session_id = None
            self._reset_sign_session_memory()
            return self._build_empty_session_resp()
        words = list(session.get('words') or self._recognized_words)
        raw_text = session.get('raw_text') or self._build_raw_text(words) or EMPTY_SIGN_TEXT
        saved = self.sign_store.update_session(session_id, status='stopped', raw_text=raw_text, summary_text=raw_text, word_count=len(words), summary_status='processing' if raw_text else 'skipped', summary_error='', stopped_at=session.get('stopped_at') or self._now_iso())
        saved['words'] = words
        saved['word_count'] = len(words)
        self.current_sign_session_id = None
        self._reset_sign_session_memory()
        return saved
    def _schedule_word_tts(self, label: str) -> None:
        async def _run() -> None:
            try:
                await self.playback_service.speak_word(label)
            except Exception as exc:
                await self._push_sign_diag(f'实时词语音播报失败：{exc}', level='warning')
        asyncio.create_task(_run(), name=f'tts-word-{label}')
    def _start_sign_summary_background(self, session_id: str) -> None:
        old_task = self._sign_summary_tasks.get(session_id)
        if old_task and not old_task.done():
            return
        task = asyncio.create_task(self._run_sign_summary_in_background(session_id), name=f'sign-summary-{session_id}')
        self._sign_summary_tasks[session_id] = task
        task.add_done_callback(lambda done_task: self._sign_summary_tasks.pop(session_id, None) if self._sign_summary_tasks.get(session_id) is done_task else None)
    async def _run_sign_summary_in_background(self, session_id: str) -> None:
        try:
            session = self.sign_store.get_session(session_id)
        except Exception:
            return
        words = list(session.get('words') or self.sign_store.load_words(session_id))
        raw_text = (session.get('raw_text') or self._build_raw_text(words) or EMPTY_SIGN_TEXT).strip()
        try:
            self.sign_store.mark_summary_processing(session_id, raw_text)
        except Exception as exc:
            await self._push_sign_diag(f'更新 text-processing 处理中状态失败：{exc}', level='warning')
        summary_result = await self.sign_text_service.summarize_sign_text(raw_text)
        summary_ok = bool(summary_result.get('ok'))
        summary_text = str(summary_result.get('summary_text') or raw_text)
        summary_status = str(summary_result.get('summary_status') or ('done' if summary_ok else 'failed'))
        summary_error = str(summary_result.get('error') or '')
        try:
            saved = self.sign_store.save_summary_result(session_id, raw_text=raw_text, summary_text=summary_text, summary_status=summary_status, summary_error=summary_error)
        except Exception as exc:
            saved = {**session, 'session_id': session_id, 'status': 'stopped', 'raw_text': raw_text, 'summary_text': summary_text, 'summary_status': summary_status, 'summary_error': summary_error or f'写回 session 失败：{exc}', 'word_count': len(words)}
        saved['words'] = words
        saved['word_count'] = len(words)
        await self._broadcast_sign_summary_done(saved)
        try:
            spoken_text = summary_text if summary_text and summary_status != 'failed' else raw_text
            if spoken_text and spoken_text != EMPTY_SIGN_TEXT:
                await self.playback_service.speak_summary(spoken_text)
        except Exception as exc:
            await self._push_sign_diag(f'总结语音播报失败：{exc}', level='warning')
    async def _broadcast_sign_summary_done(self, session: dict[str, Any]) -> None:
        if self._push_evt is None:
            return
        payload = {'session_id': session.get('session_id', ''), 'raw_text': session.get('raw_text', ''), 'summary_text': session.get('summary_text', ''), 'summary_status': session.get('summary_status', 'failed'), 'summary_error': session.get('summary_error', ''), 'word_count': int(session.get('word_count') or 0), 'words': list(session.get('words') or [])}
        now = time.time()
        await self._push_evt({'type': 'sign_sentence', 'payload': {'text': payload['summary_text'] or payload['raw_text'] or EMPTY_SIGN_TEXT, 'session_id': payload['session_id'], 'word_count': payload['word_count'], 'summary_status': payload['summary_status']}, 'ts': now})
        await self._push_evt({'type': 'sign_summary_result', 'payload': {'text': payload['summary_text'], 'raw_text': payload['raw_text'], 'session_id': payload['session_id'], 'summary_status': payload['summary_status'], 'summary_error': payload['summary_error']}, 'ts': now})
        await self._push_evt({'type': 'sign_summary_done', 'payload': payload, 'ts': now})
    def get_current_sign_session(self) -> dict[str, Any]:
        session = None
        if self.current_sign_session_id:
            try:
                session = self.sign_store.get_session(self.current_sign_session_id)
            except Exception:
                session = None
        if session is None:
            session = self.sign_store.get_latest_session()
        if session is None:
            return self._build_empty_session_resp()
        words = list(session.get('words') or [])
        raw_text = session.get('raw_text') or self._build_raw_text(words)
        summary_text = session.get('summary_text') or ''
        return {'session_id': session.get('session_id', ''), 'status': session.get('status', 'idle'), 'raw_text': raw_text, 'summary_text': summary_text, 'words': words, 'word_count': int(session.get('word_count') or len(words)), 'summary_status': session.get('summary_status', 'idle'), 'summary_error': session.get('summary_error', '')}
    def get_current_voice_session(self) -> dict[str, Any]:
        session = None
        if self.current_voice_session_id:
            try:
                session = self.voice_store.get_session(self.current_voice_session_id)
            except Exception:
                session = None
        if session is None:
            session = self.voice_store.get_latest_session()
        if session is None:
            return self._build_empty_voice_session_resp()
        return self._voice_session_response(session)
    def _voice_session_response(self, session: dict[str, Any]) -> dict[str, Any]:
        return {
            'session_id': session.get('session_id', ''),
            'status': session.get('status', 'idle'),
            'latest_text': session.get('latest_text', ''),
            'latest_tokens': session.get('latest_tokens', ''),
            'latest_ids': list(session.get('latest_ids') or []),
            'convert_status': session.get('convert_status', 'idle'),
            'convert_error': session.get('convert_error', ''),
            'send_status': session.get('send_status', 'idle'),
            'send_error': session.get('send_error', ''),
            'records': list(session.get('records') or []),
        }
    @staticmethod
    def _build_raw_text(words: list[str]) -> str:
        return SignSessionStore.build_raw_text(words)
    @staticmethod
    def _build_empty_session_resp() -> dict[str, Any]:
        return {'session_id': '', 'status': 'idle', 'raw_text': '', 'summary_text': '', 'words': [], 'word_count': 0, 'summary_status': 'idle', 'summary_error': ''}
    @staticmethod
    def _build_empty_voice_session_resp() -> dict[str, Any]:
        return {'session_id': '', 'status': 'idle', 'latest_text': '', 'latest_tokens': '', 'latest_ids': [], 'convert_status': 'idle', 'convert_error': '', 'send_status': 'idle', 'send_error': '', 'records': []}
    @staticmethod
    def _now_iso() -> str:
        return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())
