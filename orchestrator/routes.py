from __future__ import annotations

import logging
import os
import time

from fastapi import APIRouter, HTTPException, Request

from models.schemas import (
    BasicResp,
    ChatDisplayReq,
    ChatGenerateReq,
    ChatSendResp,
    EnqueueJobReq,
    EnqueueJobResp,
    ModeSelectReq,
    ModeSelectResp,
    RosBoolPubReq,
    RosLaunchListResp,
    RosLaunchStartReq,
    RosLaunchStopReq,
    RosParamSetReq,
    SignModeSelectReq,
    SignModeSelectResp,
    SignResultIngestReq,
    SignSessionResp,
    SignStartReq,
    StateResp,
    StopAllResp,
    SystemInfoResp,
    VoiceConvertReq,
    VoiceResultIngestReq,
    VoiceSendReq,
    VoiceSessionResp,
)
from utils.net import build_preview_url, detect_local_ipv4

logger = logging.getLogger("orchestrator.routes")
router = APIRouter()


def _ts() -> float:
    return time.time()


@router.post("/mode/select", response_model=ModeSelectResp)
async def mode_select(req: ModeSelectReq, request: Request):
    app_state = request.app.state
    request_id = request.state.request_id
    app_state.current_mode = req.mode
    await app_state.ws.broadcast({"type": "mode_changed", "ts": _ts(), "request_id": request_id, "payload": {"mode": req.mode}})
    return ModeSelectResp(mode=req.mode, request_id=request_id)


@router.post("/kp/start", response_model=BasicResp)
async def kp_start(request: Request):
    app_state = request.app.state
    request_id = request.state.request_id
    try:
        ok = await app_state.tasks.start_kp()
    except Exception as exc:
        await app_state.ws.broadcast({"type": "kp_state", "ts": _ts(), "request_id": request_id, "payload": {"running": False}})
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    await app_state.ws.broadcast({"type": "kp_state", "ts": _ts(), "request_id": request_id, "payload": {"running": bool(ok and app_state.tasks.flags.kp_running)}})
    return BasicResp(request_id=request_id)


@router.post("/kp/stop", response_model=BasicResp)
async def kp_stop(request: Request):
    app_state = request.app.state
    request_id = request.state.request_id
    await app_state.tasks.stop_sign_and_kp()
    await app_state.ws.broadcast({"type": "sign_state", "ts": _ts(), "request_id": request_id, "payload": {"running": False}})
    await app_state.ws.broadcast({"type": "kp_state", "ts": _ts(), "request_id": request_id, "payload": {"running": False}})
    return BasicResp(request_id=request_id)


@router.post("/sign/mode/select", response_model=SignModeSelectResp)
async def sign_mode_select(req: SignModeSelectReq, request: Request):
    app_state = request.app.state
    request_id = request.state.request_id
    app_state.current_sign_mode = req.mode
    await app_state.ws.broadcast({"type": "sign_mode_changed", "ts": _ts(), "request_id": request_id, "payload": {"mode": req.mode}})
    return SignModeSelectResp(mode=req.mode, request_id=request_id)


@router.get("/sign/mode", response_model=SignModeSelectResp)
async def sign_mode_get(request: Request):
    return SignModeSelectResp(mode=request.app.state.current_sign_mode, request_id=request.state.request_id)


@router.post("/sign/result", response_model=BasicResp)
async def sign_result_ingest(req: SignResultIngestReq, request: Request):
    await request.app.state.tasks.ingest_sign_result(req.model_dump())
    return BasicResp(request_id=request.state.request_id)


@router.get("/sign/session/current", response_model=SignSessionResp)
async def sign_session_current(request: Request):
    session = request.app.state.tasks.get_current_sign_session()
    return SignSessionResp(request_id=request.state.request_id, **session)


@router.post("/sign_iso/start", response_model=BasicResp)
async def sign_iso_start(request: Request):
    await request.app.state.tasks.start_sign_iso()
    await request.app.state.ws.broadcast({"type": "iso_state", "ts": _ts(), "request_id": request.state.request_id, "payload": {"running": True}})
    return BasicResp(request_id=request.state.request_id)


@router.post("/sign_iso/stop", response_model=BasicResp)
async def sign_iso_stop(request: Request):
    await request.app.state.tasks.stop_sign()
    await request.app.state.ws.broadcast({"type": "iso_state", "ts": _ts(), "request_id": request.state.request_id, "payload": {"running": False}})
    return BasicResp(request_id=request.state.request_id)


