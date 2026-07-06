#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time

import requests
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class AsrSubscriber(Node):
    def __init__(self, topic: str, callback_url: str, timeout_sec: float) -> None:
        super().__init__('asr_subscriber')
        self.topic = topic
        self.callback_url = callback_url.rstrip('/')
        self.timeout_sec = timeout_sec
        self._last_text = ''
        self._last_ts = 0.0
        self.create_subscription(String, topic, self.on_msg, 10)
        self.get_logger().info(f'Listening {topic} -> {self.callback_url}')
        print('[VOICE_STATE] ' + json.dumps({'topic': topic, 'callback_url': self.callback_url}, ensure_ascii=False))

    def on_msg(self, msg: String) -> None:
        text = (msg.data or '').strip()
        if not text:
            return
        now = time.time()
        if text == self._last_text and (now - self._last_ts) < 1.0:
            return
        self._last_text = text
        self._last_ts = now

        payload = {'asr_text': text, 'topic': self.topic, 'received_at': now}
        try:
            response = requests.post(self.callback_url, json=payload, timeout=self.timeout_sec)
            response.raise_for_status()
            print('[VOICE_RESULT] ' + json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            print('[VOICE_ERROR] ' + json.dumps({'error': str(exc), 'payload': payload}, ensure_ascii=False))
            self.get_logger().error(f'callback failed: {exc}')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--topic', default='/asr_text')
    ap.add_argument('--callback-url', required=True)
    ap.add_argument('--timeout-sec', type=float, default=0.5)
    args = ap.parse_args()

    rclpy.init(args=None)
    node = AsrSubscriber(args.topic, args.callback_url, args.timeout_sec)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
