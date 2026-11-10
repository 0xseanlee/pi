import asyncio
import os
from pathlib import Path
import signal
import sys


class EngineError(Exception):
    pass


async def transform(argv, source, output, timeout=120):
    if not isinstance(argv, list) or not argv or not all(isinstance(s, str) for s in argv):
        raise EngineError('VM 混淆引擎尚未接上，目前不會產生假混淆結果。')
    if not any('{input}' in s for s in argv) or not any('{output}' in s for s in argv):
        raise EngineError('引擎命令缺少 {input} 或 {output} 參數。')
    command = [s.replace('{python}', sys.executable).replace('{input}', str(source)).replace('{output}', str(output)) for s in argv]
    process = await asyncio.create_subprocess_exec(
        *command, cwd=Path(source).parent, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        try:
            await asyncio.wait_for(process.wait(), timeout)
        except asyncio.TimeoutError:
            raise EngineError('混淆處理逾時，這份工作已停止。') from None
        if process.returncode:
            raise EngineError('混淆引擎回報失敗，沒有回傳產物。')
        output = Path(output)
        if output.is_symlink() or not output.is_file() or output.stat().st_size == 0:
            raise EngineError('引擎沒有產生有效輸出檔。')
        if output.stat().st_size > 8 * 1024 * 1024:
            raise EngineError('輸出檔超過 8 MiB，沒有回傳。')
        if output.stat().st_size == Path(source).stat().st_size and output.read_bytes() == Path(source).read_bytes():
            raise EngineError('輸出與原檔完全相同，沒有當成混淆成功回傳。')
        return output
    finally:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
