"""NiceGUI 通用组件与样式。"""

from __future__ import annotations

import json
import uuid

from nicegui import ui


GLOBAL_CSS = """
:root {
    --page-h: calc(100vh - 82px);
}
body {
    background:
        radial-gradient(circle at top left, rgba(59, 130, 246, 0.16), transparent 24%),
        radial-gradient(circle at top right, rgba(16, 185, 129, 0.12), transparent 20%),
        linear-gradient(180deg, #07111f 0%, #0b1220 46%, #0f172a 100%);
    color: #e5e7eb;
}
.page-shell {
    width: 100%;
    max-width: 1760px;
    margin: 0 auto;
    min-height: var(--page-h);
}
.glass-card {
    background: linear-gradient(180deg, rgba(15, 23, 42, 0.94) 0%, rgba(17, 24, 39, 0.88) 100%);
    border: 1px solid rgba(148, 163, 184, 0.16);
    border-radius: 24px;
    box-shadow: 0 18px 45px rgba(0, 0, 0, 0.28);
    backdrop-filter: blur(16px);
}
.section-title {
    font-size: 1.12rem;
    font-weight: 700;
    letter-spacing: 0.01em;
}
.section-subtitle {
    font-size: 0.86rem;
    color: #94a3b8;
    line-height: 1.5;
}
.metric-value {
    font-size: 1.9rem;
    font-weight: 800;
    line-height: 1.2;
}
.status-chip {
    padding: 6px 12px;
    border-radius: 999px;
    border: 1px solid rgba(148, 163, 184, 0.18);
    background: rgba(15, 23, 42, 0.72);
    font-size: 0.78rem;
    color: #cbd5e1;
}
.action-btn .q-btn {
    min-height: 54px;
    border-radius: 16px;
    font-size: 1rem;
    font-weight: 600;
}
.chat-user {
    background: linear-gradient(180deg, rgba(37, 99, 235, 0.24) 0%, rgba(29, 78, 216, 0.18) 100%);
    border: 1px solid rgba(96, 165, 250, 0.28);
    border-radius: 20px;
    padding: 14px 16px;
}
.chat-ai {
    background: rgba(15, 23, 42, 0.92);
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-radius: 20px;
    padding: 14px 16px;
}
.info-tile {
    padding: 14px 16px;
    border-radius: 18px;
    border: 1px solid rgba(148, 163, 184, 0.14);
    background: rgba(15, 23, 42, 0.55);
}
.log-panel,
.history-panel,
.chat-panel {
    scrollbar-width: thin;
}
.big-nav-btn .q-btn {
    min-height: 76px;
    font-size: 1.08rem;
    border-radius: 20px;
}
.preview-root {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    min-height: 420px;
    gap: 10px;
}
.preview-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
}
.preview-stage {
    position: relative;
    width: 100%;
    flex: 1 1 auto;
    min-height: 520px;
    border-radius: 20px;
    overflow: hidden;
    background: #020617;
    border: 1px solid rgba(148, 163, 184, 0.14);
}
.preview-meta {
    font-size: 12px;
    color: #94a3b8;
    white-space: pre-wrap;
    line-height: 1.55;
}
.preview-warning {
    font-size: 12px;
    color: #fca5a5;
    white-space: pre-wrap;
    line-height: 1.55;
}
.preview-media,
.preview-overlay {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    display: block;
}
.preview-media {
    object-fit: contain;
    background: #000;
}
.preview-overlay {
    pointer-events: none;
}
.preview-placeholder {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
    color: #94a3b8;
    font-size: 13px;
    text-align: center;
    line-height: 1.7;
    background: radial-gradient(circle at center, rgba(15, 23, 42, 0.45), rgba(2, 6, 23, 0.9));
}
.preview-toggle-btn {
    border: 1px solid rgba(148, 163, 184, 0.18);
    background: rgba(15, 23, 42, 0.72);
    color: #cbd5e1;
    border-radius: 999px;
    font-size: 12px;
    padding: 6px 12px;
    cursor: pointer;
    transition: all 0.2s ease;
}
.preview-toggle-btn[data-active='1'] {
    border-color: rgba(34, 211, 238, 0.6);
    color: #67e8f9;
}
.preview-toggle-btn:hover {
    background: rgba(30, 41, 59, 0.9);
}
.preview-status-chip[data-state='connected'] {
    color: #86efac;
}
.preview-status-chip[data-state='connecting'] {
    color: #fcd34d;
}
.preview-status-chip[data-state='disconnected'],
.preview-status-chip[data-state='error'] {
    color: #fca5a5;
}
.preview-toolbar-left,
.preview-toolbar-right {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}
@media (max-width: 1100px) {
    :root {
        --page-h: auto;
    }
    .page-shell {
        min-height: auto;
    }
    .preview-root {
        min-height: 420px;
    }
    .preview-stage {
        min-height: 420px;
    }
}
"""


def apply_theme() -> None:
    """应用全局深色主题与前端资源。"""
    ui.dark_mode().enable()
    ui.add_head_html(f"<style>{GLOBAL_CSS}</style>")
    ui.add_head_html('<script src="/static/togetheros/protobuf.js"></script>')
    ui.add_head_html('<script src="/static/togetheros/native_receiver.js"></script>')


def page_container() -> ui.column:
    """创建统一页面容器。"""
    return ui.column().classes("page-shell w-full gap-4 p-4 md:p-5")


def section_card(title: str, subtitle: str | None = None) -> ui.card:
    """创建统一卡片。"""
    card = ui.card().classes("glass-card w-full p-4 md:p-5 gap-3")
    with card:
        ui.label(title).classes("section-title")
        if subtitle:
            ui.label(subtitle).classes("section-subtitle")
    return card


