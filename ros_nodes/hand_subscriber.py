#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RDK X5 sign-language recognizer without MediaPipe.

What this file does
-------------------
1) Subscribes to:
   - /hobot_mono2d_body_detection   (body / pose source)
   - /hobot_hand_lmk_detection      (hand landmark source from hand_lmk_detection)
2) Synchronizes body and hand messages by timestamp.
3) Extracts pose + up to 2 hands.
4) Reorders all keypoints into the SAME semantic order used by the original
   MediaPipe-based SPOTER preprocessing.
5) Keeps pose and hand as separate groups, but exports/feeds them in the same
   model input order as the original SPOTER code.
6) Removes drawing / cv_bridge / MediaPipe dependency.
7) Runs ONNX sign-language inference in realtime.
8) Reports:
   - classifier inference speed
   - preprocessing speed
   - end-to-result latency (wall clock + stream timestamp)

IMPORTANT
---------
You MUST fill the mapping section below to match your actual RDK keypoint order.
I intentionally made the mapping editable and explicit so that you can directly
modify corresponding keypoints one by one.

This file is designed as a replacement / fusion of:
- rdk_x5_hand_lmk_subscriber.py
- spoter_onnx_deploy_cnfix_fixed.py

It does NOT draw images.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

import requests
import numpy as np
import onnxruntime as ort
import rclpy
from rclpy.node import Node

from ai_msgs.msg import PerceptionTargets  # type: ignore
from std_msgs.msg import Bool, String


# =============================================================================
# 0) ORDER DEFINITIONS (same semantic order as SPOTER / original MediaPipe code)
# =============================================================================

BODY_IDENTIFIERS = [
    "nose",
    "neck",
    "rightEye",
    "leftEye",
    "rightEar",
    "leftEar",
    "rightShoulder",
    "leftShoulder",
    "rightElbow",
    "leftElbow",
    "rightWrist",
    "leftWrist",
]

HAND_IDENTIFIERS = [
    "wrist",
    "indexTip",
    "indexDIP",
    "indexPIP",
    "indexMCP",
    "middleTip",
    "middleDIP",
    "middlePIP",
    "middleMCP",
    "ringTip",
    "ringDIP",
    "ringPIP",
    "ringMCP",
    "littleTip",
    "littleDIP",
    "littlePIP",
    "littleMCP",
    "thumbTip",
    "thumbIP",
    "thumbMP",
    "thumbCMC",
]

MODEL_KEYPOINTS = (
    BODY_IDENTIFIERS
    + [f"{name}_0" for name in HAND_IDENTIFIERS]
    + [f"{name}_1" for name in HAND_IDENTIFIERS]
)

# MediaPipe hand index -> SPOTER hand name
MP_HAND_TO_SPOTER = {
    0: "wrist",
    8: "indexTip",
    7: "indexDIP",
    6: "indexPIP",
    5: "indexMCP",
    12: "middleTip",
    11: "middleDIP",
    10: "middlePIP",
    9: "middleMCP",
    16: "ringTip",
    15: "ringDIP",
    14: "ringPIP",
    13: "ringMCP",
    20: "littleTip",
    19: "littleDIP",
    18: "littlePIP",
    17: "littleMCP",
    4: "thumbTip",
    3: "thumbIP",
    2: "thumbMP",
    1: "thumbCMC",
}


# =============================================================================
# 1) YOU SHOULD EDIT THIS PART
# =============================================================================
# The purpose of this section is to let you directly fill in "RDK index -> name"
# or "RDK index -> MediaPipe index" according to your real message format.
#
# - Body and hand are separated.
# - Hand order in the model must finally match the original MediaPipe-based code.
# - If the RDK output order differs, edit these mappings only.
# =============================================================================

# Candidate point.type names in /hobot_mono2d_body_detection.
# Adjust these if your body message uses another type string.
BODY_POINT_TYPE_CANDIDATES = [
    "body_kps",
    "body_keypoints",
    "pose_kps",
    "pose_keypoints",
    "skeleton_kps",
]

# Candidate ROI type names for body and hand
BODY_ROI_TYPE_CANDIDATES = ["body", "person"]
HAND_ROI_TYPE_CANDIDATES = ["hand"]

# -----------------------------------------------------------------------------
# BODY MAPPING TEMPLATE
# -----------------------------------------------------------------------------
# Fill with your real RDK body-point indices.
#
# Example meaning:
#   RDK_BODY_INDEX_TO_NAME = {
#       0: "nose",
#       1: "leftEye",
#       2: "rightEye",
#       ...
#   }
#
# Keys   : index in the body point list from /hobot_mono2d_body_detection
# Values : one of BODY_IDENTIFIERS, or "leftHip"/"rightHip" if you have them
#
# "neck" can be omitted because code can estimate it automatically.
# "leftHip"/"rightHip" are optional, but recommended for better start/end lines.
# -----------------------------------------------------------------------------
RDK_BODY_INDEX_TO_NAME: Dict[int, str] = {
    # ======= TODO: EDIT HERE WITH YOUR REAL BODY ORDER =======
    0: "nose",
    1: "leftEye",
    2: "rightEye",
    3: "leftEar",
    4: "rightEar",
    5: "leftShoulder",
    6: "rightShoulder",
    7: "leftElbow",
    8: "rightElbow",
    9: "leftWrist",
    10: "rightWrist",
    11: "leftHip",
    12: "rightHip",
}

# -----------------------------------------------------------------------------
# HAND MAPPING TEMPLATE
# -----------------------------------------------------------------------------
# RDK hand landmark order may differ from MediaPipe hand order.
# You said you will compare and modify the corresponding points yourself.
# So I made the hand remap editable in the most direct way:
#
# Keys   : index in RDK hand_kps list
# Values : MediaPipe hand index (0..20)
#
# Then the code automatically converts MediaPipe order into SPOTER order.
#
# Example:
#   if RDK index 0 is MP wrist -> 0: 0
#   if RDK index 1 is MP thumb_cmc -> 1: 1
#   ...
# -----------------------------------------------------------------------------
RDK_HAND_INDEX_TO_MP_INDEX: Dict[int, int] = {
    # ======= TODO: EDIT HERE WITH YOUR REAL HAND ORDER =======
    # The example below is the standard MediaPipe order.
    1: 0,
    2: 1,
    3: 2,
    4: 3,
    5: 4,
    6: 5,
    7: 6,
    8: 7,
    9: 8,
    10: 9,
    11: 10,
    12: 11,
    13: 12,
    14: 13,
    15: 14,
    16: 15,
    17: 16,
    18: 17,
    19: 18,
    20: 19,
    21: 20,
}


# =============================================================================
# 2) CONFIG
# =============================================================================

@dataclass
class DeployConfig:
    target_frames: int = 32

    # segmentation logic
    use_dynamic_wrist_lines: bool = True
    start_line_ratio: float = 0.75
    end_line_ratio: float = 0.75
    raw_start_y_threshold: float = 0.60
    raw_end_y_threshold: float = 0.80
    start_consec_frames: int = 2
    end_consec_frames: int = 4
    pre_roll_frames: int = 2
    post_roll_frames: int = 2
    min_segment_frames: int = 8
    fail_on_multiple_segments: bool = True
    start_wrist_mode: str = "either"
    end_wrist_mode: str = "both"

    # repair / interpolation
    enable_time_interpolation: bool = True
    enable_structure_fill: bool = True
    fill_missing_hand_with_pose_wrist: bool = True
    force_no_zero: bool = True

    # realtime buffer
    frame_buffer_max: int = 240
    sync_tolerance_ms: int = 50
    hold_result_seconds: float = 2.0
    flush_idle_ms: int = 120
    infer_margin_frames: int = 1
    segment_tail_grace_ms: int = 80

    # IO
    dump_jsonl_path: str = ""
    result_topic_log_only: bool = True