@router.post("/sign/start", response_model=BasicResp)
async def sign_start(req: SignStartReq, request: Request):
    app_state = request.app.state
    request_id = request.state.request_id
    app_state.current_sign_mode = req.mode
    try:
        ok = await app_state.tasks.start_sign(req.mode)
    except Exception as exc:
        await app_state.ws.broadcast({"type": "sign_state", "ts": _ts(), "request_id": request_id, "payload": {"running": False, "mode": req.mode}})
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    current_session = app_state.tasks.get_current_sign_session()
    await app_state.ws.broadcast({"type": "sign_session_reset", "ts": _ts(), "request_id": request_id, "payload": {"mode": req.mode, "session_id": current_session.get("session_id", ""), "summary_status": current_session.get("summary_status", "pending")}})
    await app_state.ws.broadcast({"type": "sign_state", "ts": _ts(), "request_id": request_id, "payload": {"running": bool(ok), "mode": req.mode, "session_id": current_session.get("session_id", "")}})
    return BasicResp(request_id=request_id)


@router.post("/sign/stop", response_model=SignSessionResp)
async def sign_stop(request: Request):
    app_state = request.app.state
    request_id = request.state.request_id
    summary = await app_state.tasks.stop_sign()
    await app_state.ws.broadcast({"type": "sign_state", "ts": _ts(), "request_id": request_id, "payload": {"running": False, "session_id": summary.get("session_id", "")}})
    await app_state.ws.broadcast({"type": "sign_sentence", "ts": _ts(), "request_id": request_id, "payload": {"text": summary.get("raw_text", ""), "session_id": summary.get("session_id", ""), "word_count": summary.get("word_count", 0), "summary_status": summary.get("summary_status", "processing")}})
    await app_state.ws.broadcast({"type": "sign_summary_result", "ts": _ts(), "request_id": request_id, "payload": {"text": summary.get("summary_text", ""), "raw_text": summary.get("raw_text", ""), "session_id": summary.get("session_id", ""), "summary_status": summary.get("summary_status", "processing"), "summary_error": summary.get("summary_error", "")}})
    return SignSessionResp(request_id=request_id, **summary)


@router.post("/voice/start", response_model=VoiceSessionResp)
async def voice_start(request: Request):
    try:
        session = await request.app.state.tasks.start_voice()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return VoiceSessionResp(request_id=request.state.request_id, **session)


@router.post("/voice/stop", response_model=VoiceSessionResp)
async def voice_stop(request: Request):
    session = await request.app.state.tasks.stop_voice()
    return VoiceSessionResp(request_id=request.state.request_id, **session)


@router.post("/voice/result", response_model=BasicResp)
async def voice_result_ingest(req: VoiceResultIngestReq, request: Request):
    await request.app.state.tasks.ingest_voice_result(req.model_dump())
    return BasicResp(request_id=request.state.request_id)


