"""CHAT 页面。"""

from __future__ import annotations

from nicegui import ui

from web_ui.components import page_container, section_card, togetheros_native_video_component


async def build_chat(app_ctx) -> None:
    """构建手语对话页面。"""
    state = app_ctx.state
    api = app_ctx.api

    async def toggle_kp() -> None:
        try:
            if state.kp_running:
                await api.stop_kp()
                state.kp_running = False
                state.sign_running = False
            else:
                await api.start_kp()
                state.kp_running = True
            state.add_log(f"CHAT KP -> {state.kp_running}")
        except Exception as exc:
            state.add_log(f"CHAT KP failed: {exc}")
            ui.notify(f"关键点控制失败：{exc}", type="negative")

    async def toggle_sign() -> None:
        try:
            if state.sign_running:
                await api.stop_sign()
                state.sign_running = False
            else:
                await api.start_sign(state.sign_mode)
                state.sign_running = True
            state.add_log(f"CHAT sign -> {state.sign_running}")
        except Exception as exc:
            state.add_log(f"CHAT sign failed: {exc}")
            ui.notify(f"手语识别控制失败：{exc}", type="negative")

    async def generate_reply() -> None:
        try:
            source_text = (state.latest_sign_summary or '').strip()
            if not source_text or source_text == '—':
                source_text = (state.latest_sign_sentence or '').strip()
            if not source_text or source_text == '—':
                raise ValueError('当前没有可用于生成回复的手语句子')
            await api.generate_chat(source_text)
            state.add_log(f"CHAT generate requested: {source_text}")
        except Exception as exc:
            state.add_log(f"CHAT generate failed: {exc}")
            ui.notify(f"生成回复失败：{exc}", type="negative")

    async def display_arm() -> None:
        try:
            text = (state.latest_chat_reply or '').strip()
            if not text or text == '—':
                raise ValueError('当前没有可发送到机械臂的 对话回复')
            result = await api.chat_display_arm(text)
            token_text = str(result.get('token_text') or '').strip()
            ids = list(result.get('ids') or [])
            state.latest_chat_tokens = token_text or state.latest_chat_tokens
            state.latest_chat_ids = ids
            state.chat_send_status = str(result.get('send_status') or state.chat_send_status)
            state.chat_send_error = str(result.get('send_error') or '')
            state.latest_arm_display = f"tokens: {token_text or '—'}\nids: {ids or '[]'}\nserial_status: {state.chat_send_status}"
            ui.notify('已发送到机械臂显示通道', type='positive')
        except Exception as exc:
            state.add_log(f"CHAT display arm failed: {exc}")
            ui.notify(f"机械臂显示失败：{exc}", type="negative")

    with page_container():
        with ui.row().classes("w-full items-stretch gap-4 max-[1380px]:flex-wrap no-wrap"):
            with ui.column().classes("w-[24%] min-w-[340px] max-w-[430px] shrink-0 gap-4 max-[1380px]:w-full max-[1380px]:max-w-none"):
                with section_card("对话控制台", "先生成自然完整回复，再在机械臂展示时转成编号并通过串口发送").classes("h-[calc(100vh-118px)] max-[1380px]:h-auto"):
                    with ui.grid(columns=2).classes("w-full gap-3"):
                        kp_button = ui.button("启动关键点", on_click=toggle_kp).props("unelevated color=primary").classes("w-full action-btn")
                        sign_button = ui.button("启动手语识别", on_click=toggle_sign).props("unelevated color=secondary").classes("w-full action-btn")
                        ui.button("生成回复", on_click=generate_reply).props("unelevated color=accent").classes("w-full action-btn")
                        ui.button("机械臂显示", on_click=display_arm).props("outline color=orange").classes("w-full action-btn")
                    ui.separator().classes("w-full opacity-20 my-1")
                    with ui.row().classes("w-full gap-2 flex-wrap"):
                        kp_chip = ui.label("KP 未启动").classes("status-chip")
                        sign_chip = ui.label("识别未启动").classes("status-chip")
                    with ui.element("div").classes("info-tile w-full"):
                        ui.label("手语翻译整理句子").classes("text-xs text-slate-400")
                        translation_label = ui.label("—").classes("text-lg text-cyan-300 whitespace-pre-wrap leading-7")
                    with ui.element("div").classes("info-tile w-full"):
                        ui.label("对话回复").classes("text-xs text-slate-400")
                        ai_label = ui.label("—").classes("text-base text-slate-100 whitespace-pre-wrap leading-7")
                    with ui.element("div").classes("info-tile w-full mt-auto"):
                        ui.label("机械臂发送结果").classes("text-xs text-slate-400")
                        arm_display_label = ui.label("—").classes("text-sm text-orange-300 whitespace-pre-wrap leading-6")

            with section_card("实时视频", "前端原生 websocket 视频接收，不再嵌入官方 HTML 页面").classes("flex-[1.35] min-w-0 h-[calc(100vh-118px)] max-[1380px]:h-[54vh] max-[900px]:h-auto"):
                togetheros_native_video_component(
                    preview_base_url=app_ctx.settings.preview_url,
                    ws_url=app_ctx.settings.resolved_togetheros_ws_url(),
                    proto_url=app_ctx.settings.togetheros_proto_url,
                    filter_prefix=app_ctx.settings.resolved_togetheros_filter_prefix(),
                    title="CHAT 实时画面",
                    enable_overlay=False,
                )

            with section_card("聊天记录", "更大的消息区域，减少空白并提升可读性").classes("flex-[1.05] min-w-0 h-[calc(100vh-118px)] max-[1380px]:h-[54vh] max-[900px]:h-auto"):
                chat_column = ui.column().classes("chat-panel w-full flex-1 min-h-0 overflow-auto gap-3 pr-1")

        async def refresh_ui() -> None:
            kp_button.set_text("停止关键点" if state.kp_running else "启动关键点")
            sign_button.set_text("停止手语识别" if state.sign_running else "启动手语识别")
            kp_chip.set_text(f"KP {'运行中' if state.kp_running else '未启动'}")
            sign_chip.set_text(f"识别 {'运行中' if state.sign_running else '未启动'}")
            translation_label.set_text(state.latest_chat_translation or state.latest_sign_sentence or state.latest_sign_word or '—')
            ai_label.set_text(state.latest_chat_reply or '—')
            ids_text = ' '.join(str(v) for v in state.latest_chat_ids) if state.latest_chat_ids else '—'
            send_error = f"\nerror: {state.chat_send_error}" if state.chat_send_error else ''
            arm_display_label.set_text(
                f"tokens: {state.latest_chat_tokens or '—'}\nids: {ids_text}\nstatus: {state.chat_send_status or 'idle'}{send_error}"
            )
            chat_column.clear()
            for item in state.chat_messages[-24:]:
                css_class = "chat-user" if item.get("role") == "user" else "chat-ai"
                with chat_column:
                    with ui.row().classes("w-full"):
                        align = "justify-start" if item.get("role") == "user" else "justify-end"
                        with ui.row().classes(f"w-full {align}"):
                            with ui.element("div").classes(css_class + " max-w-[92%]"):
                                ui.label("用户" if item.get("role") == "user" else "text-processing").classes("text-xs text-slate-400")
                                ui.label(item.get("text") or "—").classes("whitespace-pre-wrap leading-6")

        ui.timer(1.0, refresh_ui, immediate=True)
