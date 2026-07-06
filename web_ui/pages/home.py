"""首页页面。"""

from __future__ import annotations

from nicegui import ui

from web_ui.components import page_container, section_card


async def build_home(app_ctx) -> None:
    """构建首页。"""
    state = app_ctx.state
    api = app_ctx.api

    async def enter_mode(mode: str, target: str) -> None:
        """进入指定模式并通知后端。"""
        try:
            await api.select_mode(mode)
            state.current_mode = mode
            state.add_log(f"HTTP mode/select -> {mode}")
            ui.navigate.to(target)
        except Exception as exc:
            state.add_log(f"HTTP mode/select failed: {exc}")
            ui.notify(f"切换模式失败：{exc}", type="negative")

    async def go_sign() -> None:
        await enter_mode("SIGN", "/sign")

    async def go_voice() -> None:
        await enter_mode("VOICE", "/voice")

    async def go_chat() -> None:
        await enter_mode("CHAT", "/chat")

    with page_container():
        with ui.column().classes("w-full items-center justify-center gap-6 py-8"):
            ui.label("SignRobot · NiceGUI Web UI").classes("text-4xl font-bold text-center")
            ui.label("RDK X5 仅保留推理与编排，浏览器负责交互显示").classes("text-base text-gray-400 text-center")
            mode_label = ui.label(f"当前模式：{state.current_mode}").classes("text-lg text-blue-300")

            async def refresh_mode() -> None:
                mode_label.set_text(f"当前模式：{state.current_mode}")

            ui.timer(1.0, refresh_mode)

            with ui.grid(columns=2).classes("w-full max-w-5xl gap-4"):
                with section_card("手语翻译", "统一手语翻译入口").classes("big-nav-btn"):
                    ui.button("进入 SIGN 页面", on_click=go_sign).props("unelevated color=primary").classes("w-full")
                with section_card("语音翻译", "语音识别与文本转手语占位流程").classes("big-nav-btn"):
                    ui.button("进入 VOICE 页面", on_click=go_voice).props("unelevated color=primary").classes("w-full")
                with section_card("手语对话", "手语识别、文字显示与机械臂显示").classes("big-nav-btn col-span-2"):
                    ui.button("进入 CHAT 页面", on_click=go_chat).props("unelevated color=primary").classes("w-full")

            with section_card("系统信息", "自动展示 orchestrator 最新检测结果"):
                sys_label = ui.label("等待加载系统信息...").classes("text-sm text-gray-300 whitespace-pre-wrap leading-6")

                async def refresh_system_info() -> None:
                    info = state.system_info
                    if not info:
                        try:
                            info = await api.get_system_info()
                            state.system_info = info
                        except Exception as exc:
                            sys_label.set_text(f"系统信息读取失败：{exc}")
                            return
                    ip = info.get("ip") or "127.0.0.1"
                    preview = info.get("preview_url") or app_ctx.settings.preview_url
                    sys_label.set_text(
                        "\n".join([
                            f"RDK IP：{ip}",
                            f"官方页面入口（仅参考）：{preview}",
                            f"前端原生视频 WS：{app_ctx.settings.resolved_togetheros_ws_url()}",
                            f"filter_prefix：{app_ctx.settings.resolved_togetheros_filter_prefix()}",
                            "前端策略：原生 websocket + protobuf 解码，不再嵌入 iframe",
                        ])
                    )

                ui.timer(2.0, refresh_system_info, immediate=True)