@router.post("/voice/convert", response_model=VoiceSessionResp)
async def voice_convert(req: VoiceConvertReq, request: Request):
    try:
        result = await request.app.state.tasks.convert_voice_text(req.text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    session = request.app.state.tasks.get_current_voice_session()
    session.update({
        'latest_text': result.get('text', session.get('latest_text', '')),
        'latest_tokens': result.get('token_text', session.get('latest_tokens', '')),
        'convert_status': result.get('convert_status', session.get('convert_status', 'done')),
        'convert_error': result.get('convert_error', session.get('convert_error', '')),
        'records': result.get('records', session.get('records', [])),
    })
    return VoiceSessionResp(request_id=request.state.request_id, **session)


@router.post("/voice/send", response_model=VoiceSessionResp)
async def voice_send(req: VoiceSendReq, request: Request):
    try:
        result = await request.app.state.tasks.send_voice_tokens(req.token_text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    session = request.app.state.tasks.get_current_voice_session()
    session.update({
        'latest_ids': result.get('ids', session.get('latest_ids', [])),
        'send_status': result.get('send_status', session.get('send_status', 'queued')),
        'send_error': result.get('send_error', session.get('send_error', '')),
        'records': result.get('records', session.get('records', [])),
    })
    return VoiceSessionResp(request_id=request.state.request_id, **session)


@router.get("/voice/session/current", response_model=VoiceSessionResp)
async def voice_session_current(request: Request):
    session = request.app.state.tasks.get_current_voice_session()
    return VoiceSessionResp(request_id=request.state.request_id, **session)


@router.post("/chat/generate", response_model=BasicResp)
async def chat_generate(req: ChatGenerateReq, request: Request):
    app_state = request.app.state
    try:
        result = await app_state.tasks.generate_chat_reply(req.text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user_text = str(result.get('user_text') or req.text or '').strip()
    reply_text = str(result.get('reply_text') or '').strip()
    await app_state.ws.broadcast({
        "type": "chat_translation",
        "ts": _ts(),
        "request_id": request.state.request_id,
        "payload": {"text": user_text},
    })
    await app_state.ws.broadcast({
        "type": "chat_reply",
        "ts": _ts(),
        "request_id": request.state.request_id,
        "payload": {
            "user": user_text,
            "ai": reply_text,
            "token_text": str(result.get('reply_token_text') or reply_text),
            "tokens": list(result.get('reply_tokens') or []),
            "summary_status": str(result.get('summary_status') or 'done'),
            "summary_error": str(result.get('error') or ''),
            "raw_reply": str(result.get('raw_reply') or ''),
        },
    })
    return BasicResp(request_id=request.state.request_id)


@router.post("/chat/display/text", response_model=BasicResp)
async def chat_display_text(req: ChatDisplayReq, request: Request):
    await request.app.state.ws.broadcast({"type": "chat_display_text", "ts": _ts(), "request_id": request.state.request_id, "payload": {"text": req.text}})
    return BasicResp(request_id=request.state.request_id)


@router.post("/chat/display/arm", response_model=ChatSendResp)
async def chat_display_arm(req: ChatDisplayReq, request: Request):
    app_state = request.app.state
    try:
        result = await app_state.tasks.convert_and_send_chat_text(req.text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload = {
        "text": str(result.get('text') or ''),
        "token_text": str(result.get('token_text') or ''),
        "ids": list(result.get('ids') or []),
        "send_status": str(result.get('send_status') or 'failed'),
        "send_error": str(result.get('send_error') or ''),
        "missing_tokens": list(result.get('missing_tokens') or []),
        "send_result": result.get('send_result') or {},
    }
    await app_state.ws.broadcast({"type": "chat_display_arm", "ts": _ts(), "request_id": request.state.request_id, "payload": payload})
    return ChatSendResp(request_id=request.state.request_id, **payload)


@router.post("/jobs/enqueue", response_model=EnqueueJobResp)
async def jobs_enqueue(req: EnqueueJobReq, request: Request):
    app_state = request.app.state
    result = app_state.serial.enqueue_job(req.ids)
    job_id = result.get("job_id")
    await app_state.ws.broadcast({"type": "job_enqueued", "ts": _ts(), "request_id": request.state.request_id, "job_id": job_id, "payload": {"ids": req.ids, "serial": result}})
    return EnqueueJobResp(job_id=job_id, request_id=request.state.request_id)


@router.post("/jobs/stop_all", response_model=StopAllResp)
async def jobs_stop_all(request: Request):
    app_state = request.app.state
    result = app_state.serial.stop_all()
    await app_state.ws.broadcast({"type": "job_stopped", "ts": _ts(), "request_id": request.state.request_id, "payload": {"serial": result}})
    return StopAllResp(request_id=request.state.request_id)


@router.post("/ros/launch/start", response_model=BasicResp)
async def ros_launch_start(req: RosLaunchStartReq, request: Request):
    await request.app.state.tasks.ros.start_ros2_launch(req.name, req.package, req.launch_file, args=req.args, cwd=req.cwd, stream_logs=True)
    await request.app.state.ws.broadcast({"type": "ros_launch_state", "ts": _ts(), "request_id": request.state.request_id, "payload": {"name": req.name, "running": request.app.state.tasks.ros.is_running(req.name)}})
    return BasicResp(request_id=request.state.request_id)


@router.post("/ros/launch/stop", response_model=BasicResp)
async def ros_launch_stop(req: RosLaunchStopReq, request: Request):
    await request.app.state.tasks.ros.stop(req.name)
    await request.app.state.ws.broadcast({"type": "ros_launch_state", "ts": _ts(), "request_id": request.state.request_id, "payload": {"name": req.name, "running": request.app.state.tasks.ros.is_running(req.name)}})
    return BasicResp(request_id=request.state.request_id)


@router.get("/ros/launch/list", response_model=RosLaunchListResp)
async def ros_launch_list(request: Request):
    names = request.app.state.tasks.ros.list()
    return RosLaunchListResp(request_id=request.state.request_id, running={name: True for name in names})


@router.post("/ros/topic/pub_bool", response_model=BasicResp)
async def ros_topic_pub_bool(req: RosBoolPubReq, request: Request):
    await request.app.state.ws.broadcast({"type": "ros_topic_pub_bool", "ts": _ts(), "request_id": request.state.request_id, "payload": {"topic": req.topic, "value": req.value}})
    return BasicResp(request_id=request.state.request_id)


@router.post("/ros/param/set", response_model=BasicResp)
async def ros_param_set(req: RosParamSetReq, request: Request):
    await request.app.state.ws.broadcast({"type": "ros_param_set", "ts": _ts(), "request_id": request.state.request_id, "payload": {"node": req.node, "param": req.param, "value": req.value}})
    return BasicResp(request_id=request.state.request_id)


@router.get("/system/info", response_model=SystemInfoResp)
async def system_info(request: Request):
    explicit_preview_url = os.getenv("PREVIEW_URL", "").strip()
    ip = detect_local_ipv4()
    preview_url = explicit_preview_url if explicit_preview_url else build_preview_url(ip, port=8000)
    return SystemInfoResp(request_id=request.state.request_id, ip=ip, preview_url=preview_url)


@router.get("/state", response_model=StateResp)
async def state(request: Request):
    app_state = request.app.state
    serial_state = app_state.serial.get_state()
    return StateResp(request_id=request.state.request_id, mode=app_state.current_mode, sign_mode=app_state.current_sign_mode, serial=serial_state)