def top_nav() -> None:
    """创建顶部导航栏。"""
    with ui.header().classes("bg-[rgba(7,17,31,0.72)] backdrop-blur border-b border-white/10"):
        with ui.row().classes("w-full items-center justify-between px-4 py-2"):
            with ui.row().classes("items-center gap-3"):
                ui.label("SignRobot 控制台").classes("text-lg font-bold")
                ui.label("单页高效交互版").classes("text-xs text-slate-400")
            with ui.row().classes("items-center gap-2"):
                ui.button("首页", on_click=lambda: ui.navigate.to("/")).props("flat color=white")
                ui.button("手语翻译", on_click=lambda: ui.navigate.to("/sign")).props("flat color=white")
                ui.button("语音翻译", on_click=lambda: ui.navigate.to("/voice")).props("flat color=white")
                ui.button("手语对话", on_click=lambda: ui.navigate.to("/chat")).props("flat color=white")



def togetheros_native_video_component(
    *,
    preview_base_url: str,
    ws_url: str,
    proto_url: str,
    filter_prefix: str,
    title: str = "实时预览",
    enable_overlay: bool = False,
) -> None:
    """在当前页面中原生渲染 TogetheROS websocket 视频流。"""
    element_id = f"togetheros-native-{uuid.uuid4().hex}"
    official_page_url = f"{preview_base_url.rstrip('/')}/TogetheROS/" if preview_base_url.startswith(("http://", "https://")) else "/"

    root_html = f"""
    <div id="{element_id}" class="preview-root">
      <div class="preview-toolbar">
        <div class="preview-toolbar-left">
          <span class="status-chip preview-status-chip" data-role="status">初始化中</span>
          <span class="status-chip" data-role="fps">FPS --</span>
          <span class="status-chip" data-role="resolution">--</span>
        </div>
        <div class="preview-toolbar-right">
          <button type="button" class="preview-toggle-btn" data-role="overlay-toggle">Overlay 关</button>
        </div>
      </div>
      <div class="preview-stage" data-role="stage">
        <img class="preview-media" data-role="image" alt="{title}" />
        <canvas class="preview-overlay" data-role="overlay"></canvas>
        <div class="preview-placeholder" data-role="placeholder">等待视频流...</div>
      </div>
      <div class="preview-meta" data-role="message">等待视频流...</div>
    </div>
    """
    host_id = f"togetheros-host-{uuid.uuid4().hex}"
    ui.element("div").props(f'id={host_id}').classes("w-full flex-1")
    with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
        ui.label(f"WebSocket：{ws_url}").classes("preview-meta")
        ui.link("打开官方 TogetheROS 页面（仅排障用）", official_page_url, new_tab=True).classes("text-cyan-300 text-sm no-underline hover:underline") if official_page_url != "/" else ui.label("未配置官方预览页 URL（当前仅使用 filter_prefix）").classes("preview-meta")
    ui.label(
        "若画面为空白，请优先检查：1) websocket 地址是否正确；2) 是否需要正确的 filter_prefix；3) 浏览器是否拦截 ws / mixed content；4) RDK 的 8080 端口是否可达。"
    ).classes("preview-warning")

    init_payload = {
        "hostId": host_id,
        "rootId": element_id,
        "rootHtml": root_html,
        "wsUrl": ws_url,
        "protoUrl": proto_url,
        "filterPrefix": filter_prefix,
        "showOverlay": enable_overlay,
        "maxWaitMs": 30000,
        "retryMs": 150,
    }
    config_json = json.dumps(init_payload, ensure_ascii=False)
    
    init_code = """(function bootTogetheROSNativePreview() {
        const config = __CONFIG_JSON__;
        const bootKey = '__togetheROSBoot_' + config.rootId;
    
        function findHost() {
            return document.getElementById(config.hostId);
        }
    
        function findRoot() {
            return document.getElementById(config.rootId);
        }
    
        function injectRootIfNeeded() {
            const host = findHost();
            if (!host) return false;
    
            if (!findRoot()) {
                host.innerHTML = config.rootHtml;
            }
            return !!findRoot();
        }
    
        function tryBoot() {
            if (!window.initTogetheROSNativePreview) {
                window.setTimeout(tryBoot, 150);
                return;
            }
    
            if (window[bootKey] === 'booting' || window[bootKey] === 'ready') {
                return;
            }
    
            const host = findHost();
            if (!host) {
                window.setTimeout(tryBoot, 150);
                return;
            }
    
            const ok = injectRootIfNeeded();
            if (!ok) {
                window.setTimeout(tryBoot, 150);
                return;
            }
    
            window[bootKey] = 'booting';
    
            Promise.resolve(window.initTogetheROSNativePreview({
                rootId: config.rootId,
                wsUrl: config.wsUrl,
                protoUrl: config.protoUrl,
                filterPrefix: config.filterPrefix,
                showOverlay: config.showOverlay,
                maxWaitMs: config.maxWaitMs,
                retryMs: config.retryMs,
            }))
            .then((instance) => {
                window[bootKey] = instance ? 'ready' : false;
                if (!instance) {
                    window.setTimeout(tryBoot, 300);
                }
            })
            .catch((error) => {
                console.warn('[TogetheROS] preview init failed, retrying:', error);
                window[bootKey] = false;
                window.setTimeout(tryBoot, 300);
            });
        }
    
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', tryBoot, { once: true });
        } else {
            window.requestAnimationFrame(() => {
                window.setTimeout(tryBoot, 80);
            });
        }
    })();
    """.replace('__CONFIG_JSON__', config_json)
    
    ui.timer(
        0.3,
        lambda: ui.run_javascript(init_code),
        once=True,
    )
    
