from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Literal, Any, Dict

Mode = Literal["SIGN", "VOICE", "CHAT"]


class ModeSelectReq(BaseModel):
    mode: Mode


class ModeSelectResp(BaseModel):
    ok: bool = True
    mode: Mode
    request_id: str


SignMode = Literal["WORD", "SENTENCE"]


class SignStartReq(BaseModel):
    mode: SignMode = "SENTENCE"


class SignModeSelectReq(BaseModel):
    mode: SignMode = "WORD"


class SignModeSelectResp(BaseModel):
    ok: bool = True
    mode: SignMode
    request_id: str


class SignResultIngestReq(BaseModel):
    model_config = ConfigDict(extra="allow")
    label: str = ""
    confidence: float | None = None
    frame_timestamp_ns: int | None = None
    segment: Dict[str, Any] = Field(default_factory=dict)


class SignSessionResp(BaseModel):
    ok: bool = True
    request_id: str
    session_id: str = ""
    status: str = "idle"
    raw_text: str = ""
    summary_text: str = ""
    words: List[str] = Field(default_factory=list)
    word_count: int = 0
    summary_status: str = "idle"
    summary_error: str = ""


class VoiceResultIngestReq(BaseModel):
    model_config = ConfigDict(extra="allow")
    asr_text: str = ""
    topic: str = "/asr_text"
    received_at: float | None = None


class VoiceConvertReq(BaseModel):
    text: str = ""


class VoiceSendReq(BaseModel):
    token_text: str = ""


class VoiceSessionResp(BaseModel):
    ok: bool = True
    request_id: str
    session_id: str = ""
    status: str = "idle"
    latest_text: str = ""
    latest_tokens: str = ""
    latest_ids: List[int] = Field(default_factory=list)
    convert_status: str = "idle"
    convert_error: str = ""
    send_status: str = "idle"
    send_error: str = ""
    records: List[Dict[str, Any]] = Field(default_factory=list)


class BasicResp(BaseModel):
    ok: bool = True
    request_id: str


class EnqueueJobReq(BaseModel):
    ids: List[int] = Field(default_factory=list)


class EnqueueJobResp(BaseModel):
    ok: bool = True
    job_id: str
    request_id: str


class StopAllResp(BaseModel):
    ok: bool = True
    request_id: str


class StateResp(BaseModel):
    ok: bool = True
    request_id: str
    mode: Mode
    sign_mode: SignMode
    serial: Dict[str, Any]


class SystemInfoResp(BaseModel):
    ok: bool = True
    request_id: str
    ip: str
    preview_url: str


class RosLaunchStartReq(BaseModel):
    name: str = Field(..., description="Logical process name")
    package: str
    launch_file: str
    args: List[str] = Field(default_factory=list)
    cwd: Optional[str] = None


class RosLaunchStopReq(BaseModel):
    name: str


class RosLaunchListResp(BaseModel):
    ok: bool = True
    request_id: str
    running: Dict[str, bool] = Field(default_factory=dict)


class RosBoolPubReq(BaseModel):
    topic: str
    value: bool


class RosParamSetReq(BaseModel):
    node: str
    param: str
    value: Any


class ChatGenerateReq(BaseModel):
    text: str = ""


class ChatDisplayReq(BaseModel):
    text: str = ""


class ChatSendResp(BaseModel):
    ok: bool = True
    request_id: str
    text: str = ""
    token_text: str = ""
    ids: List[int] = Field(default_factory=list)
    send_status: str = "idle"
    send_error: str = ""
    missing_tokens: List[str] = Field(default_factory=list)
    send_result: Dict[str, Any] = Field(default_factory=dict)
