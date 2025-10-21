import json
import os
import asyncio
import aiofiles
from pathlib import Path
from typing import List, Set, Union, Dict, Optional
from datetime import datetime
import logging
from functools import lru_cache

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

APP_DIR = Path(__file__).parent.resolve()
PAYMENTS_PATH = APP_DIR / "payments.json"
BACKUP_PATH = APP_DIR / "payments_backup.json"


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Telegram MiniApp: QR Checker")


_payments_cache: Optional[Dict] = None
_cache_timestamp: Optional[float] = None
CACHE_TTL = 5.0


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




def _is_cache_valid() -> bool:

    if _payments_cache is None or _cache_timestamp is None:
        return False
    return (datetime.now().timestamp() - _cache_timestamp) < CACHE_TTL


async def _read_payments_file_async() -> dict:

    global _payments_cache, _cache_timestamp


    if _is_cache_valid():
        return _payments_cache

    try:
        if not PAYMENTS_PATH.exists():
            _payments_cache = {}
            _cache_timestamp = datetime.now().timestamp()
            return {}

        async with aiofiles.open(PAYMENTS_PATH, "r", encoding="utf-8") as f:
            content = await f.read()
            data = json.loads(content)

        _payments_cache = data if isinstance(data, dict) else {}
        _cache_timestamp = datetime.now().timestamp()
        return _payments_cache

    except Exception as e:
        logger.error(f"Error reading payments file: {e}")
        return {}


def _read_payments_file() -> dict:

    global _payments_cache, _cache_timestamp

    if _is_cache_valid():
        return _payments_cache

    try:
        if not PAYMENTS_PATH.exists():
            _payments_cache = {}
            _cache_timestamp = datetime.now().timestamp()
            return {}

        with PAYMENTS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)

        _payments_cache = data if isinstance(data, dict) else {}
        _cache_timestamp = datetime.now().timestamp()
        return _payments_cache

    except Exception as e:
        logger.error(f"Error reading payments file: {e}")
        return {}


async def _backup_payments_file() -> bool:

    try:
        if PAYMENTS_PATH.exists():
            async with aiofiles.open(PAYMENTS_PATH, "r", encoding="utf-8") as src:
                content = await src.read()
            async with aiofiles.open(BACKUP_PATH, "w", encoding="utf-8") as dst:
                await dst.write(content)
        return True
    except Exception as e:
        logger.error(f"Error creating backup: {e}")
        return False


async def _update_payment_status_async(code: str, used: bool) -> bool:

    try:

        await _backup_payments_file()

        payments = await _read_payments_file_async()
        if code not in payments:
            return False

        payments_copy = payments.copy()
        payments_copy[code]["used"] = used


        temp_path = PAYMENTS_PATH.with_suffix('.tmp')
        async with aiofiles.open(temp_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(payments_copy, ensure_ascii=False, indent=4))


        temp_path.replace(PAYMENTS_PATH)


        global _payments_cache, _cache_timestamp
        _payments_cache = payments_copy
        _cache_timestamp = datetime.now().timestamp()

        logger.info(f"Payment status updated for code {code}: used={used}")
        return True

    except Exception as e:
        logger.error(f"Error updating payment status: {e}")

        try:
            if BACKUP_PATH.exists():
                async with aiofiles.open(BACKUP_PATH, "r", encoding="utf-8") as src:
                    content = await src.read()
                async with aiofiles.open(PAYMENTS_PATH, "w", encoding="utf-8") as dst:
                    await dst.write(content)
                logger.info("Restored from backup after error")
        except Exception as restore_error:
            logger.error(f"Failed to restore from backup: {restore_error}")
        return False