@dataclass
class FrameRecord:
    frame_index: int
    timestamp_ns: int
    width: int
    height: int
    body: Dict[str, Tuple[float, float]]
    hand0: Dict[str, Tuple[float, float]]  # left hand after assignment
    hand1: Dict[str, Tuple[float, float]]  # right hand after assignment
    left_wrist_y: float
    right_wrist_y: float
    start_line_y: float
    end_line_y: float
    start_active: bool
    end_active: bool


@dataclass
class SegmentResult:
    status: str
    start_idx: Optional[int] = None
    end_idx: Optional[int] = None
    segment_count: int = 0
    message: str = ""


@dataclass
class CachedMsg:
    stamp_ns: int
    msg: PerceptionTargets
    arrival_monotonic: float


# =============================================================================
# 3) GENERIC HELPERS
# =============================================================================

def safe_get_attr(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default) if hasattr(obj, name) else default


def msg_stamp_to_ns(msg: Any) -> int:
    return int(msg.header.stamp.sec) * 1_000_000_000 + int(msg.header.stamp.nanosec)


def point32_to_xy(pt: Any) -> Tuple[float, float]:
    return float(safe_get_attr(pt, "x", 0.0)), float(safe_get_attr(pt, "y", 0.0))


def get_roi_rect(roi_msg: Any) -> Tuple[float, float, float, float]:
    # Compatible with both rect.{x_offset,y_offset,width,height} and left/top/right/bottom
    if hasattr(roi_msg, "rect"):
        rect = roi_msg.rect
        left = float(safe_get_attr(rect, "x_offset", 0.0))
        top = float(safe_get_attr(rect, "y_offset", 0.0))
        width = float(safe_get_attr(rect, "width", 0.0))
        height = float(safe_get_attr(rect, "height", 0.0))
        return left, top, left + width, top + height

    left = float(safe_get_attr(roi_msg, "left", 0.0))
    top = float(safe_get_attr(roi_msg, "top", 0.0))
    right = float(safe_get_attr(roi_msg, "right", 0.0))
    bottom = float(safe_get_attr(roi_msg, "bottom", 0.0))
    return left, top, right, bottom


def roi_area(roi_msg: Any) -> float:
    l, t, r, b = get_roi_rect(roi_msg)
    return max(0.0, r - l) * max(0.0, b - t)


def find_first_point_block(target: Any, type_candidates: Sequence[str]) -> Optional[Any]:
    for p in safe_get_attr(target, "points", []):
        ptype = str(safe_get_attr(p, "type", ""))
        if ptype in type_candidates:
            return p
    return None


def find_rois_by_type(target: Any, type_candidates: Sequence[str]) -> List[Any]:
    out = []
    for roi in safe_get_attr(target, "rois", []):
        rtype = str(safe_get_attr(roi, "type", ""))
        if rtype in type_candidates:
            out.append(roi)
    return out


def normalize_named_xy(names: Sequence[str]) -> Dict[str, Tuple[float, float]]:
    return {name: (0.0, 0.0) for name in names}


def ns_to_ms(ns: int) -> float:
    return float(ns) / 1_000_000.0


# =============================================================================
# 4) MESSAGE EXTRACTION
# =============================================================================

