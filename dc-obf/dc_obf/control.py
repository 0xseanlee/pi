"""Local stop requests; no PID files or process-name matching."""
import asyncio
import contextlib
import fcntl
import os
from pathlib import Path
import socket
import stat
import time


def control_path():
    return Path.home() / '.config/dc/obf-control.sock'


def running():
    path = control_path().with_name('obf.run.lock')
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
    finally:
        os.close(fd)


@contextlib.asynccontextmanager
async def listener():
    # The caller holds obf.run.lock throughout listener lifetime and shutdown.
    path = control_path()
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        if not stat.S_ISSOCK(path.lstat().st_mode):
            raise RuntimeError('OBF 控制路徑不是 socket，已停止以免覆寫檔案。')
        path.unlink()  # A stale socket from a previous interrupted run.
    stop = asyncio.Event()

    async def request(reader, writer):
        try:
            if await asyncio.wait_for(reader.readline(), timeout=2) == b'close\n':
                stop.set()
                writer.write(b'stopping\n')
                await writer.drain()
        except (TimeoutError, OSError, ValueError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    server = await asyncio.start_unix_server(request, path=str(path), limit=128)
    path.chmod(0o600)
    try:
        yield stop
    finally:
        server.close()
        await server.wait_closed()
        path.unlink(missing_ok=True)


async def serve(client, token):
    async with listener() as stop:
        connection = asyncio.create_task(client.start(token))
        stopping = asyncio.create_task(stop.wait())
        try:
            done, _ = await asyncio.wait((connection, stopping), return_when=asyncio.FIRST_COMPLETED)
            if stopping in done:
                await client.stop()
                connection.cancel()  # Also interrupts a pending login/reconnect.
                with contextlib.suppress(asyncio.CancelledError):
                    await connection
            else:
                await connection  # Preserve real login/connection errors.
        finally:
            stopping.cancel()
            connection.cancel()
            await asyncio.gather(stopping, connection, return_exceptions=True)


def close_bot(timeout=15):
    path = control_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(path))
            connection.sendall(b'close\n')
            with connection.makefile('rb') as response:
                if response.readline(128) != b'stopping\n':
                    raise RuntimeError('OBF 控制端沒有確認停止，請回原視窗按 Ctrl+C。')
    except (FileNotFoundError, ConnectionRefusedError):
        if running():
            raise RuntimeError('沒有可連線的新版 Bot；可能正在更新或套模板。舊版 Bot 請在原視窗按 Ctrl+C。') from None
        print('OBF 已關閉，沒有正在執行的 Bot。')
        return 0
    except OSError:
        raise RuntimeError('無法連線 OBF 控制端，請回原視窗按 Ctrl+C。') from None
    deadline = time.monotonic() + timeout
    while running():
        if time.monotonic() >= deadline:
            raise RuntimeError('已送出停止要求，但尚未確認 Bot 完全退出；請查看原視窗。')
        time.sleep(0.05)
    print('OBF 已停止；已保存的檔案、設定與頻道紀錄保留。')
    return 0
