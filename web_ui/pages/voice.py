"""VOICE 页面。"""

from __future__ import annotations

from nicegui import ui

from web_ui.components import page_container, section_card


async def build_voice(app_ctx) -> None:
    state = app_ctx.state
    api = app_ctx.api

    async def toggle_voice() -> None:
        try:
            if state.voice_running:
                resp = await api.stop_voice()
                state.add_log(f"VOICE stop response: {resp}")
            else:
                resp = await api.start_voice()
                state.add_log(f"VOICE start response: {resp}")
        except Exception as exc:
            msg = str(exc).strip() or '未知错误'
            state.add_log(f'VOICE toggle failed: {msg}')
            ui.notify(f'语音链路控制失败：{msg[:120]}', type='negative')

    async def convert_voice() -> None:
        try:
            resp = await api.convert_voice(state.latest_voice_text if state.latest_voice_text != '—' else '')
            state.add_log(f'VOICE convert response: {resp}')
        except Exception as exc:
            msg = str(exc).strip() or '未知错误'
            state.add_log(f'VOICE convert failed: {msg}')
            ui.notify(f'转化失败：{msg[:120]}', type='negative')

    async def send_voice() -> None:
        try:
            resp = await api.send_voice(state.latest_voice_tokens if state.latest_voice_tokens != '—' else '')
            state.add_log(f'VOICE send response: {resp}')
        except Exception as exc:
            msg = str(exc).strip() or '未知错误'
            state.add_log(f'VOICE send failed: {msg}')
            ui.notify(f'发送失败：{msg[:120]}', type='negative')

    with page_container():
        with ui.row().classes('w-full items-stretch gap-4 max-[1280px]:flex-wrap no-wrap'):
            with section_card('语音翻译控制台', '开始语音后将统一启动 sensevoice launch 与 /asr_text 订阅节点；识别、转化、发送都由 orchestrator 统一编排。').classes('flex-[0.95] min-w-0 h-[calc(100vh-118px)] max-[1280px]:h-auto'):
                with ui.column().classes('w-full gap-3'):
                    voice_button = ui.button('开始语音', on_click=toggle_voice).props('unelevated color=primary').classes('w-full action-btn text-lg')
                    with ui.grid(columns=2).classes('w-full gap-3'):
                        convert_button = ui.button('转化', on_click=convert_voice).props('unelevated color=secondary').classes('w-full action-btn')
                        send_button = ui.button('发送', on_click=send_voice).props('outline color=primary').classes('w-full action-btn')
                    with ui.row().classes('w-full gap-2 flex-wrap'):
                        voice_chip = ui.label('语音未启动').classes('status-chip')
                        convert_chip = ui.label('转化 idle').classes('status-chip')
                        send_chip = ui.label('发送 idle').classes('status-chip')
                status_label = ui.label('等待后端事件...').classes('text-sm text-slate-300')
                session_label = ui.label('Session: -').classes('text-xs text-slate-400 break-all')
                error_label = ui.label('').classes('text-xs text-amber-300 whitespace-pre-wrap break-all')
                with ui.element('div').classes('info-tile w-full'):
                    ui.label('最新识别文本').classes('text-xs text-slate-400')
                    latest_text_label = ui.label('—').classes('text-xl text-cyan-300 whitespace-pre-wrap leading-8 break-words')
                with ui.element('div').classes('info-tile w-full'):
                    ui.label('转化后的孤立词结果').classes('text-xs text-slate-400')
                    token_label = ui.label('—').classes('text-base text-slate-100 whitespace-pre-wrap leading-7 break-words')
                with ui.element('div').classes('info-tile w-full'):
                    ui.label('发送编号结果').classes('text-xs text-slate-400')
                    ids_label = ui.label('—').classes('text-base text-emerald-300 whitespace-pre-wrap leading-7 break-words')
                ui.separator().classes('w-full opacity-20 my-1')
                ui.label('运行日志').classes('text-sm font-semibold text-slate-200')
                log_area = ui.column().classes('log-panel w-full h-[180px] overflow-auto gap-2 pr-1')

            with section_card('历史记录', '展示每次收到的识别句子、转化结果和发送编号。').classes('flex-[1.05] min-w-0 h-[calc(100vh-118px)] max-[1280px]:h-auto'):
                records_column = ui.column().classes('history-panel w-full flex-1 min-h-0 overflow-auto gap-3 pr-1')

        async def refresh_ui() -> None:
            voice_button.set_text('结束语音' if state.voice_running else '开始语音')
            voice_chip.set_text(f"语音 {'运行中' if state.voice_running else '未启动'}")
            convert_chip.set_text(f'转化 {state.voice_convert_status}')
            send_chip.set_text(f'发送 {state.voice_send_status}')
            latest_text_label.set_text(state.latest_voice_text or '—')
            token_label.set_text(state.latest_voice_tokens or '—')
            ids_label.set_text(' '.join(str(i) for i in state.latest_voice_ids) if state.latest_voice_ids else '—')
            status_label.set_text(
                f"语音：{'运行中' if state.voice_running else '已停止'} | 转化：{state.voice_convert_status} | 发送：{state.voice_send_status} | 历史条数：{len(state.voice_records)}"
            )
            session_label.set_text(f"Session: {state.current_voice_session_id or '-'} | 状态: {state.current_voice_status or 'idle'}")
            errors = [msg for msg in [state.voice_error, state.voice_convert_error, state.voice_send_error] if msg]
            error_label.set_text('\n'.join(errors))

            records_column.clear()
            with records_column:
                if not state.voice_records:
                    with ui.element('div').classes('chat-ai max-w-[96%]'):
                        ui.label('提示').classes('text-xs text-slate-400')
                        ui.label('点击“开始语音”后，/asr_text 收到的有效句子会出现在这里；然后可继续执行“转化”和“发送”。').classes('whitespace-pre-wrap leading-6')
                else:
                    for idx, item in enumerate(state.voice_records[-24:], start=max(1, len(state.voice_records) - min(24, len(state.voice_records)) + 1)):
                        with ui.element('div').classes('info-tile w-full'):
                            ui.label(f'记录 {idx}').classes('text-xs text-slate-400')
                            ui.label(f"识别文本：{item.get('asr_text') or '—'}").classes('whitespace-pre-wrap leading-6')
                            ui.label(f"孤立词：{item.get('tokens') or '—'}").classes('whitespace-pre-wrap leading-6')
                            ids = item.get('ids') or []
                            ui.label(f"编号：{' '.join(str(v) for v in ids) if ids else '—'}").classes('whitespace-pre-wrap leading-6 text-emerald-300')

            log_area.clear()
            with log_area:
                for item in state.logs[-12:]:
                    with ui.element('div').classes('info-tile w-full'):
                        ui.label(item).classes('text-xs text-slate-300 break-all leading-5')

        ui.timer(0.6, refresh_ui, immediate=True)
