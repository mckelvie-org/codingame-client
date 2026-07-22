"""CLI interface for contribution manager."""

from __future__ import annotations

import difflib
import logging
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from types import TracebackType
from typing import Self

import aiohttp
import pytimeparse
from argparse_wizard import CliBase, CliCommand, OptCmdFunc, cli_command
from rich.console import Console

from codingame_client.browser_login.async_ import async_cg_browser_login

from ..client.async_.raw_client import CgAsyncRawClient
from ..client.common.raw_client import CgDownloadFileResult, compute_content_hash
from ..common.typedefs import override

logger = logging.getLogger(__name__)

class CgCli(CliBase):
    """Command-line interface for the contribution manager."""

    _client: CgAsyncRawClient | None = None
    _remember_me_token: str | None = None
    _cg_session_token: str | None = None
    _console: Console | None = None
    
    @property
    def console(self) -> Console:
        """Return the rich console instance."""
        if self._console is None:
            raise RuntimeError("Console not initialized")
        return self._console
    
    @console.setter
    def console(self, value: Console) -> None:
        """Set the rich console instance."""
        if self._console is not None:
            raise RuntimeError("Console already initialized")
        self._console = value
        
    def get_console(self) -> Console:
        """Return the rich console instance, initializing it if necessary."""
        if self._console is None:
            self._console = Console(highlight=False)
        return self._console
        
    def parse_timestamp(self, duration_str: str) -> datetime:
        """Parse a string into a Codingame compatible UTC timestamp. The
           return value is always in UTC timezone.
           
           Codingame uses timestamps in milliseconds since the epoch (1970-01-01T00:00:00Z).
           
           The following are accepted:
              - A simple bare number (e.g., "1680000000000") is interpreted as milliseconds since the epoch UTC. Note that
                this is different from the standard pytimeparse handling or Unix timestamp, which is in seconds since the epoch.
              - A pytimeparse-compatible duration string with explicit units (e.g., "1h30m")
                is interpreted as a duration from the epoch UTC.
                To provide a Unix-style "seconds since epoch" timestamp, you can add an "s" suffix (e.g., "1680000000s").
              - A relative duration from now (e.g., "-1h30m" or "+0") is interpreted as a pytimeparse-compatible duration
                subtracted from or added to the current time.
              - An ISO 8601 datetime string (e.g., "2023-03-15T12:34:56Z"). If the string does not contain timezone information,
                it is assumed to be in the local timezone.
        """
        try:
            if duration_str.startswith(("+", "-")):
                # Relative duration from now
                sign_ch = duration_str[0]
                remainder = duration_str[1:]
                try:
                    seconds = pytimeparse.parse(remainder, granularity="ms")
                    if seconds is None:
                        raise ValueError(f"Bad pytimeparsestring: {remainder!r}")
                    if sign_ch == "-":
                        seconds = -seconds
                    now = datetime.now(timezone.utc)
                    dt = now + timedelta(seconds=seconds)
                    return dt
                except ValueError as e:
                    raise ValueError(f"Invalid relative duration string: {duration_str!r}: {e}") from e
            try:
                ms = float(duration_str)
                seconds = ms / 1000.0
            except ValueError:
                seconds = pytimeparse.parse(duration_str, granularity="ms")
                if seconds is None:
                    # Try parsing as an ISO 8601 datetime string
                    try:
                        dt = datetime.fromisoformat(duration_str)
                        dt = dt.astimezone(timezone.utc)
                        return dt
                    except ValueError:
                        raise ValueError(f"Invalid timestamp or duration string: {duration_str!r}") from None
            result = datetime.fromtimestamp(seconds, tz=timezone.utc)
            return result
        except Exception as e:
            print(f"Error parsing timestamp string {duration_str!r}: {e}", file=sys.stderr)
            raise

    def _make_trace_config(self) -> aiohttp.TraceConfig:
        tc = aiohttp.TraceConfig()

        async def on_request_start(
                    session: aiohttp.ClientSession,
                    ctx: object,
                    params: aiohttp.TraceRequestStartParams
                ) -> None:
            logger.debug("HTTP --> %s %s", params.method, params.url)
            cookies = session.cookie_jar.filter_cookies(params.url)
            if cookies:
                logger.debug("HTTP cookies: %s", "; ".join(f"{k}={v.value}" for k, v in cookies.items()))

        async def on_request_headers_sent(
                    session: aiohttp.ClientSession,
                    ctx: object,
                    params: aiohttp.TraceRequestHeadersSentParams
                ) -> None:
            for k, v in params.headers.items():
                logger.debug("HTTP >  %s: %s", k, v)

        async def on_request_end(
                    session: aiohttp.ClientSession,
                    ctx: object,
                    params: aiohttp.TraceRequestEndParams
                ) -> None:
            logger.debug("HTTP <-- %s %s", params.response.status, params.response.url)
            for k, v in params.response.headers.items():
                logger.debug("HTTP <  %s: %s", k, v)

        async def on_request_exception(
                    session: aiohttp.ClientSession,
                    ctx: object,
                    params: aiohttp.TraceRequestExceptionParams
                ) -> None:
            logger.debug("HTTP ERR %s %s: %s", params.method, params.url, params.exception)

        tc.on_request_start.append(on_request_start)
        tc.on_request_headers_sent.append(on_request_headers_sent)
        tc.on_request_end.append(on_request_end)
        tc.on_request_exception.append(on_request_exception)
        return tc
    
    def get_trace_configs(self) -> list[aiohttp.TraceConfig]:
        """Return a list of aiohttp.TraceConfig instances for the client session."""
        trace_http: bool = self.args.trace_http
        return [self._make_trace_config()] if trace_http else []
    
    async def get_client(self) -> CgAsyncRawClient:
        """Return the CgAsyncRawClient instance, initializing it if necessary."""
        if self._client is None:
            self._client = CgAsyncRawClient(
                    trace_configs=self.get_trace_configs()
                )
        return self._client
    
    @override
    async def ctx_exit(
               self,
               exc_type: type[BaseException] | None,
               exc_value: BaseException | None,
               traceback: TracebackType | None
            ) -> None:
        """Async context manager exit. If we opened a CgAsyncClient, close it."""
        if self._client is not None:
            try:
                await self._client.__aexit__(exc_type, exc_value, traceback)
            except Exception as e:
                self.logger.error("Error closing CgAsyncClient: %s", e)
            self._client = None

    def wrap_and_indent(self, text: str, w: int = 80, indent: int = 4) -> str:
        return textwrap.indent(textwrap.fill(text, width=w), " " * indent)
    
    def show_diff(self, expected: str, actual: str) -> None:
        console = self.get_console()
        exp_lines = expected.splitlines(keepends=True)
        act_lines = actual.splitlines(keepends=True)
        diff = list(difflib.unified_diff(exp_lines, act_lines,
                                        fromfile="expected", tofile="actual",
                                        lineterm=""))
        for line in diff:
            eol = "" if line.endswith("\n") else "\n"
            if line.startswith("+"):
                console.print("    " + line, style="green", end=eol)
            elif line.startswith("-"):
                console.print("    " + line, style="red", end=eol)
            else:
                console.print("    " + line, style="dim", end=eol)
                
    @cli_command("Compute a content hash from stdin content.")
    async def cmd_content_hash(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            content = sys.stdin.buffer.read()
            hash_value = compute_content_hash(content)
            print(hash_value)
        return handler

    @cli_command("Log in via browser and save the credentials.")
    async def cmd_login(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:


            timeout: float = self.args.timeout
            clean: bool = self.args.clean
            profile_name: str | None = self.args.profile
            
            _ = await async_cg_browser_login(
                    profile_name=profile_name,
                    clean=clean,
                    timeout=timeout,
                    save=True,
                )
            
            self.eprint("Logged in successfully. Credentials saved.")

        p = cmd.get_parser()
        p.add_argument(
                "--timeout", "-t", type=float, default=300.0, metavar="SECONDS",
                help="Maximum seconds to wait for login completion (default: 300).",
            )
        p.add_argument(
                "--clean", "-c", default=False, action="store_true",
                help="Force a clean browser profile.",
            )
        return handler

    @cli_command("Low-level API commands.")
    async def cmd_api(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Download a file by server object ID.")
    async def cmd_api__download(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            file_id: int = self.args.file_id
            timestamp: datetime | None = self.args.timestamp
            format: str | None = self.args.format
            self.eprint(f"Downloading file with ID: {file_id}")
            client = await self.get_client()
            file_info: CgDownloadFileResult = await client.download_file(
                    file_id,
                    format=format,
                    timestamp=timestamp
                ) # type: ignore
            self.eprint(
                    f"Fetched file: {file_info.filename!r}; content-type={file_info.content_type!r}, "
                    f"size={len(file_info.content)} bytes, hash={file_info.hash!r}"
                )
            if sys.stderr.isatty():
                self.eprint("Omitting file content because stdout is a terminal. Redirect stdout to a file or pipe to see the content.")
                return
            self.get_binary_stdout().write(file_info.content)
        p = cmd.get_parser()
        p.add_argument("file_id", type=int, metavar="ID",
                       help="Server file ID number.")
        p.add_argument("--format", type=str, default=None,
                       help="Optional format string to append to the URL as a query parameter; e.g., 'puzzle_tile'.")
        p.add_argument("--timestamp", type=self.parse_timestamp, default=None, metavar="TIMESTAMP",
                       help="Optional timestamp. Can be milliseconds since epoch (e.g., '1680000000000'),"
                            " a duration string (e.g., '1h30m'), a relative duration from now (e.g., '-1h30m'),"
                            " or an ISO 8601 datetime string.")
        return handler

    @cli_command("Upload a file from stdin.")
    async def cmd_api__upload(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            filename: str = self.args.filename
            content_type: str = self.args.content_type
            prev_id: int | None = self.args.prev_id
            prev_content_hash: str | None = self.args.prev_content_hash
            client = await self.get_client()
            content = self.get_binary_stdin().read()
            content_hash = compute_content_hash(content)
            self.eprint(
                    f"Uploading file with filename={filename!r}, content-type={content_type!r}, "
                    f"size={len(content)} bytes, hash={content_hash!r}")
            file_changed = prev_id is None or prev_content_hash is None or prev_content_hash != content_hash
            if not file_changed:
                self.eprint("Content hash matches previous content hash; skipping upload.")
                print(str(prev_id))
                return
            self.eprint("Content hash differs from previous content hash; proceeding with upload.")
            id = await client.upload_file(
                    content,
                    filename=filename,
                    content_type=content_type,
                )
            print(str(id))
        p = cmd.get_parser()
        p.add_argument("--filename", type=str, default="data.bin",
                       help="Optional filename provided to the server for the uploaded file; e.g., 'cover.png'.")
        p.add_argument("--content-type", type=str, default="application/octet-stream",
                       help="Optional content type for the uploaded file; e.g., 'application/octet-stream'.")
        p.add_argument("--prev-id", type=int, default=None,
                       help="Optional previous file ID for the uploaded file; e.g., 12345.")
        p.add_argument("--prev-content-hash", type=str, default=None,
                       help="Optional previous content hash for the uploaded file.")
        return handler

    @cli_command("Codingame client command-line interface.")
    async def main(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        """Main command handler for the CLI."""

        p = cmd.get_parser()
        p.add_argument(
                "--trace-http", dest="trace_http", default=False, action="store_true",
                help="Log detailed HTTP info (method, URL, headers, cookies) at DEBUG level.",
            )
        p.add_argument(
                "--profile", "-p", default=None,
                help="Profile name to store credentials and browser session state under. Defaults to the client's default profile.",
            )

        # No handler for the main command; bare command is not allowed
        return None
    
    @override
    async def preinit(self) -> None:
        """Perform any pre-initialization setup before the parser is built."""
        self.get_console()

async def async_main(args: list[str] | None = None, prog_name: str | None = None) -> int:
    """Main entry point for the CLI."""
    return await CgCli(args, prog_name).async_run()

def main(args: list[str] | None = None, prog_name: str | None = None) -> int:
    """Main entry point for the CLI."""
    return CgCli(args, prog_name).run()
