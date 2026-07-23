"""CLI interface for contribution manager."""

from __future__ import annotations

import difflib
import json
import logging
import sys
import textwrap
from datetime import datetime
from types import TracebackType
from typing import cast

import aiohttp
from argparse_wizard import CliBase, CliCommand, OptCmdFunc, cli_command
from json_data_types import JsonData, JsonList
from rich.console import Console

from ..client.async_.raw_client import CgAsyncRawClient
from ..client.common.raw_client import CgAuthenticationError, CgDownloadFileResult, compute_content_hash
from ..common.timestamps import parse_timestamp
from ..common.typedefs import Self, override
from ..credentials.browser_login import async_cg_browser_login, cg_browser_delete_session
from ..credentials.cg_credentials import CgCredentials, get_credentials_with_override, set_credentials

logger = logging.getLogger(__name__)

class CgCli(CliBase):
    """Command-line interface for the contribution manager."""

    _client: CgAsyncRawClient | None = None
    _client_authenticated: bool = False
    _client_validated: bool = False
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
    
    async def get_client(self, *, require_credentials: bool = False, validate: bool = False) -> CgAsyncRawClient:
        """Return the CgAsyncRawClient instance, initializing it if necessary.

           Credentials are always resolved and applied to the session on first use, best-effort
           (never raises if none are available)--this is "level 2" of four auth-strictness levels:

               1. No authentication at all: don't call this method for auth purposes; pass
                  `require_login=False` directly to `service_request`/etc.
               2. Authenticated API, best-effort (the default: require_credentials=False,
                  validate=False): credentials are applied if available, but nothing errors if
                  they aren't.
               3. Login required (require_credentials=True, validate=False): raises
                  CgAuthenticationError if no credentials are available. Does not check they're
                  still valid/unexpired.
               4. Validated login required (require_credentials=True, validate=True): raises if
                  no credentials are available, and separately raises if they don't pass a live
                  validation check against the server.
        """
        if self._client is None:
            profile: str | None = self.args.profile
            self._client = CgAsyncRawClient(
                profile_name=profile,
                trace_configs=self.get_trace_configs()
            )
        client = self._client
        if not self._client_authenticated:
            await client.authenticate()
            self._client_authenticated = True

        if require_credentials and client.credentials is None:
            raise CgAuthenticationError()

        if validate and not self._client_validated:
            await client.validate_credentials()
            self._client_validated = True

        return client
    
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
    
    async def login_helper(
                self,
                *,
                profile_name: str | None = None,
                manual: bool = False,
                timeout: float | None = None,
                clean: bool = False,
                force: bool = False,
                remember_me: str | None = None,
                cg_session: str | None = None,
                no_validate: bool = False,
            ) -> CgCredentials:
        """Performs the login process, either via browser or manual credentials, and returns the CgCredentials.
        
        Args:
            profile_name:       The name of the profile to use for storing credentials and browser session state.
                                Allows for multiple independent session profiles; e.g., if multiple CodinGame
                                accounts are used. If None, defaults to the default profile.
            manual:             If True, perform manual login instead of browser login.
                                Implied by presence of --remember-me or --cg-session.
            timeout:            For browser login, maximum time in seconds to wait for the user to log in.
                                If None, defaults to DEFAULT_TIMEOUT_SECS.
            clean:              For browser login, if True, erases browser session state and forces a fresh login flow
                                even if valid credentials are already cached in the browser. Defaults to False.
            force:              If True, force a login even if persistent credentials already exist. By default, login is skipped if
                                credentials already exist for the profile. Note that freshness of credentials is not checked in any case;
                                if they are expired, the client will fail to use them. Defaults to False.
            remember_me:        The rememberMe cookie value, for manual (non-browser) login. Must be provided together with --cg-session.
            cg_session:         The cgSession cookie value, for manual (non-browser) login. Must be provided together with --remember-me.
            no_validate:        If True, skip validation of the credentials after login. Defaults to False.
        
        """
        credentials: CgCredentials | None = None
        if not force:
            # Try to get existing credentials; if they exist, just return without doing a browser or manual login.
            # Note that we consider the presence of environment variable credentials to suffice for being logged in, even
            # though they are not saved to the profile store. This is because the environment variable credentials
            # are used implicitly by the client regardless of profile--they are not persisted to the profile store.
            # If no_validate is False, we will validate the credentials after login, which will fail if they are expired, in
            # which case we will fall through to the browser or manual login flow.
            credentials = get_credentials_with_override(profile_name=profile_name)
            if credentials is not None and (
                            credentials.remember_me_cookie is None or
                            credentials.cg_session_cookie is None
                    ):
                # Incomplete credentials; treat as not logged in.
                credentials = None
            if credentials is not None and not no_validate:
                # verify that the credentials are valid by attempting to authenticate with them in a temporary
                # client session.  If they are invalid, fall through to the login flow.
                async with CgAsyncRawClient(
                            profile_name=profile_name,
                            trace_configs=self.get_trace_configs()
                        ) as client:
                    try:
                        await client.authenticate(
                                profile_name=profile_name, credentials=credentials,
                                require_credentials=True, validate=True,
                            )
                    except CgAuthenticationError:
                        self.logger.warning(
                                "Existing credentials for profile %r are invalid or expired; forcing login.", profile_name)
                        credentials = None
            if credentials is not None:
                self.logger.debug("Credentials already exist for this profile; skipping login.")
                return credentials
            
        if manual or remember_me is not None or cg_session is not None:
            # manual login
            if remember_me is None or cg_session is None:
                raise ValueError("Both --remember-me and --cg-session must be provided for manual login.")
            credentials = CgCredentials(
                remember_me_cookie=remember_me,
                cg_session_cookie=cg_session,
            )
            set_credentials(credentials, profile_name=profile_name)
            self.logger.info("Manual login credentials set successfully.")
            return credentials
        else:
            # browser login
            self.eprint("Starting browser login. Please finish logging in in browser window that pops up...")
            credentials = await async_cg_browser_login(
                    profile_name=profile_name,
                    clean=clean,
                    timeout=timeout,
                    save=True,
                )
            self.eprint("Logged in successfully via browser. Credentials saved.")
            return credentials

    @cli_command("Log in and save the credentials. By default, opens a browser window for the user to log in interactively.")
    async def cmd_login(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            timeout: float = self.args.timeout
            manual: bool = self.args.manual
            clean: bool = self.args.clean
            profile_name: str | None = self.args.profile
            force: bool = self.args.force
            no_validate: bool = self.args.no_validate
            remember_me: str | None = self.args.remember_me
            cg_session: str | None = self.args.cg_session
            
            _ = await self.login_helper(
                    manual=manual,
                    timeout=timeout,
                    clean=clean,
                    profile_name=profile_name,
                    force=force,
                    remember_me=remember_me,
                    cg_session=cg_session,
                )
            
            if not no_validate:
                # level 4: validated login required--confirm the just-saved credentials actually work
                await self.get_client(require_credentials=True, validate=True)
            
            # For debugging, might log credentials here, but omitting here to keep creds out of logs.
            self.logger.debug(f"Login completed successfully for profile {profile_name or 'default'!r}")

        p = cmd.get_parser()
        p.add_argument(
                "--force", "-f", default=False, action="store_true",
                help="Force a login even if persistent credentials already exist. By default, login is skipped if "
                     "credentials already exist for the profile. Note that freshness of credentials is not checked in any case; "
                     "if they are expired, the client will fail to use them.",
            )
        p.add_argument(
                "--no-validate", "-q", default=False, action="store_true",
                help="Skip validation of the credentials after login.",
            )
        p.add_argument(
                "--manual", "-m", default=False, action="store_true",
                help="Perform manual login instead of browser login. Implied by presence of --remember-me or --cg-session.",
            )
        p.add_argument(
                "--remember-me", "-r", default=None,
                help="Remember me cookie value, for manual (non-browser) login.",
            )
        p.add_argument(
                "--cg-session", "-s", default=None,
                help="cgSession cookie value, for manual (non-browser) login.",
            )
        p.add_argument(
                "--clean", "-c", default=False, action="store_true",
                help="If a browser is created, force a clean browser profile and a fresh login flow. By default, the existing browser "
                     "session state is used if it exists, so that repeated logins for the same profile are generally automatic.",
            )
        p.add_argument(
                "--timeout", "-t", type=float, default=300.0, metavar="SECONDS",
                help="Maximum seconds to wait for browser login completion (default: 300).",
            )
        return handler
    
    async def logout_helper(
                self,
                *,
                profile_name: str | None = None,
                keep_browser_session: bool = False,
            ) -> None:
        """Performs the logout process, clearing the credentials and optionally the browser session state.
        
        Args:
            profile_name:       The name of the profile to use for storing credentials and browser session state.
                                Allows for multiple independent session profiles; e.g., if multiple CodinGame
                                accounts are used. If None, defaults to the default profile.
            keep_browser_session: If True, keep the existing browser session even when logging out of the profile.
                                  If the browser session is logged in, it will remain logged in and will auto-login
                                  without user authentication at the next profile login. By default, the browser
                                  session is deleted on logout, which will require a full login flow in the browser.
        """
        
        if not keep_browser_session:
            # Clear browser session state for this profile
            cg_browser_delete_session(profile_name=profile_name, delete_credentials=False)
            self.eprint("Browser session state cleared for this profile.")

        # Clear credentials from persistent store
        set_credentials(None, profile_name=profile_name)
        self.eprint("Credentials cleared from persistent store.")

    @cli_command("Log out of a given profile's session.")
    async def cmd_logout(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            profile_name: str | None = self.args.profile
            keep_browser_session: bool = self.args.keep_browser_session
            
            await self.logout_helper(
                    profile_name=profile_name,
                    keep_browser_session=keep_browser_session,
                )

            self.logger.debug(f"Logout completed successfully for profile {profile_name or 'default'!r}")

        p = cmd.get_parser()
        p.add_argument(
                "--keep-browser-session", "-k", default=False, action="store_true",
                help="Keep the existing browser session even when logging out of the profile. "
                     "If the browser session is logged in, it will remain logged in and will auto-login without user authentication "
                     "at the next profile login. By default, the browser session is deleted on logout, which will require "
                     "a full login flow in the browser.",
            )
        return handler

    @cli_command("Show the current logged-in user and other session info for the given profile.")
    async def cmd_whoami(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            use_json: bool = self.args.json
            # level 2: best-effort--report what's there rather than erroring if nothing is
            client = await self.get_client()
            profile = client.profile_name
            credentials = client.credentials
            has_credentials = credentials is not None
            codingamer_id: int | None = client.codingamer_id
            remember_me: str | None = None
            cg_session: str | None = None
            credentials_valid: bool | None = None
            if credentials is not None:
                remember_me = credentials.remember_me_cookie
                cg_session = credentials.cg_session_cookie
                try:
                    await client.validate_credentials()
                    credentials_valid = True
                except CgAuthenticationError:
                    credentials_valid = False
            if use_json:
                output = {
                    "profile": profile,
                    "hasCredentials": has_credentials,
                    "codingamerId": codingamer_id,
                    "credentialsValid": credentials_valid,
                    "rememberMe": remember_me,
                    "cgSession": cg_session,
                }
                print(json.dumps(output, indent=4, sort_keys=True))
            else:
                print(f"Profile: {profile}")
                print(f"Has credentials: {has_credentials}")
                print(f"Codingamer ID: {codingamer_id}")
                if has_credentials:
                    print(f"Credentials valid: {credentials_valid}")
                    print(f"rememberMe cookie: {remember_me}")
                    print(f"cgSession cookie: {cg_session}")


        return handler

    @cli_command("Raw (unstructured JSON) API commands.")
    async def cmd_raw_api(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Invoke a raw API request on a service endpoint. stdin must be a json-encoded list of args.")
    async def cmd_raw_api__service_request(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            service_name: str = self.args.service_name
            func_name: str = self.args.func_name
            data: str | None = self.args.req_args
            # level 2: attach credentials if available, but don't require them--this is a raw/low-level
            # tool that should also work against genuinely public endpoints without being logged in.
            client = await self.get_client()
            if data is None:
               data = cast(str, sys.stdin.read())
            json_list: JsonList = cast(JsonList,json.loads(data))
            if not isinstance(json_list, list):
                raise ValueError("Input JSON must be a list of arguments.")
            response: JsonData = await client.service_request(
                    service_name=service_name,
                    func_name=func_name,
                    args=json_list,
                    require_login=False,
                )
            print(json.dumps(response, indent=2, sort_keys=True))

        p = cmd.get_parser()
        p.add_argument("service_name", type=str, metavar="SERVICE-NAME",
                       help="Service name; e.g., 'CodingamerService'.")
        p.add_argument("func_name", type=str, metavar="FUNC-NAME",
                       help="Endpoint name; e.g., 'getCodingamer'.")
        p.add_argument("--req-args", "-a", type=str, default=None, metavar="JSON-ARGS",
                       help="Optional JSON-encoded list to send as the request arg. If not provided, stdin is read for the "
                            "JSON-encoded list of args.")
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
            # level 2: not every file requires a login--attach credentials if available and let
            # the server decide (401/403) whether this particular file actually needs them.
            client = await self.get_client()
            file_info: CgDownloadFileResult = await client.download_file(
                    file_id,
                    format=format,
                    timestamp=timestamp,
                    require_login=False,
                )
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
        p.add_argument("--timestamp", type=parse_timestamp, default=None, metavar="TIMESTAMP",
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
            client = await self.get_client(require_credentials=True)
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
        p.add_argument(
                "--json", "-j", default=False, action="store_true",
                help="Where supported, output information in JSON format.",
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
