(function () {
  const registry = (window.__togetheROSNativeReceivers = window.__togetheROSNativeReceivers || {});

  function normalizeBytes(value) {
    if (!value) return null;
    if (value instanceof Uint8Array) return value;
    if (value instanceof ArrayBuffer) return new Uint8Array(value);
    if (Array.isArray(value)) return new Uint8Array(value);
    if (typeof value === 'string') {
      try {
        const binary = atob(value);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i += 1) {
          bytes[i] = binary.charCodeAt(i);
        }
        return bytes;
      } catch (error) {
        console.warn('[TogetheROS] failed to decode base64 bytes:', error);
        return null;
      }
    }
    return null;
  }


  function pick(obj, ...keys) {
    if (!obj) return undefined;
    for (const key of keys) {
      if (Object.prototype.hasOwnProperty.call(obj, key) && obj[key] != null) {
        return obj[key];
      }
    }
    return undefined;
  }

  class NativeTogetheROSPreview {
    constructor(config) {
      this.config = {
        reconnectBaseMs: 1000,
        reconnectMaxMs: 10000,
        showOverlay: false,
        filterPrefix: '',
        ...config,
      };
      this.root =
        document.getElementById(this.config.rootId) ||
        document.querySelector(`[data-togetheros-root="${this.config.rootId}"]`);
      
      if (!this.root) {
        throw new Error(`preview root not found: ${this.config.rootId}`);
      }
      this.stage = this.root.querySelector('[data-role="stage"]');
      this.img = this.root.querySelector('[data-role="image"]');
      this.canvas = this.root.querySelector('[data-role="overlay"]');
      this.placeholder = this.root.querySelector('[data-role="placeholder"]');
      this.statusEl = this.root.querySelector('[data-role="status"]');
      this.fpsEl = this.root.querySelector('[data-role="fps"]');
      this.resolutionEl = this.root.querySelector('[data-role="resolution"]');
      this.overlayButton = this.root.querySelector('[data-role="overlay-toggle"]');
      this.messageEl = this.root.querySelector('[data-role="message"]');
      this.ctx = this.canvas.getContext('2d');
      this.showOverlay = !!this.config.showOverlay;
      this.frameCounter = 0;
      this.reconnectAttempts = 0;
      this.currentBlobUrl = null;
      this.pendingBlobUrl = null;
      this.currentMimeType = 'image/jpeg';
      this.currentFrame = null;
      this.currentImageSize = { width: 0, height: 0 };
      this.destroyed = false;
      this.ws = null;
      this.reconnectTimer = null;
      this.fpsTimer = null;
      this.lifecycleTimer = null;
      this.boundResize = () => this.renderOverlay();

      this.updateOverlayButton();
      this.setMessage('加载 x3.proto 中...');
      this.setStatus('初始化中', 'idle');
      this.bindEvents();
      this.startHousekeeping();
      this.loadProtoAndConnect();
    }

    bindEvents() {
      if (this.overlayButton) {
        this.overlayButton.addEventListener('click', () => {
          this.showOverlay = !this.showOverlay;
          this.updateOverlayButton();
          this.renderOverlay();
        });
      }
      window.addEventListener('resize', this.boundResize);
    }

    startHousekeeping() {
      this.fpsTimer = window.setInterval(() => {
        if (this.fpsEl) {
          this.fpsEl.textContent = `FPS ${this.frameCounter}`;
        }
        this.frameCounter = 0;
      }, 1000);

      this.lifecycleTimer = window.setInterval(() => {
        if (!document.getElementById(this.config.rootId)) {
          this.destroy();
        }
      }, 2000);
    }

    async loadProtoAndConnect() {
      try {
        if (!window.protobuf) {
          throw new Error('protobuf.js not loaded');
        }
        const response = await fetch(this.config.protoUrl, { cache: 'force-cache' });
        if (!response.ok) {
          throw new Error(`failed to fetch proto: ${response.status}`);
        }
        const protoText = await response.text();
        const parsed = window.protobuf.parse(protoText);
        this.FrameMessage = parsed.root.lookupType('x3.FrameMessage');
        this.setMessage('等待 websocket 视频流...');
        this.connect();
      } catch (error) {
        console.error('[TogetheROS] proto init failed:', error);
        this.setStatus('协议加载失败', 'error');
        this.setMessage(`协议初始化失败：${error.message || error}`);
      }
    }

    connect() {
      if (this.destroyed || !this.FrameMessage) return;
      this.clearReconnectTimer();
      this.cleanupSocket();

      this.setStatus('连接中', 'connecting');
      this.setMessage(`正在连接 ${this.config.wsUrl}`);

      try {
        this.ws = new WebSocket(this.config.wsUrl);
      } catch (error) {
        this.scheduleReconnect(`WebSocket 创建失败：${error.message || error}`);
        return;
      }

      this.ws.binaryType = 'arraybuffer';

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.setStatus('已连接', 'connected');
        this.setMessage(`已连接 ${this.config.wsUrl}${this.config.filterPrefix ? '，filter=' + this.config.filterPrefix : '，未发送 filter_prefix'}`);
        if (this.config.filterPrefix) {
          try {
            this.ws.send(JSON.stringify({ filter_prefix: this.config.filterPrefix }));
          } catch (error) {
            console.warn('[TogetheROS] failed to send filter_prefix:', error);
          }
        }
      };

      this.ws.onerror = () => {
        this.setStatus('连接异常', 'error');
        this.setMessage(`连接异常：${this.config.wsUrl}`);
      };

      this.ws.onclose = (event) => {
        if (this.destroyed) return;
        const reason = event && event.reason ? `，原因：${event.reason}` : '';
        this.scheduleReconnect(`连接已断开${reason}`);
      };

      this.ws.onmessage = async (event) => {
        try {
          const payload = event && event.data;
          if (!payload) return;
          if (typeof payload === 'string') {
            this.setMessage(`收到文本消息：${payload}`);
            return;
          }
          if (payload instanceof ArrayBuffer) {
            this.handleFrameBuffer(payload);
            return;
          }
          if (payload instanceof Blob) {
            const arrayBuffer = await payload.arrayBuffer();
            this.handleFrameBuffer(arrayBuffer);
            return;
          }
          this.setMessage(`收到未知消息类型：${Object.prototype.toString.call(payload)}`);
        } catch (error) {
          console.error('[TogetheROS] frame handling failed:', error);
          this.setMessage(`视频帧解析失败：${error.message || error}`);
        }
      };
    }

    handleFrameBuffer(buffer) {
      let message;
      let object;
      try {
        message = this.FrameMessage.decode(new Uint8Array(buffer));
        object = this.FrameMessage.toObject(message);
      } catch (error) {
        this.setMessage(`protobuf 解码失败：${error.message || error}`);
        throw error;
      }
      const image = object && (pick(object, 'img_', 'img') || null);
      const imageBuf = pick(image, 'buf_', 'buf');
      if (!image || !imageBuf) {
        this.setMessage('已收到 websocket 消息，但当前帧里没有 img_.buf_');
        return;
      }

      const bytes = normalizeBytes(imageBuf);
      if (!bytes || !bytes.length) {
        this.setMessage('已收到 img_.buf_，但字节为空');
        return;
      }

      const imageType = String(pick(image, 'type_', 'type') || 'JPEG').toUpperCase();
      const frame = {
        imageWidth: pick(image, 'width_', 'width') || 1920,
        imageHeight: pick(image, 'height_', 'height') || 1080,
        imageType,
        mimeType: this.resolveMimeType(imageType),
        imageBytes: bytes,
        targets: this.extractTargets(object && (pick(object, 'smartMsg_', 'smart_msg_', 'smartMsg', 'smart_msg') || null)),
      };
      this.renderFrame(frame);
    }

    extractTargets(smartMessage) {
      const targets = smartMessage && (pick(smartMessage, 'targets_', 'targets') || null);
      if (!Array.isArray(targets) || !targets.length) return [];
      return targets.map((target) => {
        const boxes = [];
        const points = [];

        const ownBoxes = Array.isArray(pick(target, 'boxes_', 'boxes')) ? pick(target, 'boxes_', 'boxes') : [];
        ownBoxes.forEach((box) => {
          const normalized = this.normalizeBox(box, pick(target, 'trackId_', 'track_id_', 'trackId', 'track_id'));
          if (normalized) boxes.push(normalized);
        });

        const ownPoints = Array.isArray(pick(target, 'points_', 'points')) ? pick(target, 'points_', 'points') : [];
        ownPoints.forEach((group) => {
          const pointList = Array.isArray(pick(group, 'points_', 'points')) ? pick(group, 'points_', 'points') : [];
          pointList.forEach((point) => {
            const normalized = this.normalizePoint(point, pick(group, 'type_', 'type') || 'points');
            if (normalized) points.push(normalized);
          });
        });

        const subTargets = Array.isArray(pick(target, 'subTargets_', 'sub_targets_', 'subTargets', 'sub_targets')) ? pick(target, 'subTargets_', 'sub_targets_', 'subTargets', 'sub_targets') : [];
        subTargets.forEach((subTarget) => {
          const subBoxes = Array.isArray(pick(subTarget, 'boxes_', 'boxes')) ? pick(subTarget, 'boxes_', 'boxes') : [];
          subBoxes.forEach((box) => {
            const normalized = this.normalizeBox(box, pick(subTarget, 'trackId_', 'track_id_', 'trackId', 'track_id'));
            if (normalized) boxes.push(normalized);
          });
        });

        return { boxes, points };
      });
    }

    normalizeBox(box, trackId) {
      const topLeft = box && (pick(box, 'topLeft_', 'top_left_', 'topLeft', 'top_left') || null);
      const bottomRight = box && (pick(box, 'bottomRight_', 'bottom_right_', 'bottomRight', 'bottom_right') || null);
      if (!topLeft || !bottomRight) return null;
      const x1 = Number(pick(topLeft, 'x_', 'x'));
      const y1 = Number(pick(topLeft, 'y_', 'y'));
      const x2 = Number(pick(bottomRight, 'x_', 'x'));
      const y2 = Number(pick(bottomRight, 'y_', 'y'));
      if (![x1, y1, x2, y2].every(Number.isFinite)) return null;
      return {
        type: pick(box, 'type_', 'type') || '',
        trackId: Number.isFinite(Number(trackId)) ? Number(trackId) : null,
        x1,
        y1,
        x2,
        y2,
      };
    }

    resolveMimeType(imageType) {
      const normalized = String(imageType || '').trim().toUpperCase();
      if (normalized.includes('PNG')) return 'image/png';
      if (normalized.includes('WEBP')) return 'image/webp';
      if (normalized.includes('BMP')) return 'image/bmp';
      if (normalized.includes('JPEG') || normalized.includes('JPG') || !normalized) return 'image/jpeg';
      return 'image/jpeg';
    }

    normalizePoint(point, type) {
      const x = Number(point && pick(point, 'x_', 'x'));
      const y = Number(point && pick(point, 'y_', 'y'));
      if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
      return {
        type: type || 'points',
        x,
        y,
        score: Number(point && pick(point, 'score_', 'score')) || 0,
      };
    }

    renderFrame(frame) {
      const previousCommittedUrl = this.currentBlobUrl;
      this.currentMimeType = frame.mimeType || 'image/jpeg';
      const objectUrl = URL.createObjectURL(new Blob([frame.imageBytes], { type: this.currentMimeType }));
      if (this.pendingBlobUrl && this.pendingBlobUrl !== this.currentBlobUrl) {
        URL.revokeObjectURL(this.pendingBlobUrl);
      }
      this.pendingBlobUrl = objectUrl;
      this.currentFrame = frame;
      this.currentImageSize = { width: frame.imageWidth, height: frame.imageHeight };

      this.img.onload = () => {
        this.frameCounter += 1;
        this.placeholder.style.display = 'none';
        this.updateResolution();
        this.setMessage(`视频流正常：${frame.imageWidth}×${frame.imageHeight} / ${frame.imageType || 'JPEG'}`);
        this.renderOverlay();
        if (previousCommittedUrl && previousCommittedUrl !== objectUrl) {
          URL.revokeObjectURL(previousCommittedUrl);
        }
        this.currentBlobUrl = objectUrl;
        if (this.pendingBlobUrl === objectUrl) {
          this.pendingBlobUrl = null;
        }
      };
      this.img.onerror = () => {
        if (objectUrl) {
          URL.revokeObjectURL(objectUrl);
        }
        if (this.pendingBlobUrl === objectUrl) {
          this.pendingBlobUrl = null;
        }
      };
      this.img.src = objectUrl;
    }

    updateResolution() {
      if (this.resolutionEl) {
        const { width, height } = this.currentImageSize;
        this.resolutionEl.textContent = width && height ? `${width}×${height}` : '--';
      }
    }

    renderOverlay() {
      const ctx = this.ctx;
      const stageWidth = this.stage.clientWidth;
      const stageHeight = this.stage.clientHeight;
      if (!ctx || !stageWidth || !stageHeight) return;

      const dpr = window.devicePixelRatio || 1;
      this.canvas.width = Math.max(1, Math.floor(stageWidth * dpr));
      this.canvas.height = Math.max(1, Math.floor(stageHeight * dpr));
      this.canvas.style.width = `${stageWidth}px`;
      this.canvas.style.height = `${stageHeight}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, stageWidth, stageHeight);

      if (!this.showOverlay || !this.currentFrame || !this.currentFrame.targets || !this.currentFrame.targets.length) {
        return;
      }

      const imageWidth = this.currentFrame.imageWidth;
      const imageHeight = this.currentFrame.imageHeight;
      if (!imageWidth || !imageHeight) return;

      const scale = Math.min(stageWidth / imageWidth, stageHeight / imageHeight);
      const drawWidth = imageWidth * scale;
      const drawHeight = imageHeight * scale;
      const offsetX = (stageWidth - drawWidth) / 2;
      const offsetY = (stageHeight - drawHeight) / 2;

      ctx.lineWidth = 2;
      ctx.font = '12px sans-serif';
      ctx.textBaseline = 'top';

      this.currentFrame.targets.forEach((target) => {
        target.boxes.forEach((box) => {
          const x = offsetX + box.x1 * scale;
          const y = offsetY + box.y1 * scale;
          const w = (box.x2 - box.x1) * scale;
          const h = (box.y2 - box.y1) * scale;
          ctx.strokeStyle = '#22d3ee';
          ctx.fillStyle = 'rgba(34, 211, 238, 0.12)';
          ctx.strokeRect(x, y, w, h);
          ctx.fillRect(x, y, w, h);
          const label = box.type || (box.trackId != null ? `id:${box.trackId}` : 'box');
          const textY = Math.max(0, y - 16);
          ctx.fillStyle = 'rgba(2, 6, 23, 0.88)';
          const textWidth = ctx.measureText(label).width + 10;
          ctx.fillRect(x, textY, textWidth, 16);
          ctx.fillStyle = '#e2e8f0';
          ctx.fillText(label, x + 5, textY + 2);
        });

        target.points.forEach((point) => {
          const x = offsetX + point.x * scale;
          const y = offsetY + point.y * scale;
          ctx.fillStyle = '#f59e0b';
          ctx.beginPath();
          ctx.arc(x, y, 2.5, 0, Math.PI * 2);
          ctx.fill();
        });
      });
    }

    updateOverlayButton() {
      if (!this.overlayButton) return;
      this.overlayButton.textContent = this.showOverlay ? 'Overlay 开' : 'Overlay 关';
      this.overlayButton.dataset.active = this.showOverlay ? '1' : '0';
    }

    setStatus(text, tone) {
      if (!this.statusEl) return;
      this.statusEl.textContent = text;
      this.statusEl.dataset.state = tone || 'idle';
    }

    setMessage(text) {
      if (this.messageEl) {
        this.messageEl.textContent = text || '';
      }
      if (this.placeholder && (!this.img.getAttribute('src') || !this.img.getAttribute('src').length)) {
        this.placeholder.textContent = text || '等待视频流...';
      }
    }

    scheduleReconnect(reasonText) {
      if (this.destroyed) return;
      const delay = Math.min(
        this.config.reconnectMaxMs,
        this.config.reconnectBaseMs * Math.pow(1.6, this.reconnectAttempts || 0),
      );
      this.reconnectAttempts += 1;
      this.setStatus('已断开', 'disconnected');
      this.setMessage(`${reasonText}，${Math.round(delay)} ms 后重连`);
      this.clearReconnectTimer();
      this.reconnectTimer = window.setTimeout(() => this.connect(), delay);
    }

    clearReconnectTimer() {
      if (this.reconnectTimer) {
        window.clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
    }

    cleanupSocket() {
      if (!this.ws) return;
      try {
        this.ws.onopen = null;
        this.ws.onmessage = null;
        this.ws.onerror = null;
        this.ws.onclose = null;
        if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
          this.ws.close();
        }
      } catch (error) {
        console.warn('[TogetheROS] socket cleanup failed:', error);
      } finally {
        this.ws = null;
      }
    }

    destroy() {
      if (this.destroyed) return;
      this.destroyed = true;
      this.clearReconnectTimer();
      this.cleanupSocket();
      if (this.fpsTimer) window.clearInterval(this.fpsTimer);
      if (this.lifecycleTimer) window.clearInterval(this.lifecycleTimer);
      window.removeEventListener('resize', this.boundResize);
      if (this.currentBlobUrl) {
        URL.revokeObjectURL(this.currentBlobUrl);
        this.currentBlobUrl = null;
      }
      this.pendingBlobUrl = null;
      delete registry[this.config.rootId];
    }
  }

  window.initTogetheROSNativePreview = function initTogetheROSNativePreview(config) {
    if (!config || !config.rootId) {
      throw new Error('rootId is required');
    }

    const options = {
      maxWaitMs: 15000,
      retryMs: 100,
      ...config,
    };
    const startTime = Date.now();

    return new Promise((resolve) => {
      let finished = false;
      let observer = null;
      let timer = null;

      const cleanup = () => {
        if (observer) {
          observer.disconnect();
          observer = null;
        }
        if (timer) {
          window.clearTimeout(timer);
          timer = null;
        }
      };

      const finish = (instance) => {
        if (finished) return;
        finished = true;
        cleanup();
        resolve(instance || null);
      };

      const scheduleRetry = () => {
        if (finished) return;
        timer = window.setTimeout(tryInit, options.retryMs);
      };

      const tryInit = () => {
        if (finished) return;

        const root = document.getElementById(options.rootId);
        if (!root) {
          if (Date.now() - startTime >= options.maxWaitMs) {
            console.warn(`[TogetheROS] preview root not found within wait window: ${options.rootId}`);
            finish(null);
            return;
          }
          scheduleRetry();
          return;
        }

        try {
          if (registry[options.rootId]) {
            registry[options.rootId].destroy();
          }
          registry[options.rootId] = new NativeTogetheROSPreview(options);
          finish(registry[options.rootId]);
        } catch (error) {
          if (error && String(error.message || error).includes('preview root not found')) {
            scheduleRetry();
            return;
          }
          console.error('[TogetheROS] preview init failed:', error);
          finish(null);
        }
      };

      if (window.MutationObserver && document.body) {
        observer = new MutationObserver(() => {
          const root = document.getElementById(options.rootId);
          if (root) {
            tryInit();
          }
        });
        observer.observe(document.body, { childList: true, subtree: true });
      }

      tryInit();
    });
  };
})();
