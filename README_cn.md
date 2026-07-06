# 手语识别与交互系统

## 项目简介

本项目是一个面向手语识别、语音交互和动作反馈的综合交互系统。系统围绕“手势输入识别、文本语义整理、语音指令转换、对话式交互、前端可视化、设备动作下发”构建完整链路，适用于手语辅助沟通、人机交互演示、无障碍交互原型和智能终端控制等场景。

项目采用前后端协同架构：前端使用 NiceGUI 构建触控式 Web 界面，后端使用 FastAPI 维护系统状态、任务调度和接口通信，识别侧通过 ROS 节点接入手部关键点数据，并通过 ONNX Runtime 执行手语分类推理。系统还提供语音文本转换、词表映射、对话回复、串口任务队列和本地语音播放等服务模块，使识别结果能够进一步参与交互控制流程。

## 功能特性

- 手语识别流程：接收手部关键点序列，构建时间窗口，调用 ONNX 推理接口输出手语标签。
- 识别结果管理：对识别词序列进行去重、整理、会话保存和前端实时展示。
- 语音交互流程：支持语音文本输入、词表匹配、动作编号映射和串口任务下发。
- 对话交互流程：根据用户输入生成回复文本，并转换为可执行的手语动作序列。
- Web 可视化界面：提供首页、手语识别页、语音交互页和对话交互页。
- 实时状态同步：后端通过 WebSocket 将识别状态、任务状态和交互结果推送到前端。
- 进程编排能力：统一管理关键点进程、识别进程、语音进程和串口任务队列。
- 模块化服务层：会话存储、文本整理、词表映射、对话服务、播放服务和串口服务相互解耦，便于扩展。

## 技术栈

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

## 目录结构

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

## 系统架构

系统由四个主要层次组成：

### 1. 前端交互层

`web_ui/` 目录负责构建用户交互界面。前端页面通过 HTTP API 调用后端任务接口，并通过 WebSocket 监听系统事件。主要页面包括：

- 首页：展示系统入口和模块导航。
- 手语识别页：启动识别任务、展示识别结果和会话状态。
- 语音交互页：输入语音识别文本，并展示转换后的手语词条与动作编号。
- 对话交互页：完成用户文本输入、系统回复和动作序列生成。

### 2. 后端编排层

`orchestrator/` 是系统调度中心，负责接收前端请求、管理任务状态、调度 ROS 相关进程、维护会话结果并向前端推送事件。

核心文件包括：

- `app.py`：FastAPI 应用入口，定义 REST API 和 WebSocket 接口。
- `task_hub.py`：系统核心调度器，封装手语识别、语音交互、对话交互和串口发送流程。
- `broadcast.py`：WebSocket 广播管理，用于实时推送状态变化。
- `ros_process_manager.py`：ROS 进程管理封装，用于启动、停止和维护外部识别进程。

### 3. 识别推理层

`ros_nodes/hand_subscriber.py` 是手语识别流程的入口文件。该模块订阅手部关键点数据，将连续帧组织为模型输入序列，并调用 ONNX Runtime 完成分类推理。识别得到的标签结果会通过后端接口回传到编排层，再由编排层写入会话并推送到前端页面。

主要流程如下：

```text
手部关键点输入
    ↓
关键点帧缓存
    ↓
时序窗口构建
    ↓
ONNX Runtime 推理
    ↓
标签解析
    ↓
结果回传后端
    ↓
前端实时展示
```

### 4. 服务能力层

`services/` 目录封装业务服务能力，各模块职责清晰：

- `sign_text_service.py`：负责手语识别词序列的整理、去重和格式化。
- `voice_mapper_service.py`：负责文本到手语词条的匹配，以及词条到动作编号的映射。
- `dialog_service.py`：负责对话文本生成和后续动作序列转换。
- `playback_service.py`：负责本地音频播放接口和词条音频索引。
- `sign_session_store.py`：负责手语识别会话的保存和读取。
- `voice_session_store.py`：负责语音交互会话的保存和读取。
- `serial_stub.py`：负责串口任务的封装和队列式发送接口。

## 代码实现流程

### 手语识别流程

1. 前端点击开始识别。
2. 后端 `TaskHub` 启动关键点处理与识别进程。
3. ROS 节点持续接收手部关键点数据。
4. 节点将关键点序列整理为模型输入。
5. ONNX Runtime 执行推理并输出分类结果。
6. 识别结果转换为手语标签。
7. 后端保存结果并通过 WebSocket 推送到前端。

### 语音转手语流程

1. 前端提交语音识别后的文本。
2. 后端调用 `VoiceMapperService` 读取词表。
3. 服务根据词条规则匹配手语标签。
4. 系统将标签映射为动作编号。
5. `TaskHub` 创建串口任务。
6. 串口服务按顺序发送动作编号。

### 对话交互流程

1. 用户在对话页面输入文本。
2. `DialogService` 生成回复文本。
3. 回复文本进入词表映射流程。
4. 系统生成手语标签序列和动作编号序列。
5. 任务状态通过 WebSocket 实时同步到前端。
6. 串口发送模块执行对应动作序列。

## API 设计

后端 API 由 `orchestrator/app.py` 统一提供，主要包含以下类型：

- 系统状态接口：获取当前运行状态、任务状态和会话信息。
- 手语识别接口：启动识别、停止识别、提交识别结果、读取识别会话。
- 语音交互接口：提交语音文本、转换手语词条、生成动作编号。
- 对话交互接口：提交用户文本、生成回复、转换动作序列。
- WebSocket 接口：推送识别结果、任务状态和交互事件。

## 前端页面说明

`web_ui/pages/` 下的页面文件分别对应系统的主要交互入口。页面通过统一的 API 客户端与后端通信，并使用 WebSocket 保持实时更新。

常见页面职责：

- 展示当前任务状态。
- 发起识别或交互请求。
- 展示手语识别结果。
- 展示语音文本转换结果。
- 展示对话回复与动作编号。
- 反馈设备任务执行状态。

## 安装与启动

创建虚拟环境并安装依赖：

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

启动后端服务：

```bash
python -m orchestrator.app
```

启动前端页面：

```bash
python -m web_ui.app
```

默认情况下，前端页面通过 HTTP API 和 WebSocket 与后端编排服务通信。可根据部署环境调整服务端口、主机地址和相关路径配置。

## 扩展方向

- 接入更多手语类别和词表。
- 优化关键点序列的平滑与窗口策略。
- 增加更多交互场景和对话模板。
- 扩展串口协议以适配不同执行设备。
- 增强前端页面的数据可视化能力。
- 支持多用户会话和长期交互记录。
- 增加识别置信度展示和异常状态提示。

## License

This project can be released with a license that matches the competition or repository requirements.
