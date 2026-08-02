"""`run_argv_streaming`: shared asyncio subprocess engine any `CgLanguage` plugin can call after
   building its own argv, for its `run_streaming()` implementation--not a `CgLanguage` itself, not
   discovered by `codingame_tools.language.registry` (it doesn't live under `languages/`), and not
   re-exported from `codingame_tools.language`'s public surface.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator

from .base import CgRunEvent, CgRunFinished, CgRunOutputChunk, CgRunResult, CgRunStream

__all__ = ["run_argv_streaming"]

_CHUNK_READ_SIZE = 4096


async def run_argv_streaming(
            argv: list[str],
            input_text: str,
            *,
            timeout: float,
            env: dict[str, str] | None = None,
        ) -> AsyncGenerator[CgRunEvent, None]:
    """Run `argv` as a subprocess, write `input_text` to stdin then close it, and yield
       `CgRunOutputChunk`s tagged by stream as stdout/stderr become available, ending with a
       `CgRunFinished` carrying the aggregated `CgRunResult`.

       stdout and stderr are read from two independent OS pipes, each with its own kernel-level
       buffering--chunks are yielded in the order this process happens to receive them, a
       reasonable real-time approximation but not a correctness guarantee about the target
       process's true write order between the two streams (see `CgRunOutputChunk`).

       On timeout, the subprocess is killed and reaped before this generator finishes; whatever
       output was captured before the kill is still included in the final `CgRunResult`.
    """
    process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env,
        )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    queue: asyncio.Queue[CgRunOutputChunk] = asyncio.Queue()
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    async def pump(reader: asyncio.StreamReader, stream: CgRunStream, sink: list[str]) -> None:
        while True:
            data = await reader.read(_CHUNK_READ_SIZE)
            if not data:
                return
            text = data.decode("utf-8", errors="replace")
            sink.append(text)
            await queue.put(CgRunOutputChunk(stream=stream, text=text))

    async def drive() -> int:
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        process.stdin.write(input_text.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()
        await asyncio.gather(
                pump(process.stdout, "stdout", stdout_parts),
                pump(process.stderr, "stderr", stderr_parts),
            )
        return await process.wait()

    driver: asyncio.Task[int] = asyncio.ensure_future(drive())
    deadline = asyncio.get_event_loop().time() + timeout
    timed_out = False
    try:
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                timed_out = True
                break
            get_next: asyncio.Task[CgRunOutputChunk] = asyncio.ensure_future(queue.get())
            done, _pending = await asyncio.wait(
                    {get_next, driver}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
            if get_next in done:
                yield get_next.result()
                continue
            get_next.cancel()
            if driver in done:
                break
            timed_out = True
            break
    finally:
        if timed_out:
            driver.cancel()
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            with contextlib.suppress(asyncio.CancelledError):
                await driver
            await process.wait()

    while not queue.empty():          # anything queued between the driver's last put and return
        yield queue.get_nowait()

    returncode = -1 if timed_out else driver.result()
    yield CgRunFinished(CgRunResult(
            output="".join(stdout_parts), stderr="".join(stderr_parts),
            returncode=returncode, timed_out=timed_out,
        ))