class MessageExtractor:
    """
    Extracts:
    - one main body target (largest body ROI if multiple)
    - up to 2 hand targets (largest 2 hand ROIs if more)
    - hand side assignment by distance to body left/right wrist
    """

    def __init__(self) -> None:
        pass

    def extract_body_from_msg(self, msg: PerceptionTargets) -> Optional[Dict[str, Any]]:
        body_candidates = []

        for target in safe_get_attr(msg, "targets", []):
            rois = find_rois_by_type(target, BODY_ROI_TYPE_CANDIDATES)
            body_points = find_first_point_block(target, BODY_POINT_TYPE_CANDIDATES)
            if body_points is None:
                continue

            best_roi = max(rois, key=roi_area) if rois else None
            area = roi_area(best_roi) if best_roi is not None else 0.0
            body_candidates.append(
                {
                    "target": target,
                    "point_block": body_points,
                    "roi": best_roi,
                    "area": area,
                }
            )

        if not body_candidates:
            return None

        # choose largest body/person target
        return max(body_candidates, key=lambda x: x["area"])

    def extract_body_named_points(self, msg: PerceptionTargets) -> Dict[str, Tuple[float, float]]:
        named = normalize_named_xy(list(BODY_IDENTIFIERS) + ["leftHip", "rightHip"])
        picked = self.extract_body_from_msg(msg)
        if picked is None:
            named["neck"] = (0.0, 0.0)
            return named

        pts = safe_get_attr(picked["point_block"], "point", [])
        for idx, pt in enumerate(pts):
            if idx not in RDK_BODY_INDEX_TO_NAME:
                continue
            name = RDK_BODY_INDEX_TO_NAME[idx]
            named[name] = point32_to_xy(pt)

        if named["neck"] == (0.0, 0.0):
            named["neck"] = self.estimate_neck(named)

        return named

    def estimate_neck(self, body: Dict[str, Tuple[float, float]]) -> Tuple[float, float]:
        ls = body.get("leftShoulder", (0.0, 0.0))
        rs = body.get("rightShoulder", (0.0, 0.0))
        nose = body.get("nose", (0.0, 0.0))
        le = body.get("leftEye", (0.0, 0.0))
        re = body.get("rightEye", (0.0, 0.0))
        lear = body.get("leftEar", (0.0, 0.0))
        rear = body.get("rightEar", (0.0, 0.0))

        if ls != (0.0, 0.0) and rs != (0.0, 0.0):
            return ((ls[0] + rs[0]) / 2.0, (ls[1] + rs[1]) / 2.0)
        if ls != (0.0, 0.0) and nose != (0.0, 0.0):
            return (ls[0] * 0.75 + nose[0] * 0.25, ls[1] * 0.75 + nose[1] * 0.25)
        if rs != (0.0, 0.0) and nose != (0.0, 0.0):
            return (rs[0] * 0.75 + nose[0] * 0.25, rs[1] * 0.75 + nose[1] * 0.25)
        eye_mid = self.safe_midpoint([le, re])
        if eye_mid != (0.0, 0.0) and nose != (0.0, 0.0):
            return ((eye_mid[0] + nose[0]) / 2.0, (eye_mid[1] + nose[1]) / 2.0)
        ear_mid = self.safe_midpoint([lear, rear])
        return ear_mid if ear_mid != (0.0, 0.0) else nose

    @staticmethod
    def safe_midpoint(points: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
        valid = [p for p in points if not (p[0] == 0.0 and p[1] == 0.0)]
        if not valid:
            return 0.0, 0.0
        return float(np.mean([p[0] for p in valid])), float(np.mean([p[1] for p in valid]))

    def extract_hand_candidates(self, msg: PerceptionTargets) -> List[Dict[str, Any]]:
        out = []
        for target in safe_get_attr(msg, "targets", []):
            point_block = find_first_point_block(target, ["hand_kps"])
            if point_block is None:
                continue
            hand_rois = find_rois_by_type(target, HAND_ROI_TYPE_CANDIDATES)
            best_roi = max(hand_rois, key=roi_area) if hand_rois else None
            out.append(
                {
                    "target": target,
                    "point_block": point_block,
                    "roi": best_roi,
                    "area": roi_area(best_roi) if best_roi is not None else 0.0,
                }
            )

        # keep only largest 2 hands if more than 2 appear in one image
        out.sort(key=lambda x: x["area"], reverse=True)
        return out[:2]

    def remap_rdk_hand_points_to_spoter_names(self, pts: Sequence[Any]) -> Dict[str, Tuple[float, float]]:
        """
        RDK hand list -> MP index -> SPOTER hand name
        """
        mp_points: Dict[int, Tuple[float, float]] = {i: (0.0, 0.0) for i in range(21)}
        for rdk_idx, pt in enumerate(pts):
            if rdk_idx not in RDK_HAND_INDEX_TO_MP_INDEX:
                continue
            mp_idx = int(RDK_HAND_INDEX_TO_MP_INDEX[rdk_idx])
            if mp_idx < 0 or mp_idx > 20:
                continue
            mp_points[mp_idx] = point32_to_xy(pt)

        named = normalize_named_xy(HAND_IDENTIFIERS)
        for mp_idx, name in MP_HAND_TO_SPOTER.items():
            named[name] = mp_points.get(mp_idx, (0.0, 0.0))
        return named

    def assign_two_hands_to_left_right(
        self,
        hand_candidates: List[Dict[str, Any]],
        body: Dict[str, Tuple[float, float]],
    ) -> Tuple[Dict[str, Tuple[float, float]], Dict[str, Tuple[float, float]]]:
        empty = normalize_named_xy(HAND_IDENTIFIERS)
        if not hand_candidates:
            return empty.copy(), empty.copy()

        left_wrist_pose = body.get("leftWrist", (0.0, 0.0))
        right_wrist_pose = body.get("rightWrist", (0.0, 0.0))

        prepared = []
        for item in hand_candidates:
            pts = safe_get_attr(item["point_block"], "point", [])
            named = self.remap_rdk_hand_points_to_spoter_names(pts)
            wrist = named["wrist"]

            dl = 1e18
            dr = 1e18
            if left_wrist_pose != (0.0, 0.0) and wrist != (0.0, 0.0):
                dl = (wrist[0] - left_wrist_pose[0]) ** 2 + (wrist[1] - left_wrist_pose[1]) ** 2
            if right_wrist_pose != (0.0, 0.0) and wrist != (0.0, 0.0):
                dr = (wrist[0] - right_wrist_pose[0]) ** 2 + (wrist[1] - right_wrist_pose[1]) ** 2

            prepared.append({"hand": named, "dl": dl, "dr": dr})

        if len(prepared) == 1:
            one = prepared[0]
            if one["dl"] <= one["dr"]:
                return one["hand"], empty.copy()
            return empty.copy(), one["hand"]

        left_candidate = sorted(prepared, key=lambda x: x["dl"])[0]
        remaining = [x for x in prepared if x is not left_candidate]
        right_candidate = sorted(remaining, key=lambda x: x["dr"])[0] if remaining else None

        left_out = left_candidate["hand"] if left_candidate else empty.copy()
        right_out = right_candidate["hand"] if right_candidate else empty.copy()
        return left_out, right_out


# =============================================================================
# 5) SPOTER PREPROCESSOR (MediaPipe removed, semantics preserved)
# =============================================================================

class SpoterPreprocessor:
    def __init__(self, config: DeployConfig):
        self.config = config

    @staticmethod
    def _safe_midpoint(points: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
        valid = [p for p in points if not (p[0] == 0 and p[1] == 0)]
        if not valid:
            return 0.0, 0.0
        return float(np.mean([p[0] for p in valid])), float(np.mean([p[1] for p in valid]))

    def _compute_activity_lines(self, body: Dict[str, Tuple[float, float]], height: int) -> Tuple[float, float]:
        ls, rs = body["leftShoulder"], body["rightShoulder"]
        lh, rh = body.get("leftHip", (0.0, 0.0)), body.get("rightHip", (0.0, 0.0))
        shoulder = self._safe_midpoint([ls, rs])
        hip = self._safe_midpoint([lh, rh])

        shoulder_y = shoulder[1] if shoulder != (0.0, 0.0) else 0.35 * height
        hip_y = hip[1] if hip != (0.0, 0.0) else 0.80 * height
        if hip_y <= shoulder_y:
            hip_y = shoulder_y + 0.40 * height

        if self.config.use_dynamic_wrist_lines:
            start_line_y = shoulder_y + self.config.start_line_ratio * (hip_y - shoulder_y)
            end_line_y = shoulder_y + self.config.end_line_ratio * (hip_y - shoulder_y)
        else:
            start_line_y = self.config.raw_start_y_threshold * height
            end_line_y = self.config.raw_end_y_threshold * height
        return float(start_line_y), float(end_line_y)

    @staticmethod
    def _wrist_condition(left_y: float, right_y: float, line_y: float, mode: str, wrist_mode: str) -> bool:
        left_ok = False if left_y == 0 or line_y == 0 else (left_y <= line_y if mode == "start" else left_y >= line_y)
        right_ok = False if right_y == 0 or line_y == 0 else (right_y <= line_y if mode == "start" else right_y >= line_y)
        if wrist_mode == "both":
            return left_ok and right_ok
        if wrist_mode == "either":
            return left_ok or right_ok
        raise ValueError(f"Unknown wrist_mode: {wrist_mode}")

    def make_frame_record(
        self,
        frame_index: int,
        timestamp_ns: int,
        width: int,
        height: int,
        body_named: Dict[str, Tuple[float, float]],
        hand_left: Dict[str, Tuple[float, float]],
        hand_right: Dict[str, Tuple[float, float]],
    ) -> FrameRecord:
        start_line_y, end_line_y = self._compute_activity_lines(body_named, height)
        left_wrist_y = body_named["leftWrist"][1]
        right_wrist_y = body_named["rightWrist"][1]
        start_active = self._wrist_condition(left_wrist_y, right_wrist_y, start_line_y, "start", self.config.start_wrist_mode)
        end_active = self._wrist_condition(left_wrist_y, right_wrist_y, end_line_y, "end", self.config.end_wrist_mode)

        body_final = {k: body_named.get(k, (0.0, 0.0)) for k in BODY_IDENTIFIERS}

        return FrameRecord(
            frame_index=frame_index,
            timestamp_ns=timestamp_ns,
            width=width,
            height=height,
            body=body_final,
            hand0=hand_left,
            hand1=hand_right,
            left_wrist_y=float(left_wrist_y),
            right_wrist_y=float(right_wrist_y),
            start_line_y=float(start_line_y),
            end_line_y=float(end_line_y),
            start_active=bool(start_active),
            end_active=bool(end_active),
        )

    def find_segments(self, records: List[FrameRecord]) -> SegmentResult:
        if not records:
            return SegmentResult(status="empty_video", message="No frames found.")

        valid_segments: List[Tuple[int, int]] = []
        in_segment = False
        start_run = 0
        end_run = 0
        seg_start = None

        for idx, rec in enumerate(records):
            if not in_segment:
                start_run = start_run + 1 if rec.start_active else 0
                if start_run >= self.config.start_consec_frames:
                    seg_start = max(0, idx - self.config.start_consec_frames + 1 - self.config.pre_roll_frames)
                    in_segment = True
                    end_run = 0
            else:
                end_run = end_run + 1 if rec.end_active else 0
                if end_run >= self.config.end_consec_frames:
                    seg_end = min(len(records) - 1, idx - self.config.end_consec_frames + 1 + self.config.post_roll_frames)
                    if seg_start is not None and (seg_end - seg_start + 1) >= self.config.min_segment_frames:
                        valid_segments.append((seg_start, seg_end))
                    in_segment = False
                    seg_start = None
                    start_run = 0
                    end_run = 0

        if in_segment and seg_start is not None:
            seg_end = len(records) - 1
            if (seg_end - seg_start + 1) >= self.config.min_segment_frames:
                valid_segments.append((seg_start, seg_end))

        if not valid_segments:
            return SegmentResult(status="no_sign_detected", segment_count=0, message="No valid segment found.")

        merged = []
        for seg in sorted(valid_segments):
            if not merged or seg[0] > merged[-1][1] + 1:
                merged.append(seg)
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], seg[1]))

        if len(merged) > 1:
            if self.config.fail_on_multiple_segments:
                return SegmentResult(
                    status="multiple_segments",
                    segment_count=len(merged),
                    message=f"Detected {len(merged)} segments.",
                )
            s, e = merged[0]
            return SegmentResult(
                status="multiple_segments_kept_first",
                start_idx=s,
                end_idx=e,
                segment_count=len(merged),
                message=f"Detected {len(merged)} segments, kept first.",
            )

        s, e = merged[0]
        return SegmentResult(status="ok", start_idx=s, end_idx=e, segment_count=1, message="Single valid segment detected.")

    @staticmethod
    def _resample_indices(num_frames: int, target_frames: int) -> np.ndarray:
        if num_frames <= 0:
            raise ValueError("num_frames must be > 0")
        if num_frames == target_frames:
            return np.arange(num_frames, dtype=np.int32)
        if num_frames == 1:
            return np.zeros(target_frames, dtype=np.int32)
        xs = np.linspace(0, num_frames - 1, target_frames)
        idx = np.rint(xs).astype(np.int32)
        return np.clip(idx, 0, num_frames - 1)

    def _records_to_sequence(self, records: List[FrameRecord]) -> Dict[str, np.ndarray]:
        n = len(records)
        data = {}

        for name in BODY_IDENTIFIERS:
            arr = np.zeros((n, 2), dtype=np.float32)
            for i, rec in enumerate(records):
                arr[i, 0] = rec.body[name][0]
                arr[i, 1] = rec.body[name][1]
            data[name] = arr

        for hand_idx, hand_key in enumerate(["hand0", "hand1"]):
            for name in HAND_IDENTIFIERS:
                key = f"{name}_{hand_idx}"
                arr = np.zeros((n, 2), dtype=np.float32)
                for i, rec in enumerate(records):
                    hand = getattr(rec, hand_key)
                    arr[i, 0] = hand[name][0]
                    arr[i, 1] = hand[name][1]
                data[key] = arr

        return data

    @staticmethod
    def _interpolate_xy(arr: np.ndarray) -> np.ndarray:
        out = arr.astype(np.float32).copy()
        for d in range(2):
            v = out[:, d].copy()
            mask_missing = v == 0
            v[mask_missing] = np.nan
            idx = np.arange(len(v))
            valid = ~np.isnan(v)
            if valid.sum() == 0:
                continue
            if valid.sum() == 1:
                v[:] = v[valid][0]
            else:
                v[np.isnan(v)] = np.interp(idx[np.isnan(v)], idx[valid], v[valid])

            valid_idx = np.where(~np.isnan(v))[0]
            if len(valid_idx) > 0:
                v[:valid_idx[0]] = v[valid_idx[0]]
                v[valid_idx[-1] + 1:] = v[valid_idx[-1]]
            out[:, d] = v
        return out

    def _fill_body_structure(self, seq: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        n = len(next(iter(seq.values()))) if seq else 0
        for t in range(n):
            nose = seq["nose"][t]
            l_eye = seq["leftEye"][t]
            r_eye = seq["rightEye"][t]
            l_ear = seq["leftEar"][t]
            r_ear = seq["rightEar"][t]
            l_sh = seq["leftShoulder"][t]
            r_sh = seq["rightShoulder"][t]
            l_el = seq["leftElbow"][t]
            r_el = seq["rightElbow"][t]
            l_wr = seq["leftWrist"][t]
            r_wr = seq["rightWrist"][t]

            if np.all(seq["neck"][t] == 0):
                if not np.all(l_sh == 0) and not np.all(r_sh == 0):
                    seq["neck"][t] = (l_sh + r_sh) / 2.0
                elif not np.all(nose == 0):
                    seq["neck"][t] = nose
                elif not np.all(l_eye == 0) and not np.all(r_eye == 0):
                    seq["neck"][t] = (l_eye + r_eye) / 2.0

            if np.all(seq["leftEye"][t] == 0) and not np.all(nose == 0):
                seq["leftEye"][t] = nose
            if np.all(seq["rightEye"][t] == 0) and not np.all(nose == 0):
                seq["rightEye"][t] = nose

            if np.all(seq["leftEar"][t] == 0):
                if not np.all(l_eye == 0):
                    seq["leftEar"][t] = l_eye
                elif not np.all(nose == 0):
                    seq["leftEar"][t] = nose

            if np.all(seq["rightEar"][t] == 0):
                if not np.all(r_eye == 0):
                    seq["rightEar"][t] = r_eye
                elif not np.all(nose == 0):
                    seq["rightEar"][t] = nose

            if np.all(seq["leftElbow"][t] == 0):
                if not np.all(l_sh == 0) and not np.all(l_wr == 0):
                    seq["leftElbow"][t] = (l_sh + l_wr) / 2.0
                elif not np.all(l_sh == 0):
                    seq["leftElbow"][t] = l_sh
                elif not np.all(l_wr == 0):
                    seq["leftElbow"][t] = l_wr

            if np.all(seq["rightElbow"][t] == 0):
                if not np.all(r_sh == 0) and not np.all(r_wr == 0):
                    seq["rightElbow"][t] = (r_sh + r_wr) / 2.0
                elif not np.all(r_sh == 0):
                    seq["rightElbow"][t] = r_sh
                elif not np.all(r_wr == 0):
                    seq["rightElbow"][t] = r_wr

            if np.all(seq["leftWrist"][t] == 0):
                if not np.all(l_el == 0) and not np.all(l_sh == 0):
                    seq["leftWrist"][t] = l_el + (l_el - l_sh)
                elif not np.all(l_el == 0):
                    seq["leftWrist"][t] = l_el
                elif not np.all(l_sh == 0):
                    seq["leftWrist"][t] = l_sh

            if np.all(seq["rightWrist"][t] == 0):
                if not np.all(r_el == 0) and not np.all(r_sh == 0):
                    seq["rightWrist"][t] = r_el + (r_el - r_sh)
                elif not np.all(r_el == 0):
                    seq["rightWrist"][t] = r_el
                elif not np.all(r_sh == 0):
                    seq["rightWrist"][t] = r_sh
        return seq

    def _fill_hand_structure(self, seq: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        finger_groups = {
            "thumb": ["thumbCMC", "thumbMP", "thumbIP", "thumbTip"],
            "index": ["indexMCP", "indexPIP", "indexDIP", "indexTip"],
            "middle": ["middleMCP", "middlePIP", "middleDIP", "middleTip"],
            "ring": ["ringMCP", "ringPIP", "ringDIP", "ringTip"],
            "little": ["littleMCP", "littlePIP", "littleDIP", "littleTip"],
        }

        for hand_idx, body_wrist_name in [(0, "leftWrist"), (1, "rightWrist")]:
            wrist_key = f"wrist_{hand_idx}"
            pose_wrist = seq[body_wrist_name]
            hand_keys = [f"{name}_{hand_idx}" for name in HAND_IDENTIFIERS]
            all_hand = np.concatenate([seq[k] for k in hand_keys], axis=1)

            if self.config.fill_missing_hand_with_pose_wrist and np.all(all_hand == 0):
                for k in hand_keys:
                    seq[k] = pose_wrist.copy()
                continue

            missing_wrist = np.all(seq[wrist_key] == 0, axis=1)
            seq[wrist_key][missing_wrist] = pose_wrist[missing_wrist]

            for chain in finger_groups.values():
                chain_keys = [f"{name}_{hand_idx}" for name in chain]
                for t in range(len(seq[wrist_key])):
                    anchor = seq[wrist_key][t]
                    prev = anchor if not np.all(anchor == 0) else pose_wrist[t]
                    for k in chain_keys:
                        if np.all(seq[k][t] == 0):
                            seq[k][t] = prev
                        prev = seq[k][t]

        return seq

    def _fill_from_related_anchor(self, seq: Dict[str, np.ndarray], key: str) -> np.ndarray:
        if key in seq and not np.all(seq[key] == 0):
            return seq[key]

        if key == "neck":
            if not np.all(seq["leftShoulder"] == 0) and not np.all(seq["rightShoulder"] == 0):
                return (seq["leftShoulder"] + seq["rightShoulder"]) / 2.0
            if not np.all(seq["nose"] == 0):
                return seq["nose"].copy()

        if key.startswith("wrist_0"):
            return seq["leftWrist"].copy()
        if key.startswith("wrist_1"):
            return seq["rightWrist"].copy()

        if key.endswith("_0"):
            return seq["wrist_0"].copy() if "wrist_0" in seq else seq["leftWrist"].copy()
        if key.endswith("_1"):
            return seq["wrist_1"].copy() if "wrist_1" in seq else seq["rightWrist"].copy()

        if key in ["leftElbow", "leftWrist"] and not np.all(seq["leftShoulder"] == 0):
            return seq["leftShoulder"].copy()
        if key in ["rightElbow", "rightWrist"] and not np.all(seq["rightShoulder"] == 0):
            return seq["rightShoulder"].copy()

        if not np.all(seq["nose"] == 0):
            return seq["nose"].copy()

        for candidate in seq.values():
            if not np.all(candidate == 0):
                return candidate.copy()

        return np.ones_like(next(iter(seq.values())), dtype=np.float32)

    def _remove_all_zeros(self, seq: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        if self.config.enable_time_interpolation:
            for k in list(seq.keys()):
                seq[k] = self._interpolate_xy(seq[k])

        if self.config.enable_structure_fill:
            seq = self._fill_body_structure(seq)
            seq = self._fill_hand_structure(seq)

        for k in list(seq.keys()):
            seq[k] = self._interpolate_xy(seq[k])

            all_zero_rows = np.all(seq[k] == 0, axis=1)
            if np.any(all_zero_rows):
                valid_rows = ~all_zero_rows
                if np.any(valid_rows):
                    seq[k][all_zero_rows] = seq[k][np.where(valid_rows)[0][0]]
                else:
                    seq[k] = self._fill_from_related_anchor(seq, k)

            if np.all(seq[k] == 0):
                seq[k] = self._fill_from_related_anchor(seq, k)

            zero_rows = np.all(seq[k] == 0, axis=1)
            if np.any(zero_rows):
                anchor = self._fill_from_related_anchor(seq, k)
                seq[k][zero_rows] = anchor[zero_rows]

            zero_mask = seq[k] == 0
            if np.any(zero_mask):
                filled = seq[k].copy()
                for d in range(2):
                    col = filled[:, d]
                    nz_idx = np.where(col != 0)[0]
                    if len(nz_idx) == 0:
                        col[:] = 1.0
                    else:
                        for i in np.where(col == 0)[0]:
                            nearest = nz_idx[np.argmin(np.abs(nz_idx - i))]
                            col[i] = col[nearest]
                    filled[:, d] = col
                seq[k] = filled

        return seq

    def _normalize_single_body_dict(self, row: Dict[str, List[List[float]]]) -> Dict[str, List[List[float]]]:
        sequence_size = len(row["leftEar"])
        last_starting_point = None
        last_ending_point = None

        for sequence_index in range(sequence_size):
            cond1 = (row["leftShoulder"][sequence_index][0] == 0 or row["rightShoulder"][sequence_index][0] == 0)
            cond2 = (row["neck"][sequence_index][0] == 0 or row["nose"][sequence_index][0] == 0)
            if cond1 and cond2:
                if last_starting_point is None:
                    continue
                starting_point, ending_point = list(last_starting_point), list(last_ending_point)
            else:
                if row["leftShoulder"][sequence_index][0] != 0 and row["rightShoulder"][sequence_index][0] != 0:
                    ls = row["leftShoulder"][sequence_index]
                    rs = row["rightShoulder"][sequence_index]
                    head_metric = float((((ls[0] - rs[0]) ** 2) + ((ls[1] - rs[1]) ** 2)) ** 0.5)
                else:
                    neck = row["neck"][sequence_index]
                    nose = row["nose"][sequence_index]
                    head_metric = float((((neck[0] - nose[0]) ** 2) + ((neck[1] - nose[1]) ** 2)) ** 0.5)

                starting_point = [row["neck"][sequence_index][0] - 3 * head_metric, row["leftEye"][sequence_index][1] + head_metric]
                ending_point = [row["neck"][sequence_index][0] + 3 * head_metric, starting_point[1] - 6 * head_metric]
                last_starting_point, last_ending_point = list(starting_point), list(ending_point)

            starting_point[0] = max(starting_point[0], 0)
            starting_point[1] = max(starting_point[1], 0)
            ending_point[0] = max(ending_point[0], 0)
            ending_point[1] = max(ending_point[1], 0)

            denom_x = ending_point[0] - starting_point[0]
            denom_y = starting_point[1] - ending_point[1]
            if denom_x == 0 or denom_y == 0:
                continue

            for identifier in BODY_IDENTIFIERS:
                if row[identifier][sequence_index][0] == 0:
                    continue
                normalized_x = (row[identifier][sequence_index][0] - starting_point[0]) / denom_x
                normalized_y = (row[identifier][sequence_index][1] - ending_point[1]) / denom_y
                row[identifier][sequence_index] = [float(normalized_x), float(normalized_y)]

        return row

    def _normalize_single_hand_dict(self, row: Dict[str, List[List[float]]]) -> Dict[str, List[List[float]]]:
        range_hand_size = 2 if "wrist_1" in row else 1
        hand_landmarks = {i: [f"{identifier}_{i}" for identifier in HAND_IDENTIFIERS] for i in range(range_hand_size)}

        for hand_index in range(range_hand_size):
            sequence_size = len(row[f"wrist_{hand_index}"])
            for sequence_index in range(sequence_size):
                landmarks_x_values = [row[key][sequence_index][0] for key in hand_landmarks[hand_index] if row[key][sequence_index][0] != 0]
                landmarks_y_values = [row[key][sequence_index][1] for key in hand_landmarks[hand_index] if row[key][sequence_index][1] != 0]
                if not landmarks_x_values or not landmarks_y_values:
                    continue

                width = max(landmarks_x_values) - min(landmarks_x_values)
                height = max(landmarks_y_values) - min(landmarks_y_values)
                if width > height:
                    delta_x = 0.1 * width
                    delta_y = delta_x + ((width - height) / 2)
                else:
                    delta_y = 0.1 * height
                    delta_x = delta_y + ((height - width) / 2)

                starting_point = (min(landmarks_x_values) - delta_x, min(landmarks_y_values) - delta_y)
                ending_point = (max(landmarks_x_values) + delta_x, max(landmarks_y_values) + delta_y)
                denom_x = ending_point[0] - starting_point[0]
                denom_y = ending_point[1] - starting_point[1]
                if denom_x == 0 or denom_y == 0:
                    continue

                for identifier in HAND_IDENTIFIERS:
                    key = f"{identifier}_{hand_index}"
                    if row[key][sequence_index][0] == 0:
                        continue
                    normalized_x = (row[key][sequence_index][0] - starting_point[0]) / denom_x
                    normalized_y = (row[key][sequence_index][1] - starting_point[1]) / denom_y
                    row[key][sequence_index] = [float(normalized_x), float(normalized_y)]

        return row

    def _sequence_to_model_input(self, seq: Dict[str, np.ndarray]) -> np.ndarray:
        seq = {k: np.asarray(v, dtype=np.float32).copy() for k, v in seq.items()}
        for k in list(seq.keys()):
            seq[k] = seq[k].tolist()

        seq = self._normalize_single_body_dict(seq)
        seq = self._normalize_single_hand_dict(seq)

        data = np.empty((len(seq["leftEar"]), len(MODEL_KEYPOINTS), 2), dtype=np.float32)
        for idx, identifier in enumerate(MODEL_KEYPOINTS):
            data[:, idx, 0] = np.asarray([frame[0] for frame in seq[identifier]], dtype=np.float32)
            data[:, idx, 1] = np.asarray([frame[1] for frame in seq[identifier]], dtype=np.float32)

        data = data - 0.5
        return data[np.newaxis, ...].astype(np.float32)

    def preprocess_records(self, records: List[FrameRecord]) -> Tuple[np.ndarray, SegmentResult, dict]:
        seg = self.find_segments(records)
        debug = {
            "status": seg.status,
            "segment_count": seg.segment_count,
            "start_idx": seg.start_idx,
            "end_idx": seg.end_idx,
            "message": seg.message,
            "total_frames": len(records),
        }

        if seg.status not in {"ok", "multiple_segments_kept_first"}:
            raise RuntimeError(json.dumps(debug, ensure_ascii=False))

        selected = records[seg.start_idx: seg.end_idx + 1]
        seq = self._records_to_sequence(selected)
        idx = self._resample_indices(len(selected), self.config.target_frames)
        seq = {k: arr[idx] for k, arr in seq.items()}
        seq = self._remove_all_zeros(seq)

        if self.config.force_no_zero:
            for key, arr in seq.items():
                if np.any(arr == 0):
                    raise RuntimeError(f"Joint {key} still contains zero values after repair.")

        model_input = self._sequence_to_model_input(seq)
        debug["selected_frames"] = len(selected)
        debug["resampled_frames"] = self.config.target_frames
        return model_input, seg, debug


# =============================================================================
# 6) ONNX CLASSIFIER
# =============================================================================

class SpoterOnnxClassifier:
    def __init__(self, model_path: str, label_path: str):
        self.labels = self._load_labels(label_path)
        self.session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

    @staticmethod
    def _load_labels(label_path: str) -> List[str]:
        text = Path(label_path).read_text(encoding="utf-8")
        labels = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            line = re.sub(r"^\s*\d+\.\s*", "", line)
            if line:
                labels.append(line)
        return labels

    def predict_from_input(self, model_input: np.ndarray) -> Tuple[dict, float]:
        t0 = time.perf_counter()
        logits = self.session.run([self.output_name], {self.input_name: model_input})[0][0]
        infer_ms = (time.perf_counter() - t0) * 1000.0

        probs = np.exp(logits - np.max(logits))
        probs = probs / np.sum(probs)
        pred_index = int(np.argmax(probs))
        topk_idx = np.argsort(probs)[::-1][:5]

        result = {
            "pred_index_0_based": pred_index,
            "pred_label_id_1_based": pred_index + 1,
            "pred_gloss": self.labels[pred_index] if pred_index < len(self.labels) else str(pred_index + 1),
            "confidence": float(probs[pred_index]),
            "top5": [
                {
                    "label_id": int(i + 1),
                    "gloss": self.labels[i] if i < len(self.labels) else str(i + 1),
                    "probability": float(probs[i]),
                }
                for i in topk_idx
            ],
        }
        return result, infer_ms


# =============================================================================
# 7) REALTIME NODE
# =============================================================================

class RDKX5SpoterNode(Node):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__("rdk_x5_spoter_without_mediapipe")

        self.args = args
        self.config = DeployConfig(
            target_frames=args.target_frames,
            start_consec_frames=args.start_consec_frames,
            end_consec_frames=args.end_consec_frames,
            sync_tolerance_ms=args.sync_tolerance_ms,
            frame_buffer_max=args.frame_buffer_max,
            dump_jsonl_path=args.dump_jsonl,
            hold_result_seconds=args.hold_result_seconds,
            flush_idle_ms=args.flush_idle_ms,
            infer_margin_frames=args.infer_margin_frames,
            segment_tail_grace_ms=args.segment_tail_grace_ms,
        )

        self.extractor = MessageExtractor()
        self.preprocessor = SpoterPreprocessor(self.config)
        self.classifier = SpoterOnnxClassifier(args.model, args.labels)

        self.body_cache: Deque[CachedMsg] = deque(maxlen=args.msg_cache_max)
        self.hand_cache: Deque[CachedMsg] = deque(maxlen=args.msg_cache_max)
        self.records: List[FrameRecord] = []
        self.frame_counter = 0

        self.last_result_wall_until = 0.0
        self.last_prediction: Optional[dict] = None
        self.recording_enabled = False
        self.result_callback_url = (os.getenv("SIGN_RESULT_CALLBACK_URL") or "http://127.0.0.1:8001/sign/result").strip()
        self.result_callback_timeout_sec = float(os.getenv("SIGN_RESULT_REPORT_TIMEOUT_SEC", "0.4"))
        self.result_callback_workers = int(os.getenv("SIGN_RESULT_REPORT_WORKERS", "2"))
        self.result_pub = self.create_publisher(String, "/sign_result", 10)
        self.record_sub = self.create_subscription(Bool, "/start_recording", self.recording_callback, 10)

        # performance stats
        self.classifier_infer_ms_hist: List[float] = []
        self.pipeline_ms_hist: List[float] = []
        self.end_to_result_wall_ms_hist: List[float] = []
        self.end_to_result_stream_ms_hist: List[float] = []
        self.rdk_hand_infer_ms_hist: List[float] = []
        self.rdk_hand_parse_ms_hist: List[float] = []

        self._report_executor = ThreadPoolExecutor(max_workers=max(1, self.result_callback_workers), thread_name_prefix="sign-report")
        self._report_session = requests.Session()
        self.last_synced_body: Optional[CachedMsg] = None
        self.last_synced_hand: Optional[CachedMsg] = None
        self.last_frame_monotonic: float = 0.0
        self.flush_timer = self.create_timer(0.05, self._flush_pending_segment)

        self.body_sub = self.create_subscription(
            PerceptionTargets,
            args.body_topic,
            self.body_callback,
            10,
        )
        self.hand_sub = self.create_subscription(
            PerceptionTargets,
            args.hand_topic,
            self.hand_callback,
            10,
        )

        self.get_logger().info(f"body topic : {args.body_topic}")
        self.get_logger().info(f"hand topic : {args.hand_topic}")
        self.get_logger().info(f"onnx model : {args.model}")
        self.get_logger().info(f"labels     : {args.labels}")
        self.get_logger().info("No drawing, no cv_bridge, no MediaPipe.")
        self.get_logger().info(
            f"low-latency config: target_frames={self.config.target_frames}, start_consec_frames={self.config.start_consec_frames}, end_consec_frames={self.config.end_consec_frames}, sync_tolerance_ms={self.config.sync_tolerance_ms}, flush_idle_ms={self.config.flush_idle_ms}, infer_margin_frames={self.config.infer_margin_frames}, segment_tail_grace_ms={self.config.segment_tail_grace_ms}"
        )

        self._check_mapping_sanity()

    def _check_mapping_sanity(self) -> None:
        if not RDK_BODY_INDEX_TO_NAME:
            self.get_logger().warn("RDK_BODY_INDEX_TO_NAME is still empty. You MUST fill the body mapping.")
        if len(RDK_HAND_INDEX_TO_MP_INDEX) == 0:
            self.get_logger().warn("RDK_HAND_INDEX_TO_MP_INDEX is empty. You MUST fill the hand mapping.")
        bad_names = [v for v in RDK_BODY_INDEX_TO_NAME.values() if v not in (set(BODY_IDENTIFIERS) | {"leftHip", "rightHip"})]
        if bad_names:
            self.get_logger().warn(f"Unknown body names in RDK_BODY_INDEX_TO_NAME: {bad_names}")

    def body_callback(self, msg: PerceptionTargets) -> None:
        self.body_cache.append(CachedMsg(msg_stamp_to_ns(msg), msg, time.monotonic()))
        self.try_process_pair(trigger="body")

    def hand_callback(self, msg: PerceptionTargets) -> None:
        self.hand_cache.append(CachedMsg(msg_stamp_to_ns(msg), msg, time.monotonic()))
        self.collect_rdk_perf(msg)
        self.try_process_pair(trigger="hand")

    def recording_callback(self, msg: Bool) -> None:
        enabled = bool(msg.data)
        if enabled != self.recording_enabled:
            self.recording_enabled = enabled
            self.records = []
            self.body_cache.clear()
            self.hand_cache.clear()
            self.last_synced_body = None
            self.last_synced_hand = None
            self.last_frame_monotonic = 0.0
            state_payload = {"enabled": self.recording_enabled, "ts": time.time()}
            self.get_logger().info("[SIGN_STATE] " + json.dumps(state_payload, ensure_ascii=False))

    def collect_rdk_perf(self, hand_msg: PerceptionTargets) -> None:
        for perf in safe_get_attr(hand_msg, "perfs", []):
            ptype = str(safe_get_attr(perf, "type", ""))
            dur = float(safe_get_attr(perf, "time_ms_duration", 0.0))
            if dur <= 0:
                continue
            if "predict_infer" in ptype:
                self.rdk_hand_infer_ms_hist.append(dur)
            elif "predict_parse" in ptype:
                self.rdk_hand_parse_ms_hist.append(dur)

    def try_process_pair(self, trigger: str) -> None:
        if not self.body_cache or not self.hand_cache:
            return

        # process oldest hand msg against nearest body msg
        hand_cached = self.hand_cache[0]
        best_body = self.find_nearest_msg(self.body_cache, hand_cached.stamp_ns, self.config.sync_tolerance_ms)
        if best_body is None:
            # if too old and unmatched, drop
            if len(self.hand_cache) > 1:
                self.hand_cache.popleft()
            return

        self.hand_cache.popleft()
        self.last_synced_body = best_body
        self.last_synced_hand = hand_cached
        self.process_synced_messages(best_body, hand_cached)

        # remove outdated body cache items
        latest_hand_ns = hand_cached.stamp_ns
        cutoff = latest_hand_ns - int(max(self.config.sync_tolerance_ms, 200) * 1_000_000)
        while self.body_cache and self.body_cache[0].stamp_ns < cutoff:
            self.body_cache.popleft()

    @staticmethod
    def find_nearest_msg(cache: Deque[CachedMsg], stamp_ns: int, tolerance_ms: int) -> Optional[CachedMsg]:
        if not cache:
            return None
        best = None
        best_delta = None
        for item in cache:
            delta = abs(item.stamp_ns - stamp_ns)
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best = item
        if best is not None and best_delta is not None and best_delta <= tolerance_ms * 1_000_000:
            return best
        return None

    def process_synced_messages(self, body_cached: CachedMsg, hand_cached: CachedMsg) -> None:
        t_pipeline_start = time.perf_counter()

        body_msg = body_cached.msg
        hand_msg = hand_cached.msg
        stamp_ns = hand_cached.stamp_ns

        body_named = self.extractor.extract_body_named_points(body_msg)
        hand_candidates = self.extractor.extract_hand_candidates(hand_msg)
        hand_left, hand_right = self.extractor.assign_two_hands_to_left_right(hand_candidates, body_named)

        width, height = self.estimate_frame_size(body_msg, hand_msg, body_named, hand_left, hand_right)
        rec = self.preprocessor.make_frame_record(
            frame_index=self.frame_counter,
            timestamp_ns=stamp_ns,
            width=width,
            height=height,
            body_named=body_named,
            hand_left=hand_left,
            hand_right=hand_right,
        )
        self.frame_counter += 1
        self.records.append(rec)
        if len(self.records) > self.config.frame_buffer_max:
            self.records = self.records[-self.config.frame_buffer_max:]

        self.last_frame_monotonic = time.monotonic()
        self.try_run_inference(body_cached, hand_cached, trigger="frame", force=False)

        pipeline_ms = (time.perf_counter() - t_pipeline_start) * 1000.0
        self.pipeline_ms_hist.append(pipeline_ms)

        if self.frame_counter % 30 == 0:
            self.print_stats()

    def estimate_frame_size(
        self,
        body_msg: PerceptionTargets,
        hand_msg: PerceptionTargets,
        body_named: Dict[str, Tuple[float, float]],
        hand_left: Dict[str, Tuple[float, float]],
        hand_right: Dict[str, Tuple[float, float]],
    ) -> Tuple[int, int]:
        # There may be no explicit image width/height in the message.
        # So we estimate a canvas size from existing points.
        points = []

        for v in body_named.values():
            if v != (0.0, 0.0):
                points.append(v)
        for v in hand_left.values():
            if v != (0.0, 0.0):
                points.append(v)
        for v in hand_right.values():
            if v != (0.0, 0.0):
                points.append(v)

        if not points:
            return 1920, 1080

        max_x = max(p[0] for p in points)
        max_y = max(p[1] for p in points)
        width = max(640, int(math.ceil(max_x + 10)))
        height = max(480, int(math.ceil(max_y + 10)))
        return width, height

    def _flush_pending_segment(self) -> None:
        if not self.recording_enabled or not self.records or self.last_synced_body is None or self.last_synced_hand is None:
            return
        if self.last_frame_monotonic <= 0:
            return
        idle_ms = (time.monotonic() - self.last_frame_monotonic) * 1000.0
        if idle_ms < self.config.flush_idle_ms:
            return
        self.try_run_inference(self.last_synced_body, self.last_synced_hand, trigger="idle_flush", force=True)

    def _can_finalize_segment(self, seg: SegmentResult, force: bool) -> bool:
        if seg.end_idx is None or not self.records:
            return False
        latest_idx = len(self.records) - 1
        trailing_frames = latest_idx - seg.end_idx
        if trailing_frames >= self.config.infer_margin_frames:
            return True
        if force:
            return True
        if trailing_frames < 0:
            return False
        tail_ms = ns_to_ms(self.records[-1].timestamp_ns - self.records[seg.end_idx].timestamp_ns)
        return tail_ms >= self.config.segment_tail_grace_ms

    def try_run_inference(self, body_cached: CachedMsg, hand_cached: CachedMsg, trigger: str = "frame", force: bool = False) -> None:
        if not self.records:
            return

        try:
            seg = self.preprocessor.find_segments(self.records)
            if seg.status not in {"ok", "multiple_segments_kept_first"}:
                return
            if seg.end_idx is None:
                return
            if not self._can_finalize_segment(seg, force=force):
                return

            t0 = time.perf_counter()
            model_input, seg2, debug = self.preprocessor.preprocess_records(self.records)
            preprocess_ms = (time.perf_counter() - t0) * 1000.0

            pred, infer_ms = self.classifier.predict_from_input(model_input)
            result_wall = time.monotonic()

            if not self.recording_enabled:
                self.records = []
                return

            segment_records = self.records[seg2.start_idx: seg2.end_idx + 1]
            end_run_start_idx = self.find_terminal_end_run_start(segment_records)
            end_run_start_rec = segment_records[end_run_start_idx] if end_run_start_idx is not None else segment_records[-1]

            wall_latency_ms = (result_wall - hand_cached.arrival_monotonic) * 1000.0
            stream_latency_ms = ns_to_ms(hand_cached.stamp_ns - end_run_start_rec.timestamp_ns)

            self.classifier_infer_ms_hist.append(infer_ms)
            self.end_to_result_wall_ms_hist.append(wall_latency_ms)
            self.end_to_result_stream_ms_hist.append(stream_latency_ms)

            result = {
                **pred,
                "segment": {
                    "status": seg2.status,
                    "start_idx": seg2.start_idx,
                    "end_idx": seg2.end_idx,
                    "message": seg2.message,
                },
                "debug": debug,
                "speed": {
                    "classifier_infer_ms": infer_ms,
                    "classifier_fps": (1000.0 / infer_ms) if infer_ms > 0 else None,
                    "preprocess_ms": preprocess_ms,
                    "end_to_result_wall_ms": wall_latency_ms,
                    "end_to_result_stream_ms": stream_latency_ms,
                },
                "frame_timestamp_ns": hand_cached.stamp_ns,
                "trigger": trigger,
            }

            self.last_prediction = result
            self.last_result_wall_until = time.monotonic() + self.config.hold_result_seconds

            msg = String()
            msg.data = result["pred_gloss"]
            self.result_pub.publish(msg)

            sign_event = {
                "label": result.get("pred_gloss", ""),
                "confidence": result.get("confidence", 0.0),
                "frame_timestamp_ns": hand_cached.stamp_ns,
                "segment": result.get("segment", {}),
                "speed": result.get("speed", {}),
                "trigger": trigger,
            }
            report_start = time.perf_counter()
            self._report_sign_event(sign_event)
            report_enqueue_ms = (time.perf_counter() - report_start) * 1000.0
            self.get_logger().info(
                f"sign inference ready trigger={trigger} gloss={sign_event['label']} preprocess_ms={preprocess_ms:.1f} infer_ms={infer_ms:.1f} wall_latency_ms={wall_latency_ms:.1f} stream_latency_ms={stream_latency_ms:.1f} callback_enqueue_ms={report_enqueue_ms:.1f}"
            )
            self.get_logger().info("[SIGN_RESULT] " + json.dumps(sign_event, ensure_ascii=False))
            self.get_logger().info(json.dumps(result, ensure_ascii=False))

            if self.config.dump_jsonl_path:
                with Path(self.config.dump_jsonl_path).open("a", encoding="utf-8") as f:
                    f.write(json.dumps(result, ensure_ascii=False) + "\n")

            self.records = []

        except Exception as e:
            self.get_logger().debug(f"inference skipped trigger={trigger}: {e}")

    def _report_sign_event(self, sign_event: dict[str, Any]) -> None:
        if not self.result_callback_url:
            return

        callback_url = self.result_callback_url
        timeout_sec = self.result_callback_timeout_sec
        logger = self.get_logger()
        enqueue_monotonic = time.monotonic()

        def _send() -> None:
            send_started = time.monotonic()
            try:
                self._report_session.post(
                    callback_url,
                    json=sign_event,
                    timeout=timeout_sec,
                )
                logger.info(
                    f"sign callback done label={sign_event.get('label', '')} queue_wait_ms={(send_started - enqueue_monotonic) * 1000.0:.1f} http_ms={(time.monotonic() - send_started) * 1000.0:.1f}"
                )
            except Exception as exc:
                logger.debug(f"sign event report failed asynchronously: {exc}")

        try:
            self._report_executor.submit(_send)
        except Exception as exc:
            logger.debug(f"sign event report submit failed: {exc}")

    def find_terminal_end_run_start(self, segment_records: List[FrameRecord]) -> Optional[int]:
        if not segment_records:
            return None
        run = 0
        start_idx = None
        for i in range(len(segment_records) - 1, -1, -1):
            if segment_records[i].end_active:
                run += 1
                start_idx = i
            else:
                if run > 0:
                    break
        return start_idx

    def destroy_node(self) -> bool:
        try:
            self._report_session.close()
        except Exception:
            pass
        try:
            self._report_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        return super().destroy_node()

    def print_stats(self) -> None:
        payload = {
            "stats": {
                "classifier_infer_ms_avg": self.safe_mean(self.classifier_infer_ms_hist),
                "classifier_infer_fps_avg": self.safe_fps(self.classifier_infer_ms_hist),
                "pipeline_ms_avg": self.safe_mean(self.pipeline_ms_hist),
                "end_to_result_wall_ms_avg": self.safe_mean(self.end_to_result_wall_ms_hist),
                "end_to_result_stream_ms_avg": self.safe_mean(self.end_to_result_stream_ms_hist),
                "rdk_hand_node_infer_ms_avg": self.safe_mean(self.rdk_hand_infer_ms_hist),
                "rdk_hand_node_parse_ms_avg": self.safe_mean(self.rdk_hand_parse_ms_hist),
            }
        }
        self.get_logger().info(json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def safe_mean(values: Sequence[float]) -> Optional[float]:
        vals = [float(x) for x in values if x is not None]
        if not vals:
            return None
        return float(statistics.mean(vals))

    @staticmethod
    def safe_fps(ms_values: Sequence[float]) -> Optional[float]:
        vals = [float(x) for x in ms_values if x and x > 0]
        if not vals:
            return None
        return float(1000.0 / statistics.mean(vals))


# =============================================================================
# 8) ENTRYPOINT
# =============================================================================

def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RDK X5 SPOTER recognizer without MediaPipe")
    parser.add_argument("--model", required=False, default=os.getenv("SIGN_MODEL_PATH", "models/gesture_model.onnx"), help="Path to ONNX model")
    parser.add_argument("--labels", required=False, default=os.getenv("SIGN_LABEL_PATH", "models/labels.txt"), help="Path to label txt")
    parser.add_argument("--body-topic", default="/hobot_mono2d_body_detection")
    parser.add_argument("--hand-topic", default="/hobot_hand_lmk_detection")
    parser.add_argument("--target-frames", type=int, default=int(os.getenv("SIGN_TARGET_FRAMES", "32")))
    parser.add_argument("--start-consec-frames", type=int, default=int(os.getenv("SIGN_START_CONSEC_FRAMES", "2")))
    parser.add_argument("--end-consec-frames", type=int, default=int(os.getenv("SIGN_END_CONSEC_FRAMES", "4")))
    parser.add_argument("--sync-tolerance-ms", type=int, default=int(os.getenv("SIGN_SYNC_TOLERANCE_MS", "50")))
    parser.add_argument("--frame-buffer-max", type=int, default=240)
    parser.add_argument("--msg-cache-max", type=int, default=60)
    parser.add_argument("--hold-result-seconds", type=float, default=float(os.getenv("SIGN_HOLD_RESULT_SECONDS", "2.0")))
    parser.add_argument("--flush-idle-ms", type=int, default=int(os.getenv("SIGN_FLUSH_IDLE_MS", "120")))
    parser.add_argument("--infer-margin-frames", type=int, default=int(os.getenv("SIGN_INFER_MARGIN_FRAMES", "1")))
    parser.add_argument("--segment-tail-grace-ms", type=int, default=int(os.getenv("SIGN_SEGMENT_TAIL_GRACE_MS", "80")))
    parser.add_argument("--dump-jsonl", default="", help="Optional output JSONL for predictions")
    return parser


def main() -> None:
    parser = build_argparser()
    args = parser.parse_args()

    rclpy.init()
    node = RDKX5SpoterNode(args)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
