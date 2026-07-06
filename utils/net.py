from __future__ import annotations
import socket
from typing import Optional, List

def detect_local_ipv4(prefer_private: bool = True) -> str:
    """Best-effort local IPv4 address detection.

    Intended usage: running on RDK itself to expose its reachable LAN IP.
    Strategy:
    1) UDP connect trick (no packets sent) to infer outbound interface IP
    2) fallback to hostname resolution
    """
    # 1) UDP connect trick
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 8.8.8.8:80 is arbitrary; no traffic is sent for UDP connect
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and ip != "0.0.0.0":
            return ip
    except Exception:
        pass

    # 2) hostname fallback
    try:
        host = socket.gethostname()
        ip = socket.gethostbyname(host)
        if ip and ip != "127.0.0.1":
            return ip
    except Exception:
        pass

    return "127.0.0.1"

def build_preview_url(ip: str, port: int = 8000) -> str:
    ip = (ip or "").strip() or "127.0.0.1"
    return f"http://{ip}:{int(port)}"
