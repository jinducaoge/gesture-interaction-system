# Sign Language Recognition and Interaction System

## Overview

This project is an integrated interaction system for sign language recognition, voice-based control, and action feedback. It is designed around a complete workflow that includes gesture input recognition, text post-processing, voice command conversion, dialog interaction, frontend visualization, and device command dispatch.

The project uses a collaborative frontend-backend architecture. The frontend is built with NiceGUI as a touch-friendly web interface. The backend is built with FastAPI to manage task orchestration, runtime state, API communication, and WebSocket events. The recognition side connects to hand keypoint data through ROS nodes and performs sign classification through an ONNX Runtime inference pipeline. The service layer also provides text formatting, vocabulary mapping, dialog reply, serial job dispatch, and local playback interfaces.

## Features

- Sign recognition pipeline: receives hand keypoint sequences, builds temporal windows, and runs ONNX inference to produce sign labels.
- Recognition result management: deduplicates, formats, stores, and displays recognized sign sequences in real time.
- Voice interaction pipeline: converts input text into sign labels, maps labels to action IDs, and dispatches device jobs.
- Dialog interaction pipeline: generates response text and converts it into executable sign-action sequences.
- Web UI: provides pages for home, sign recognition, voice interaction, and dialog interaction.
- Real-time synchronization: pushes recognition events, task state, and interaction results to the frontend through WebSocket.
- Process orchestration: manages keypoint processes, recognition processes, voice flows, and serial job queues.
- Modular services: session storage, text formatting, vocabulary mapping, dialog handling, playback, and serial dispatch are separated for easier extension.

## Tech Stack

- Python
- FastAPI
- Uvicorn
- NiceGUI
- WebSocket
- ROS / ROS2
- ONNX Runtime
- NumPy
- Pydantic
- HTTPX / Requests
- Serial communication scaffold

## Repository Structure

```text
.
├── models/
│   ├── api.py
│   └── events.py
├── orchestrator/
│   ├── app.py
│   ├── broadcast.py
│   ├── ros_process_manager.py
│   └── task_hub.py
├── ros_nodes/
│   └── hand_subscriber.py
├── services/
│   ├── dialog_service.py
│   ├── playback_service.py
│   ├── serial_stub.py
│   ├── sign_session_store.py
│   ├── sign_text_service.py
│   ├── voice_mapper_service.py
│   └── voice_session_store.py
├── utils/
│   ├── ids.py
│   ├── logging.py
│   └── net.py
├── web_ui/
│   ├── app.py
│   └── pages/
├── requirements.txt
├── README_CN.md
└── README_EN.md
```

## Architecture

The system is organized into four main layers.

### 1. Frontend Interaction Layer

The `web_ui/` directory contains the user interface. Frontend pages call backend task APIs through HTTP and subscribe to real-time events through WebSocket.

Main pages include:

- Home page: navigation and system entry points.
- Sign recognition page: starts recognition tasks and displays recognition sessions.
- Voice interaction page: submits recognized speech text and displays converted sign labels and action IDs.
- Dialog interaction page: handles user text input, response generation, and action sequence output.

### 2. Backend Orchestration Layer

The `orchestrator/` directory is the scheduling center of the system. It receives frontend requests, manages task state, starts and stops ROS-related processes, maintains session results, and broadcasts events to the frontend.

Key files include:

- `app.py`: FastAPI application entry point for REST APIs and WebSocket routes.
- `task_hub.py`: central scheduler for sign recognition, voice interaction, dialog interaction, and serial dispatch.
- `broadcast.py`: WebSocket broadcast manager for real-time state updates.
- `ros_process_manager.py`: process management wrapper for launching and controlling external ROS processes.

### 3. Recognition and Inference Layer

`ros_nodes/hand_subscriber.py` is the entry point of the sign recognition pipeline. It subscribes to hand keypoint data, organizes continuous frames into model input sequences, and calls ONNX Runtime for classification. The recognized label is sent back to the backend orchestration layer, where it is stored in the session and pushed to the frontend.

Main pipeline:

```text
Hand keypoint input
    ↓
Keypoint frame buffer
    ↓
Temporal window construction
    ↓
ONNX Runtime inference
    ↓
Label decoding
    ↓
Backend result callback
    ↓
Frontend real-time display
```

### 4. Service Layer

The `services/` directory contains the business logic modules:

- `sign_text_service.py`: formats and deduplicates recognized sign-label sequences.
- `voice_mapper_service.py`: maps input text to sign labels and maps sign labels to action IDs.
- `dialog_service.py`: handles dialog reply generation and action sequence conversion.
- `playback_service.py`: provides local audio playback and word-audio lookup interfaces.
- `sign_session_store.py`: stores and reads sign recognition sessions.
- `voice_session_store.py`: stores and reads voice interaction sessions.
- `serial_stub.py`: wraps serial jobs and queue-style command dispatch.

## Implementation Flow

### Sign Recognition Flow

1. The frontend starts a recognition task.
2. `TaskHub` starts keypoint processing and recognition processes.
3. The ROS node continuously receives hand keypoint data.
4. The node converts keypoints into model input sequences.
5. ONNX Runtime performs classification inference.
6. The output is decoded into a sign label.
7. The backend stores the result and pushes updates to the frontend through WebSocket.

### Voice-to-Sign Flow

1. The frontend submits speech-recognition text.
2. The backend calls `VoiceMapperService` to load the vocabulary.
3. The service matches words and phrases against sign labels.
4. The system maps labels to action IDs.
5. `TaskHub` creates serial jobs.
6. The serial service sends action IDs in order.

### Dialog Interaction Flow

1. The user enters text on the dialog page.
2. `DialogService` generates a response.
3. The response enters the vocabulary mapping flow.
4. The system produces sign labels and action ID sequences.
5. Task state is synchronized to the frontend through WebSocket.
6. The serial dispatch module executes the action sequence.

## API Design

Backend APIs are defined in `orchestrator/app.py`. They are grouped into the following categories:

- System state APIs: read runtime state, task status, and session data.
- Sign recognition APIs: start recognition, stop recognition, submit recognition results, and read sessions.
- Voice interaction APIs: submit voice text, convert sign labels, and generate action IDs.
- Dialog interaction APIs: submit user text, generate replies, and convert action sequences.
- WebSocket API: push recognition results, task states, and interaction events.

## Frontend Pages

The files under `web_ui/pages/` correspond to the main interaction pages. They communicate with the backend through a shared API client and keep real-time updates through WebSocket.

Common page responsibilities:

- Display current task state.
- Start recognition or interaction requests.
- Show sign recognition results.
- Show voice text conversion results.
- Show dialog replies and action IDs.
- Display device task execution feedback.

## Installation and Startup

Create a virtual environment and install dependencies:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Start the backend service:

```bash
python -m orchestrator.app
```

Start the frontend UI:

```bash
python -m web_ui.app
```

The frontend communicates with the backend orchestration service through HTTP APIs and WebSocket connections. Host, port, and path settings can be adjusted according to the deployment environment.

## Extension Ideas

- Add more sign categories and vocabulary entries.
- Improve smoothing and temporal window strategies for keypoint sequences.
- Add more interaction scenes and dialog templates.
- Extend serial protocols for different execution devices.
- Improve frontend visualization for recognition confidence and task state.
- Support multi-user sessions and long-term interaction records.
- Add richer error feedback and runtime state indicators.

## License

This project can be released with a license that matches the competition or repository requirements.
