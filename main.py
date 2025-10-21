import asyncio
import os
import re
import signal
import sys
import shutil
from dataclasses import dataclass
from typing import Optional

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# Allowed TG ID's. | Replace with int
users = ["1111111111", "2222222222"]

ALLOWED_IDS = [int(x) for x in users]
ALLOWED_FILTER = filters.User(user_id=ALLOWED_IDS)

# env variables
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "PUT_YOUR_TOKEN_HERE")
UVICORN_HOST = os.getenv("UVICORN_HOST", "0.0.0.0")
UVICORN_PORT = int(os.getenv("UVICORN_PORT", "8000"))
APP_MODULE = os.getenv("APP_MODULE", "server_local:app") #app
SUBDOMAIN = os.getenv("LT_SUBDOMAIN", "my-qr-miniapp")


NPX_CANDIDATES = ["npx.cmd", "npx"] if os.name == "nt" else ["npx"]
CURL_CANDIDATES = ["curl.exe", "curl"] if os.name == "nt" else ["curl"]

URL_RE = re.compile(r"(https?://[^\s]+)")

@dataclass
class Session:
    uvicorn_proc: Optional[asyncio.subprocess.Process] = None
    lt_proc: Optional[asyncio.subprocess.Process] = None
    lt_url: Optional[str] = None
    ip: Optional[str] = None

SESSION = Session()

# Utils

def _creationflags() -> int:
    if os.name == "nt":
        return 0x00000200
    return 0

def _find_binary(candidates):
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    return None

def _ensure_uvicorn_installed_or_hint():

    try:
        proc = asyncio.run(asyncio.create_subprocess_exec(
            sys.executable, "-m", "uvicorn", "--version",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        ))
    except RuntimeError:

        import subprocess
        try:
            subprocess.run([sys.executable, "-m", "uvicorn", "--version"], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as e:
            raise RuntimeError("uvicorn не установлен. use: pip install uvicorn fastapi") from e
        return
    except Exception as e:
        raise RuntimeError("не удалось проверить uvicorn. use: pip install uvicorn fastapi") from e

async def _start_uvicorn_if_needed() -> None:
    if SESSION.uvicorn_proc and SESSION.uvicorn_proc.returncode is None:
        return
    try:
        p = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "uvicorn", "--version",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await p.communicate()
        if p.returncode not in (0, None):
            raise RuntimeError
    except Exception:
        raise RuntimeError("uvicorn не найден. use: pip install uvicorn fastapi")

    cmd = [sys.executable, "-m", "uvicorn", APP_MODULE, "--host", UVICORN_HOST, "--port", str(UVICORN_PORT)]
    SESSION.uvicorn_proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        creationflags=_creationflags(),
    )
    await asyncio.sleep(0.6)

async def _start_localtunnel_and_get_url(timeout: float = 25.0) -> str:
    if SESSION.lt_proc and SESSION.lt_proc.returncode is None and SESSION.lt_url:
        return SESSION.lt_url

    npx_bin = _find_binary(NPX_CANDIDATES)
    if not npx_bin:
        raise RuntimeError(
            "Не найден 'npx'. Установите Node.js и добавьте в PATH:\n"
        )

    lt_cmd = [npx_bin, "localtunnel", "--port", str(UVICORN_PORT), "--subdomain", SUBDOMAIN]
    SESSION.lt_proc = await asyncio.create_subprocess_exec(
        *lt_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        creationflags=_creationflags(),
    )

    assert SESSION.lt_proc.stdout is not None
    url = None
    try:
        async def read_lines():
            nonlocal url
            while True:
                line = await SESSION.lt_proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="ignore").strip()
                m = URL_RE.search(text)
                if m:
                    url = m.group(1)
                    break
        await asyncio.wait_for(read_lines(), timeout=timeout)
    except asyncio.TimeoutError:
        url = url or f"https://{SUBDOMAIN}.loca.lt"

    SESSION.lt_url = url
    return url

async def _get_ipv4_via_curl_or_http() -> str:
    async def _run(cmd):
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, _ = await proc.communicate()
        return out.decode(errors="ignore").strip()


    curl_bin = _find_binary(CURL_CANDIDATES)
    if curl_bin:
        try:
            ip = await _run([curl_bin, "-4", "ifconfig.me"])
            if ip:
                return ip
        except Exception:
            pass


    try:
        import urllib.request, socket
        req = urllib.request.Request("http://ifconfig.me/ip", headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            txt = resp.read().decode().strip()
            if txt:
                socket.inet_aton(txt)
                return txt
    except Exception:
        pass

    return "не удалось определить"

async def _ensure_services() -> tuple[str, str]:
    await _start_uvicorn_if_needed()
    url = await _start_localtunnel_and_get_url()
    if not SESSION.ip:
        SESSION.ip = await _get_ipv4_via_curl_or_http()
    return url, SESSION.ip

async def _stop_services():
    if SESSION.lt_proc and SESSION.lt_proc.returncode is None:
        try:
            if os.name == "nt":
                SESSION.lt_proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                SESSION.lt_proc.terminate()
            await asyncio.sleep(0.3)
        except Exception:
            pass
        try:
            SESSION.lt_proc.kill()
        except Exception:
            pass
    SESSION.lt_proc = None
    SESSION.lt_url = None

    if SESSION.uvicorn_proc and SESSION.uvicorn_proc.returncode is None:
        try:
            if os.name != "nt":
                SESSION.uvicorn_proc.terminate()
            else:
                SESSION.uvicorn_proc.kill()
            await asyncio.sleep(0.3)
        except Exception:
            pass
    SESSION.uvicorn_proc = None



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.effective_message.reply_text("Запуск сканера…")
    try:
        url, ip = await _ensure_services()
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(text="Сканировать", web_app=WebAppInfo(url=url))]]
        )
        await update.effective_message.reply_text(
            f"Пароль: {ip}\nНажмите кнопку ниже, чтобы открыть сканер.", reply_markup=kb
        )
    except RuntimeError as e:
        await update.effective_message.reply_text(f"Ошибка запуска: {e}")
    except FileNotFoundError:
        await update.effective_message.reply_text(
            "Ошибка запуска: не найден исполняемый файл (WinError 2).\n"
            "Проверьте установку Node.js (npx) и curl, а также PATH."
        )
    except Exception as e:
        await update.effective_message.reply_text(f"Неожиданная ошибка: {e}")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _stop_services()
    await update.effective_message.reply_text("Сервисы остановлены.")

async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _stop_services()
    await asyncio.sleep(0.5)
    await start(update, context)


async def deny_access(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_message:
        await update.effective_message.reply_text("Нет доступа ❌")

def main():
    if not BOT_TOKEN or BOT_TOKEN == "PUT_YOUR_TOKEN_HERE":
        print("Установите TELEGRAM_TOKEN в окружение.")
        sys.exit(1)

    app = Application.builder().token(BOT_TOKEN).build()


    app.add_handler(CommandHandler("start", start, filters=ALLOWED_FILTER))
    app.add_handler(CommandHandler("stop", stop_cmd, filters=ALLOWED_FILTER))
    app.add_handler(CommandHandler("restart", restart_cmd, filters=ALLOWED_FILTER))


    app.add_handler(MessageHandler(~ALLOWED_FILTER, deny_access))

    print("Bot is running…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