def _update_payment_status(code: str, used: bool) -> bool:

    try:

        if PAYMENTS_PATH.exists():
            with PAYMENTS_PATH.open("r", encoding="utf-8") as src:
                content = src.read()
            with BACKUP_PATH.open("w", encoding="utf-8") as dst:
                dst.write(content)

        payments = _read_payments_file()
        if code not in payments:
            return False

        payments[code]["used"] = used


        temp_path = PAYMENTS_PATH.with_suffix('.tmp')
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(payments, f, ensure_ascii=False, indent=4)

        temp_path.replace(PAYMENTS_PATH)

        global _payments_cache, _cache_timestamp
        _payments_cache = payments
        _cache_timestamp = datetime.now().timestamp()

        logger.info(f"Payment status updated for code {code}: used={used}")
        return True

    except Exception as e:
        logger.error(f"Error updating payment status: {e}")
        return False


class ValidateRequest(BaseModel):
    text: str


class UpdateRequest(BaseModel):
    text: str



_request_counts = {}
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX_REQUESTS = 100


def _check_rate_limit(client_ip: str) -> bool:

    now = datetime.now().timestamp()

    if client_ip not in _request_counts:
        _request_counts[client_ip] = []


    _request_counts[client_ip] = [
        timestamp for timestamp in _request_counts[client_ip]
        if now - timestamp < RATE_LIMIT_WINDOW
    ]


    if len(_request_counts[client_ip]) >= RATE_LIMIT_MAX_REQUESTS:
        return False


    _request_counts[client_ip].append(now)
    return True


@app.get("/api/ping")
async def ping():

    return {"ok": True, "timestamp": datetime.now().isoformat()}


@app.post("/api/validate")
async def validate(payload: ValidateRequest, request: Request):

    try:

        client_ip = request.client.host
        if not _check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        text = payload.text.strip()
        if not text:
            return {"ok": False, "error": "Empty text", "status": "invalid"}


        payments = await _read_payments_file_async()

        if text not in payments:
            logger.info(f"Code not found: {text[:10]}...")
            return {"ok": True, "status": "not_found", "exists": False, "payment_data": None}

        payment_data = payments[text]

        if payment_data.get("used", False):
            logger.info(f"Code already used: {text[:10]}...")
            return {"ok": True, "status": "already_used", "exists": True, "payment_data": payment_data}
        else:
            logger.info(f"Valid code found: {text[:10]}...")
            return {"ok": True, "status": "valid", "exists": True, "payment_data": payment_data}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in validate endpoint: {e}")
        return {"ok": False, "error": "Internal server error", "status": "error"}


@app.post("/api/update")
async def update_code_status(payload: UpdateRequest, request: Request):

    try:

        client_ip = request.client.host
        if not _check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        text = payload.text.strip()
        if not text:
            return {"ok": False, "error": "Empty text"}

        success = await _update_payment_status_async(text, True)

        if success:
            logger.info(f"Code status updated successfully: {text[:10]}...")
        else:
            logger.warning(f"Failed to update code status: {text[:10]}...")

        return {"ok": success}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update endpoint: {e}")
        return {"ok": False, "error": "Internal server error"}



