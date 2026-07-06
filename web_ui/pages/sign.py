"""SIGN 页面。"""

from __future__ import annotations

from nicegui import ui

from web_ui.components import page_container, section_card, togetheros_native_video_component


async def build_sign(app_ctx) -> None:
    """构建手语识别页面。"""
    state = app_ctx.state
    api = app_ctx.api

    async def toggle_kp() -> None:
        try:
            state.add_log(
                f"准备切换 KP，当前 kp_running={state.kp_running}, sign_running={state.sign_running}"
            )
            if state.kp_running:
                resp = await api.stop_kp()
                state.add_log(f"KP stop response: {resp}")
            else:
                resp = await api.start_kp()
                state.add_log(f"KP start response: {resp}")
        except Exception as exc:
            msg = str(exc).strip() or "未知错误"
            state.add_log(f"KP toggle failed: {msg}")
            ui.notify(f"关键点控制失败：{msg[:120]}", type="negative")

    async def toggle_sign() -> None:
        state.add_log(
            f"准备切换手语识别，当前 sign_running={state.sign_running}, "
            f"kp_running={state.kp_running}, mode={state.sign_mode}"
        )
        try:
            if state.sign_running:
                resp = await api.stop_sign()
                state.add_log(f"SIGN stop response: {resp}")
            else:
                resp = await api.start_sign(state.sign_mode)
                state.add_log(f"SIGN start response: {resp}")
        except Exception as exc:
            msg = str(exc).strip() or "未知错误"
            state.add_log(f"SIGN toggle failed: {msg}")
            ui.notify(f"手语识别控制失败：{msg[:120]}", type="negative")
            state.sign_running = False

    with page_container():
        with ui.row().classes("w-full items-stretch gap-4 max-[1280px]:flex-wrap no-wrap"):
            with section_card(
                "实时视频",
                "启动关键点后会同时拉起识别节点；只有点击“启动手语识别”后才开始录入和展示结果。",
            ).classes("flex-[1.1] min-w-0 h-[calc(100vh-118px)] max-[1280px]:h-[54vh] max-[900px]:h-auto"):
                togetheros_native_video_component(
                    preview_base_url=app_ctx.settings.preview_url,
                    ws_url=app_ctx.settings.resolved_togetheros_ws_url(),
                    proto_url=app_ctx.settings.togetheros_proto_url,
                    filter_prefix=app_ctx.settings.resolved_togetheros_filter_prefix(),
                    title="SIGN 实时画面",
                    enable_overlay=False,
                )

            with section_card(
                "识别结果与整理输出",
                "右半侧展示实时识别词、识别句段和关闭翻译后的 文本整理结果。",
            ).classes("flex-[0.95] min-w-0 h-[calc(100vh-118px)] max-[1280px]:h-auto"):
                with ui.grid(columns=2).classes("w-full gap-3"):
                    kp_button = ui.button("启动关键点", on_click=toggle_kp).props("unelevated color=primary").classes("w-full action-btn")
                    sign_button = ui.button("启动手语识别", on_click=toggle_sign).props("unelevated color=secondary").classes("w-full action-btn")
                with ui.row().classes("w-full gap-2 flex-wrap"):
                    kp_chip = ui.label("KP 未启动").classes("status-chip")
                    sign_chip = ui.label("识别未启动").classes("status-chip")
                status_label = ui.label("等待后端事件...").classes("text-sm text-slate-300")
                session_label = ui.label("Session: -").classes("text-xs text-slate-400 break-all")
                summary_error_label = ui.label("").classes("text-xs text-amber-300 whitespace-pre-wrap break-all")

                with ui.element("div").classes("info-tile w-full"):
                    ui.label("实时拼接结果").classes("text-xs text-slate-400")
                    sentence_label = ui.label("—").classes("text-xl text-cyan-300 whitespace-pre-wrap leading-8 break-words")

                with ui.element("div").classes("info-tile w-full"):
                    ui.label("文本整理输出").classes("text-xs text-slate-400")
                    ai_label = ui.label("—").classes("text-base text-slate-100 whitespace-pre-wrap leading-7 break-words")

                ui.label("识别词流").classes("text-sm font-semibold text-slate-200")
                words_column = ui.column().classes("chat-panel w-full flex-1 min-h-0 overflow-auto gap-3 pr-1")

                ui.separator().classes("w-full opacity-20 my-1")
                ui.label("运行日志").classes("text-sm font-semibold text-slate-200")
                log_area = ui.column().classes("log-panel w-full h-[160px] overflow-auto gap-2 pr-1")

        async def refresh_ui() -> None:
            kp_button.set_text("停止关键点" if state.kp_running else "启动关键点")
            sign_button.set_text("关闭手语翻译" if state.sign_running else "启动手语识别")
            kp_chip.set_text(f"KP {'运行中' if state.kp_running else '未启动'}")
            sign_chip.set_text(f"识别 {'运行中' if state.sign_running else '未启动'}")
            sentence_label.set_text(state.latest_sign_sentence or state.latest_sign_word or '—')
            ai_label.set_text(state.latest_sign_summary or '—')
            status_label.set_text(
                f"模式：{state.sign_mode} | KP：{'运行中' if state.kp_running else '已停止'} | "
                f"识别：{'运行中' if state.sign_running else '已停止'} | "
                f"当前词数：{len(state.recognized_sign_words)} | text-processing：{state.sign_summary_status}"
            )
            session_label.set_text(
                f"Session: {state.current_sign_session_id or '-'} | 状态: {state.current_sign_status or 'idle'}"
            )
            summary_error_label.set_text(f"整理错误：{state.sign_summary_error}" if state.sign_summary_error else "")

            words_column.clear()
            words = state.recognized_sign_words[-24:]
            with words_column:
                if not words:
                    with ui.element("div").classes("chat-ai max-w-[96%]"):
                        ui.label("提示").classes("text-xs text-slate-400")
                        ui.label(
                            "点击“启动手语识别”后，识别到的词会从这里开始依次显示。关闭翻译后会自动进行 文本整理。\n"
                        ).classes("whitespace-pre-wrap leading-6")
                else:
                    for idx, word in enumerate(words, start=max(1, len(state.recognized_sign_words) - len(words) + 1)):
                        with ui.row().classes("w-full justify-start"):
                            with ui.element("div").classes("chat-user max-w-[92%]"):
                                ui.label(f"词 {idx}").classes("text-xs text-slate-400")
                                ui.label(word).classes("whitespace-pre-wrap leading-6")

            log_area.clear()
            with log_area:
                for item in state.logs[-12:]:
                    with ui.element("div").classes("info-tile w-full"):
                        ui.label(item).classes("text-xs text-slate-300 break-all leading-5")

        ui.timer(0.6, refresh_ui, immediate=True)