@app.get("/", response_class=HTMLResponse)
def index(request: Request):

    html = """
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>QR Checker</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <script src="https://unpkg.com/@zxing/library@latest"></script>
  <style>
    :root {
      --bg: #0f1115;
      --card: #171a21;
      --text: #e7e9ee;
      --muted: #9aa4b2;
      --ok: #29c46d;
      --bad: #ff5468;
      --accent: #4e8cff;
    }
    html, body {
      height: 100%;
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Inter, Arial, "Apple Color Emoji", "Segoe UI Emoji";
    }
    .wrap {
      max-width: 720px;
      margin: 0 auto;
      padding: 16px 16px calc(16px + env(safe-area-inset-bottom));
    }
    .card {
      background: var(--card);
      border-radius: 18px;
      box-shadow: 0 10px 30px rgba(0,0,0,.35);
      padding: 16px;
    }
    h1 {
      font-size: 20px;
      margin: 0 0 12px;
      letter-spacing: .2px;
    }
    .video-wrap {
      position: relative;
      border-radius: 14px;
      overflow: hidden;
      background: #000;
      aspect-ratio: 3/4;
      margin-bottom: 12px;
    }
    video {
      width: 100%;
      height: 100%;
      object-fit: cover;
      transform: scaleX(1); /* УБРАТЬ ЗЕРКАЛКУ */
    }
    .overlay {
      position: absolute;
      inset: 0;
      pointer-events: none;
      box-shadow:
        inset 0 0 0 2px rgba(255,255,255,.08),
        inset 0 0 0 160px rgba(0,0,0,.08);
    }
    .status {
      border-radius: 14px;
      padding: 12px 14px;
      font-size: 15px;
      background: rgba(255,255,255,.04);
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 12px;
    }
    .status .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--muted);
      flex: 0 0 auto;
    }
    .status.ok .dot { background: var(--ok); }
    .status.bad .dot { background: var(--bad); }
    .row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    button {
      appearance: none;
      border: none;
      border-radius: 12px;
      padding: 12px 14px;
      font-size: 15px;
      font-weight: 600;
      color: #fff;
      background: var(--accent);
      cursor: pointer;
    }
    button.secondary {
      background: rgba(255,255,255,.08);
      color: var(--text);
      font-weight: 500;
    }
    .hint {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
      margin-top: 8px;
    }
    .result-text {
      font-weight: 700;
    }
    .small {
      font-size: 12px;
      color: var(--muted);
    }
    .code-preview {
      white-space: pre-wrap;
      word-break: break-word;
      background: rgba(255,255,255,.04);
      border-radius: 10px;
      padding: 8px 10px;
      margin-top: 6px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 13px;
    }
    .overlay-result {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      border-radius: 14px;
      pointer-events: none;
      transition: all 0.3s ease;
    }
    .overlay-result.red {
      background: rgba(255, 84, 104, 0.6);
    }
    .overlay-result.yellow {
      background: rgba(255, 193, 7, 0.6);
    }
    .overlay-result.green {
      background: rgba(41, 196, 109, 0.6);
    }
    .overlay-result.hidden {
      opacity: 0;
      pointer-events: none;
    }
    .overlay-text {
      color: white;
      font-size: 18px;
      font-weight: 600;
      text-align: center;
      margin-bottom: 16px;
      text-shadow: 0 2px 4px rgba(0,0,0,0.5);
    }
    .overlay-button {
      appearance: none;
      border: none;
      border-radius: 16px;
      padding: 16px 32px;
      font-size: 18px;
      font-weight: 600;
      color: white;
      background: rgba(255,255,255,0.2);
      cursor: pointer;
      pointer-events: auto;
      backdrop-filter: blur(10px);
      border: 1px solid rgba(255,255,255,0.3);
      margin-top: 8px;
    }
    .overlay-button:hover {
      background: rgba(255,255,255,0.3);
    }
    .purchase-info {
      background: var(--card);
      border-radius: 16px;
      padding: 20px;
      margin-top: 16px;
      box-shadow: 0 4px 20px rgba(0,0,0,.2);
      border: 1px solid rgba(255,255,255,.08);
    }
    .purchase-info.hidden {
      display: none;
    }
    .purchase-title {
      font-size: 18px;
      font-weight: 600;
      margin-bottom: 16px;
      color: var(--text);
    }
    .purchase-detail {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 0;
      border-bottom: 1px solid rgba(255,255,255,.05);
    }
    .purchase-detail:last-child {
      border-bottom: none;
    }
    .purchase-label {
      color: var(--muted);
      font-size: 14px;
    }
    .purchase-value {
      color: var(--text);
      font-weight: 500;
      font-size: 14px;
    }
    .camera-permission {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(0, 0, 0, 0.8);
      border-radius: 14px;
      z-index: 10;
    }
    .camera-permission.hidden {
      display: none;
    }
    .permission-content {
      text-align: center;
      padding: 24px;
      max-width: 280px;
    }
    .permission-icon {
      font-size: 48px;
      margin-bottom: 16px;
    }
    .permission-title {
      font-size: 20px;
      font-weight: 600;
      margin-bottom: 12px;
      color: var(--text);
    }
    .permission-text {
      font-size: 14px;
      color: var(--muted);
      line-height: 1.4;
      margin-bottom: 20px;
    }
    .permission-button {
      appearance: none;
      border: none;
      border-radius: 12px;
      padding: 14px 24px;
      font-size: 16px;
      font-weight: 600;
      color: white;
      background: var(--accent);
      cursor: pointer;
      margin-bottom: 12px;
      transition: all 0.2s ease;
    }
    .permission-button:hover {
      background: #3d7bff;
      transform: translateY(-1px);
    }
    .permission-button:active {
      transform: translateY(0);
    }
    .permission-hint {
      font-size: 12px;
      color: var(--muted);
      line-height: 1.3;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">


      <div class="video-wrap">
        <video id="video" playsinline muted></video>
        <div class="overlay"></div>
        <div id="overlayResult" class="overlay-result hidden">
          <div id="overlayText" class="overlay-text"></div>
          <button id="overlayOk" class="overlay-button">ОК</button>
        </div>
        <div id="cameraPermission" class="camera-permission hidden">
          <div class="permission-content">
            <div class="permission-icon">📷</div>
            <div class="permission-title">Доступ к камере</div>
            <div class="permission-text">Для сканирования QR кодов необходимо разрешить доступ к камере</div>
            <button id="requestCamera" class="permission-button">Разрешить камеру</button>
            <div class="permission-hint">Нажмите "Разрешить" в появившемся окне браузера</div>
          </div>
        </div>
      </div>

      <div id="purchaseInfo" class="purchase-info hidden">
        <div class="purchase-title">Информация о покупке</div>
        <div id="purchaseDetails"></div>
      </div>
    </div>
  </div>

  <script>
    if (window.Telegram && Telegram.WebApp) {
      Telegram.WebApp.ready();
      Telegram.WebApp.expand();
    }

    // кэшинг DOMа 
    const videoEl = document.getElementById("video");
    const overlayResult = document.getElementById("overlayResult");
    const overlayText = document.getElementById("overlayText");
    const overlayOk = document.getElementById("overlayOk");
    const purchaseInfo = document.getElementById("purchaseInfo");
    const purchaseDetails = document.getElementById("purchaseDetails");
    const cameraPermission = document.getElementById("cameraPermission");
    const requestCameraBtn = document.getElementById("requestCamera");

    let codeReader = null;
    let active = false;
    let paused = false;
    let lastPayload = "";
    let lastShown = 0;
    let requestQueue = new Set(); 
    let abortController = null; 
    let performanceMetrics = {
      scanCount: 0,
      successCount: 0,
      errorCount: 0,
      avgResponseTime: 0
    };

    async function validateText(text) {
      const startTime = performance.now();

      if (requestQueue.has(text)) {
        console.log("Request already in progress for:", text.substring(0, 10));
        return null;
      }

      requestQueue.add(text);

      try {
        if (abortController) {
          abortController.abort();
        }
        abortController = new AbortController();

        const res = await fetch("/api/validate", {
          method: "POST",
          headers: { 
            "Content-Type": "application/json",
            "Cache-Control": "no-cache"
          },
          body: JSON.stringify({ text }),
          signal: abortController.signal
        });

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }

        const data = await res.json();

        const responseTime = performance.now() - startTime;
        performanceMetrics.scanCount++;
        performanceMetrics.avgResponseTime = 
          (performanceMetrics.avgResponseTime * (performanceMetrics.scanCount - 1) + responseTime) / performanceMetrics.scanCount;

        if (data.ok) {
          performanceMetrics.successCount++;
        } else {
          performanceMetrics.errorCount++;
        }

        return data;

      } catch (error) {
        if (error.name === 'AbortError') {
          console.log("Request aborted for:", text.substring(0, 10));
          return null;
        }

        console.error("Validation error:", error);
        performanceMetrics.errorCount++;

        if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
          console.log("Retrying request in 500ms...");
          await new Promise(resolve => setTimeout(resolve, 500));
          return await validateText(text);
        }

        throw error;
      } finally {
        requestQueue.delete(text);
      }
    }

    async function updateCodeStatus(text) {
      if (requestQueue.has(`update_${text}`)) {
        console.log("Update already in progress for:", text.substring(0, 10));
        return false;
      }

      requestQueue.add(`update_${text}`);

      try {
        const res = await fetch("/api/update", {
          method: "POST",
          headers: { 
            "Content-Type": "application/json",
            "Cache-Control": "no-cache"
          },
          body: JSON.stringify({ text })
        });

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }

        const data = await res.json();
        return data.ok;

      } catch (error) {
        console.error("Update error:", error);
        return false;
      } finally {
        requestQueue.delete(`update_${text}`);
      }
    }

    function showOverlay(color, message) {
      requestAnimationFrame(() => {
        overlayResult.className = `overlay-result ${color}`;
        overlayText.textContent = message;
        overlayResult.classList.remove("hidden");

        paused = true;
        if (codeReader) {
          try { 
            codeReader.reset(); 
          } catch (e) {
            console.warn("Error resetting code reader:", e);
          }
        }
        active = false;
      });
    }

    function hideOverlay() {
      requestAnimationFrame(() => {
        overlayResult.classList.add("hidden");
        hidePurchaseInfo();

        setTimeout(() => {
          paused = false;
          start();
        }, 100);
      });
    }

    function displayPurchaseInfo(paymentData) {
      if (!paymentData) {
        purchaseInfo.classList.add("hidden");
        return;
      }

      const fragment = document.createDocumentFragment();

      const details = [
        { label: "Телеграм:", value: paymentData.username || "Не указан" },
        { label: "Куплено билетов:", value: paymentData.tickets_quantity },
        { label: "Общая сумма:", value: `${paymentData.total}р.` },
        { label: "Дата покупки:", value: paymentData.date },
        { label: "ID покупки:", value: paymentData.purchase_id }
      ];

      purchaseDetails.innerHTML = "";

      details.forEach(detail => {
        const detailDiv = document.createElement("div");
        detailDiv.className = "purchase-detail";
        detailDiv.innerHTML = `
          <span class="purchase-label">${detail.label}</span>
          <span class="purchase-value">${detail.value}</span>
        `;
        fragment.appendChild(detailDiv);
      });

      purchaseDetails.appendChild(fragment);
      purchaseInfo.classList.remove("hidden");
    }

    function hidePurchaseInfo() {
      purchaseInfo.classList.add("hidden");
    }
    async function handleScan(text) {

      if (paused) return;

      const now = Date.now();

      if (text === lastPayload && (now - lastShown) < 1500) {
        console.log("Duplicate scan ignored:", text.substring(0, 10));
        return;
      }

      if (text.length < 3 || text.length > 1000) {
        console.log("Invalid text length:", text.length);
        return;
      }

      lastPayload = text;
      lastShown = now;

      try {
        console.log("Processing scan:", text.substring(0, 10) + "...");
        const data = await validateText(text);


        if (!data) {
          console.log("Request was cancelled");
          return;
        }

        if (data.status === "not_found") {
          showOverlay("red", "Билет не найден ❌");
          hidePurchaseInfo();
        } else if (data.status === "already_used") {
          showOverlay("yellow", "Билет уже был использован ❗");
          displayPurchaseInfo(data.payment_data);
        } else if (data.status === "valid") {
          showOverlay("green", "Билет принят ✅");
          displayPurchaseInfo(data.payment_data);


          updateCodeStatus(text).then(success => {
            if (success) {
              console.log("Code status updated successfully");
            } else {
              console.warn("Failed to update code status");
            }
          }).catch(error => {
            console.error("Error updating code status:", error);
          });
        } else if (data.status === "error") {

          showOverlay("red", "Ошибка сервера");
          hidePurchaseInfo();
        }
      } catch (e) {
        console.error("Ошибка проверки кода:", e);


        if (e.name === 'AbortError') {
          console.log("Request was aborted");
          return;
        } else if (e.message.includes('Rate limit')) {
          showOverlay("red", "Слишком много запросов, подождите");
        } else if (e.message.includes('Failed to fetch')) {
          showOverlay("red", "Нет соединения с сервером");
        } else {
          showOverlay("red", "Ошибка проверки кода");
        }
        hidePurchaseInfo();
      }
    }


    function showCameraPermission() {
      cameraPermission.classList.remove("hidden");
    }


    function hideCameraPermission() {
      cameraPermission.classList.add("hidden");
    }


    async function requestCameraPermission() {
      try {

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          showOverlay("red", "Ваш браузер не поддерживает камеру");
          return false;
        }


        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = devices.filter(device => device.kind === 'videoinput');

        if (videoDevices.length === 0) {
          showOverlay("red", "Камера не найдена на устройстве");
          return false;
        }

        console.log("Camera support confirmed, devices:", videoDevices.length);
        hideCameraPermission();
        return true;
      } catch (error) {
        console.error("Camera permission check failed:", error);
        showCameraPermission();
        return false;
      }
    }


    async function start() {
      if (active || paused) return;


      hideCameraPermission();

      try {
        codeReader = new ZXing.BrowserMultiFormatReader();


        await codeReader.decodeFromVideoDevice(undefined, "video", (result, err) => {
          if (result) {
            const text = result.getText();
            handleScan(text);
          } else if (err && !(err instanceof ZXing.NotFoundException)) {
            console.warn("Scanner error:", err);
          }
        });

        active = true;
        console.log("Scanner started successfully");

      } catch (e) {
        console.error("Scanner start error:", e);


        if (e.name === 'NotAllowedError') {
          showCameraPermission();
        } else if (e.name === 'NotFoundError') {
          showOverlay("red", "Камера не найдена на устройстве");
        } else if (e.name === 'NotReadableError') {
          showOverlay("red", "Камера занята другим приложением");
        } else {
          showOverlay("red", "Не удалось открыть камеру");
        }
      }
    }


    function stop() {
      if (codeReader) {
        try { 
          codeReader.reset(); 
          console.log("Scanner stopped");
        } catch (e) {
          console.warn("Error stopping scanner:", e);
        }
      }
      active = false;


      requestQueue.clear();


      if (abortController) {
        abortController.abort();
        abortController = null;
      }
    }


    overlayOk.addEventListener("click", hideOverlay);


    requestCameraBtn.addEventListener("click", async () => {
      hideCameraPermission();
      await start();
    });


    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        console.log("Page hidden, pausing scanner");
        stop();
      } else {
        console.log("Page visible, resuming scanner");
        start();
      }
    });


    let resizeTimeout;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(() => {
        if (active) {
          console.log("Window resized, restarting scanner");
          stop();
          setTimeout(start, 100);
        }
      }, 250);
    });


    window.addEventListener("error", (event) => {
      console.error("Global error:", event.error);
    });

    window.addEventListener("unhandledrejection", (event) => {
      console.error("Unhandled promise rejection:", event.reason);
    });


    setInterval(() => {
      if (performanceMetrics.scanCount > 1000) {
        performanceMetrics.scanCount = Math.floor(performanceMetrics.scanCount * 0.9);
        performanceMetrics.successCount = Math.floor(performanceMetrics.successCount * 0.9);
        performanceMetrics.errorCount = Math.floor(performanceMetrics.errorCount * 0.9);
      }
    }, 60000); 


    window.getPerformanceStats = () => {
      return {
        ...performanceMetrics,
        successRate: performanceMetrics.scanCount > 0 ? 
          (performanceMetrics.successCount / performanceMetrics.scanCount * 100).toFixed(2) + '%' : '0%',
        avgResponseTime: Math.round(performanceMetrics.avgResponseTime) + 'ms'
      };
    };


    function checkCameraSupport() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showOverlay("red", "Ваш браузер не поддерживает камеру");
        return false;
      }
      return true;
    }

    setTimeout(async () => {
      console.log("Starting QR scanner...");

      if (checkCameraSupport()) {
        await start();
      }
    }, 500);
  </script>
</body>
</html>
    """
    return HTMLResponse(html)
