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

from ..client.async_.client import CgAsyncClient
from ..client.common.protocol.contribution import CgContributionData
from ..client.common.protocol.test_session import CgMultipleLanguagesTestParams, CgPlayRequest, CgSubmitRequest
from ..client.common.protocol.user import CgUserProperties
from ..client.common.raw_client import CgAuthenticationError, CgDownloadFileResult, compute_content_hash
from ..common.timestamps import parse_timestamp
from ..common.typedefs import Self, override
from ..credentials.browser_login import async_cg_browser_login, cg_browser_delete_session
from ..credentials.cg_credentials import CgCredentials, get_credentials_with_override, set_credentials

logger = logging.getLogger(__name__)

class CgCli(CliBase):
    """Command-line interface for the contribution manager."""

    _client: CgAsyncClient | None = None
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
    
    async def get_client(self, *, require_credentials: bool = False, validate: bool = False) -> CgAsyncClient:
        """Return the CgAsyncClient instance, initializing it if necessary.

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
            self._client = CgAsyncClient(
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
                async with CgAsyncClient(
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

    @cli_command("Notification service commands.")
    async def cmd_api__notification(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Find unread notifications for a codingamer.")
    async def cmd_api__notification__find_unread_notifications(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            # level 2 here is enough: notification_find_unread_notifications() enforces its own
            # login requirement (the endpoint always needs a valid session) and resolves the
            # default codingamer_id itself.
            client = await self.get_client()
            notifications = await client.services.notification.find_unread_notifications(codingamer_id)
            print(json.dumps([n.to_dict() for n in notifications], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer ID to find unread notifications for. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Contribution service commands.")
    async def cmd_api__contribution(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Find a contribution by its opaque contribution ID.")
    async def cmd_api__contribution__find_contribution(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_id: str = self.args.contribution_id
            arg2: bool = not self.args.arg2_false
            client = await self.get_client()
            contribution = await client.services.contribution.find_contribution(contribution_id, arg2)
            print(json.dumps(contribution.to_dict(), indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("contribution_id", type=str, metavar="CONTRIBUTION-ID",
                       help="Opaque contribution ID string.")
        p.add_argument("--arg2-false", default=False, action="store_true",
                       help="Set the API's second (purpose unknown) argument to False instead of the default True.")
        return handler

    @cli_command("Count new contributions published since a given point in time.")
    async def cmd_api__contribution__find_new_contribution_count(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            since: datetime | None = self.args.since
            client = await self.get_client()
            count = await client.services.contribution.find_new_contribution_count(codingamer_id, since)
            print(json.dumps(count))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer to count new contributions for. Defaults to the logged-in codingamer's ID.")
        p.add_argument("--since", type=parse_timestamp, default=None, metavar="TIMESTAMP",
                       help="Count contributions published after this point in time. Can be milliseconds "
                            "since epoch (e.g., '1680000000000'), a duration string (e.g., '1h30m'), a relative "
                            "duration from now (e.g., '-1h30m'), or an ISO 8601 datetime string. Defaults to now.")
        return handler

    @cli_command("Get pending (community-review-queue) contributions.")
    async def cmd_api__contribution__get_all_pending_contributions(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_type_filter: str = self.args.type_filter
            codingamer_id: int | None = self.args.codingamer_id
            page: int = self.args.page
            client = await self.get_client()
            contributions = await client.services.contribution.get_all_pending_contributions(
                    contribution_type_filter, codingamer_id, page)
            print(json.dumps([c.to_dict() for c in contributions], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--type-filter", "-t", type=str, default="ALL", metavar="FILTER",
                       help="Category filter: 'ALL', 'CLASHOFCODE', or 'PUZZLE'. Defaults to 'ALL'.")
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Must equal the logged-in codingamer's own ID (server-enforced). "
                            "Defaults to the logged-in codingamer's ID.")
        p.add_argument("--page", "-n", type=int, default=1, metavar="PAGE",
                       help="Assumed 1-indexed page number; unconfirmed. Defaults to 1.")
        return handler

    @cli_command("Submit a new version of a contribution's content. A JSON-serialized "
                 "CgContributionData object is read from stdin.")
    async def cmd_api__contribution__update_contribution(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_id: str = self.args.contribution_id
            puzzle_type: str = self.args.puzzle_type
            prev_version: int = self.args.prev_version
            draft: bool = self.args.draft
            ready_for_moderation: bool = self.args.ready_for_moderation
            codingamer_id: int | None = self.args.codingamer_id
            contribution_data = CgContributionData.loads(sys.stdin.read())
            client = await self.get_client()
            contribution = await client.services.contribution.update_contribution(
                    contribution_id, puzzle_type, contribution_data, draft, ready_for_moderation,
                    prev_version, codingamer_id)
            print(json.dumps(contribution.to_dict(), indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("contribution_id", type=str, metavar="CONTRIBUTION-ID",
                       help="Opaque contribution ID string.")
        p.add_argument("puzzle_type", type=str, metavar="PUZZLE-TYPE",
                       help="The type of the contribution, e.g. 'PUZZLE_INOUT'.")
        p.add_argument("prev_version", type=int, metavar="PREV-VERSION",
                       help="The contribution's current version number, as last retrieved via find-contribution "
                            "(an idempotency/concurrency check--rejected if stale).")
        p.add_argument("--draft", default=False, action="store_true",
                       help="Submit as a private, unpublished draft. Defaults to false.")
        p.add_argument("--ready-for-moderation", default=False, action="store_true",
                       help="Formally submit for moderation. Defaults to false.")
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="The authoring codingamer's numeric ID. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("ClashOfCode service commands.")
    @cli_command("ClashOfCode service commands.")
    async def cmd_api__clash_of_code(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Get a codingamer's global Clash of Code ranking.")
    async def cmd_api__clash_of_code__get_clash_rank_by_codingamer_id(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            clash_rank = await client.services.clash_of_code.get_clash_rank_by_codingamer_id(codingamer_id)
            print(json.dumps(clash_rank.to_dict() if clash_rank is not None else None, indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer numeric ID. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Find a Clash of Code session by its handle.")
    async def cmd_api__clash_of_code__find_clash_by_handle(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            handle: str = self.args.handle
            client = await self.get_client()
            clash = await client.services.clash_of_code.find_clash_by_handle(handle)
            print(json.dumps(clash.to_dict(), indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("handle", type=str, metavar="HANDLE",
                       help="Opaque clash-instance handle string (a per-slot handle from "
                            "'api featured-event find-clash-slots'; not a codingamer handle or the "
                            "parent featured event's own handle--both are rejected by the server).")
        return handler

    @cli_command("ClashOfCodeDescription service commands.")
    async def cmd_api__clash_of_code_description(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Get localized help/explainer content for Clash of Code.")
    async def cmd_api__clash_of_code_description__get_clash_description(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            client = await self.get_client()
            description = await client.services.clash_of_code_description.get_clash_description()
            print(json.dumps(description.to_dict(), indent=2, sort_keys=True))
        return handler

    @cli_command("FeaturedEvent service commands.")
    async def cmd_api__featured_event(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Find upcoming and ongoing site-wide featured events.")
    async def cmd_api__featured_event__find_upcoming_and_ongoing_featured_events(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            events = await client.services.featured_event.find_upcoming_and_ongoing_featured_events(codingamer_id)
            print(json.dumps([e.to_dict() for e in events], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer to check registration status for. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Check whether a codingamer is auto-registered for featured events.")
    async def cmd_api__featured_event__is_codingamer_auto_registered(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            auto_registered = await client.services.featured_event.is_codingamer_auto_registered(codingamer_id)
            print(json.dumps(auto_registered))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer to check. Must be the logged-in codingamer's own ID "
                            "(server-enforced). Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Count featured events published since a given point in time.")
    async def cmd_api__featured_event__find_new_featured_event_count(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            since: datetime | None = self.args.since
            client = await self.get_client()
            count = await client.services.featured_event.find_new_featured_event_count(since)
            print(json.dumps(count))
        p = cmd.get_parser()
        p.add_argument("--since", type=parse_timestamp, default=None, metavar="TIMESTAMP",
                       help="Count featured events published after this point in time. Can be milliseconds "
                            "since epoch (e.g., '1680000000000'), a duration string (e.g., '1h30m'), a relative "
                            "duration from now (e.g., '-1h30m'), or an ISO 8601 datetime string. Defaults to now.")
        return handler

    @cli_command("Find the individual scheduled Clash of Code slots belonging to a featured event.")
    async def cmd_api__featured_event__find_clash_slots(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            featured_event_id: int = self.args.featured_event_id
            client = await self.get_client()
            slots = await client.services.featured_event.find_clash_slots(featured_event_id)
            print(json.dumps([s.to_dict() for s in slots], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("featured_event_id", type=int, metavar="FEATURED-EVENT-ID",
                       help="The numeric 'id' of a CLASH_OF_CODE-type featured event (not its 'handle').")
        return handler

    @cli_command("Find a featured event by its opaque handle.")
    async def cmd_api__featured_event__find_by_handle(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            handle: str = self.args.handle
            client = await self.get_client()
            event = await client.services.featured_event.find_by_handle(handle)
            print(json.dumps(event.to_dict(), indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("handle", type=str, metavar="HANDLE",
                       help="Opaque featured event handle string.")
        return handler

    @cli_command("CodingamerPuzzleTopic service commands.")
    async def cmd_api__codingamer_puzzle_topic(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Find the puzzle topics a codingamer has made progress on.")
    async def cmd_api__codingamer_puzzle_topic__find_topics_by_codingamer_id(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            topics = await client.services.codingamer_puzzle_topic.find_topics_by_codingamer_id(codingamer_id)
            print(json.dumps([t.to_dict() for t in topics], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose puzzle topic progress to list. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Find the topic tree for a single puzzle, personalized with the codingamer's per-topic learned status.")
    async def cmd_api__codingamer_puzzle_topic__select_topics_by_codingamer_id_and_puzzle_id(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            puzzle_id: int = self.args.puzzle_id
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            topics = await client.services.codingamer_puzzle_topic.select_topics_by_codingamer_id_and_puzzle_id(
                    puzzle_id, codingamer_id)
            print(json.dumps([t.to_dict() for t in topics], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("puzzle_id", type=int, metavar="PUZZLE-ID",
                       help="Numeric ID of the puzzle.")
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose topic mastery to check. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Puzzle service commands.")
    async def cmd_api__puzzle(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Count a codingamer's solved puzzles, broken down by programming language.")
    async def cmd_api__puzzle__count_solved_puzzles_by_programming_language(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            counts = await client.services.puzzle.count_solved_puzzles_by_programming_language(codingamer_id)
            print(json.dumps([c.to_dict() for c in counts], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose solved-puzzle counts to list. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Find the current puzzle of the week.")
    async def cmd_api__puzzle__find_puzzle_of_the_week(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            client = await self.get_client()
            puzzle = await client.services.puzzle.find_puzzle_of_the_week()
            print(json.dumps(puzzle.to_dict(), indent=2, sort_keys=True))
        return handler

    @cli_command("Find a codingamer's minimal progress summary for every puzzle they have some relationship to.")
    async def cmd_api__puzzle__find_all_minimal_progress(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            progress = await client.services.puzzle.find_all_minimal_progress(codingamer_id)
            print(json.dumps([p.to_dict() for p in progress], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose puzzle progress to list. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Find a codingamer's progress summary for a specific set of puzzles, by puzzle ID.")
    async def cmd_api__puzzle__find_progress_by_ids(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            puzzle_ids: list[int] = self.args.puzzle_ids
            codingamer_id: int | None = self.args.codingamer_id
            arg3: int = self.args.arg3
            client = await self.get_client()
            progress = await client.services.puzzle.find_progress_by_ids(puzzle_ids, codingamer_id, arg3)
            print(json.dumps([p.to_dict() for p in progress], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("puzzle_ids", type=int, nargs="+", metavar="PUZZLE-ID",
                       help="One or more numeric puzzle IDs to look up.")
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose progress to look up. Defaults to the logged-in codingamer's ID.")
        p.add_argument("--arg3", type=int, default=2, metavar="N",
                       help="Third (purpose unclear) argument to the underlying API call. Defaults to 2.")
        return handler

    @cli_command("Find the best progress on a given puzzle among the codingamers a codingamer follows.")
    async def cmd_api__puzzle__find_best_following_progress(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            puzzle_id: int = self.args.puzzle_id
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            progress = await client.services.puzzle.find_best_following_progress(puzzle_id, codingamer_id)
            print(json.dumps([p.to_dict() for p in progress], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("puzzle_id", type=int, metavar="PUZZLE-ID",
                       help="Numeric ID of the puzzle to check.")
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose followees to check. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Find a codingamer's progress summary for a single puzzle, by its pretty ID.")
    async def cmd_api__puzzle__find_progress_by_pretty_id(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            pretty_id: str = self.args.pretty_id
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            puzzle = await client.services.puzzle.find_progress_by_pretty_id(pretty_id, codingamer_id)
            print(json.dumps(puzzle.to_dict(), indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("pretty_id", type=str, metavar="PRETTY-ID",
                       help="The puzzle's pretty ID: displayed title, lowercased with spaces replaced by "
                            "hyphens, e.g. 'literary-alfabet-soupe'.")
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose progress to look up. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("LastActivities service commands.")
    async def cmd_api__last_activities(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Get a codingamer's most recent activity feed entries.")
    async def cmd_api__last_activities__get_last_activities(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            limit: int = self.args.limit
            client = await self.get_client()
            activities = await client.services.last_activities.get_last_activities(codingamer_id, limit)
            print(json.dumps([a.to_dict() for a in activities], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose recent activity to list. Defaults to the logged-in codingamer's ID.")
        p.add_argument("--limit", "-n", type=int, default=4, metavar="N",
                       help="Maximum number of activity entries to return. Defaults to 4.")
        return handler

    @cli_command("Quest service commands.")
    async def cmd_api__quest(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Find a codingamer's quest map.")
    async def cmd_api__quest__find_quest_map(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            quest_map = await client.services.quest.find_quest_map(codingamer_id)
            print(json.dumps(quest_map.to_dict(), indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose quest map to fetch. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Count a codingamer's completed-but-unclaimed (lootable) quests.")
    async def cmd_api__quest__count_lootable_quests(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            count = await client.services.quest.count_lootable_quests(codingamer_id)
            print(json.dumps(count))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer to count lootable quests for. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Intercom service commands.")
    async def cmd_api__intercom(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Generate an Intercom identity-verification JWT for the logged-in codingamer.")
    async def cmd_api__intercom__generate_token(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            client = await self.get_client()
            token = await client.services.intercom.generate_token()
            print(json.dumps(token))
        return handler

    @cli_command("Survey service commands.")
    async def cmd_api__survey(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Find a survey to potentially show a codingamer (UNVERIFIED--response shape unconfirmed).")
    async def cmd_api__survey__find_survey(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            limit: int = self.args.limit
            client = await self.get_client()
            survey = await client.services.survey.find_survey(codingamer_id, limit)
            print(json.dumps(survey.to_dict() if survey is not None else None, indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer to find a survey for. Defaults to the logged-in codingamer's ID.")
        p.add_argument("--limit", "-n", type=int, default=2, metavar="N",
                       help="Assumed maximum number of results; unconfirmed. Defaults to 2.")
        return handler

    @cli_command("Achievement service commands.")
    async def cmd_api__achievement(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Find the achievements a codingamer has unlocked.")
    async def cmd_api__achievement__find_by_codingamer_id(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            achievements = await client.services.achievement.find_by_codingamer_id(codingamer_id)
            print(json.dumps([a.to_dict() for a in achievements], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose achievements to list. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("User service commands.")
    async def cmd_api__user(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Update a subset of a codingamer's account properties.")
    async def cmd_api__user__update_user_properties(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            contributions_list_last_visit: datetime | None = self.args.contributions_list_last_visit
            properties = CgUserProperties()
            if contributions_list_last_visit is not None:
                properties.contributions_list_last_visit = contributions_list_last_visit
            client = await self.get_client()
            await client.services.user.update_user_properties(properties, codingamer_id)
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer to update. Defaults to the logged-in codingamer's ID.")
        p.add_argument("--contributions-list-last-visit", type=parse_timestamp, default=None, metavar="TIMESTAMP",
                       help="Set the codingamer's last-visit time for their contributions list. Can be "
                            "milliseconds since epoch, a duration string (e.g., '1h30m'), a relative duration "
                            "from now (e.g., '-1h30m'), or an ISO 8601 datetime string.")
        return handler

    @cli_command("TestSession service commands.")
    async def cmd_api__test_session(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Start (or resume) an interactive IDE test session for a puzzle.")
    async def cmd_api__test_session__start_test_session(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            test_session_handle: str = self.args.test_session_handle
            client = await self.get_client()
            session = await client.services.test_session.start_test_session(test_session_handle)
            print(json.dumps(session.to_dict(), indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("test_session_handle", type=str, metavar="TEST-SESSION-HANDLE",
                       help="The puzzle's test session handle (e.g. CgLastActivityPuzzle.test_session_handle).")
        return handler

    @cli_command("Run a codingamer's code against a single test case within a test session. Code is read from stdin.")
    async def cmd_api__test_session__play(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            test_session_handle: str = self.args.test_session_handle
            programming_language_id: str = self.args.language
            test_index: int | None = self.args.test_index
            code = sys.stdin.read()
            request = CgPlayRequest(code=code, programming_language_id=programming_language_id)
            if test_index is not None:
                request.multiple_languages = CgMultipleLanguagesTestParams(test_index=test_index)
            client = await self.get_client()
            result = await client.services.test_session.play(test_session_handle, request)
            print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("test_session_handle", type=str, metavar="TEST-SESSION-HANDLE",
                       help="The puzzle's test session handle.")
        p.add_argument("--language", "-l", type=str, required=True, metavar="LANGUAGE-ID",
                       help="Programming language ID the code is written in, e.g. 'Python3'.")
        p.add_argument("--test-index", "-t", type=int, default=None, metavar="N",
                       help="1-based test case index to run against, for MULTIPLE_LANGUAGES-type puzzles.")
        return handler

    @cli_command("Generate a Language Server Protocol (LSP) auth token for a test session.")
    async def cmd_api__test_session__generate_lsp_token(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            test_session_id: int = self.args.test_session_id
            client = await self.get_client()
            token = await client.services.test_session.generate_lsp_token(test_session_id)
            print(json.dumps(token))
        p = cmd.get_parser()
        p.add_argument("test_session_id", type=int, metavar="TEST-SESSION-ID",
                       help="The test session's numeric ID (CgTestSession.test_session_id).")
        return handler

    @cli_command("Submit a final solution to a puzzle for credit. Code is read from stdin.")
    async def cmd_api__test_session__submit(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            test_session_handle: str = self.args.test_session_handle
            programming_language_id: str = self.args.language
            code = sys.stdin.read()
            request = CgSubmitRequest(code=code, programming_language_id=programming_language_id)
            client = await self.get_client()
            submission_id = await client.services.test_session.submit(test_session_handle, request)
            print(json.dumps(submission_id))
        p = cmd.get_parser()
        p.add_argument("test_session_handle", type=str, metavar="TEST-SESSION-HANDLE",
                       help="The puzzle's test session handle.")
        p.add_argument("--language", "-l", type=str, required=True, metavar="LANGUAGE-ID",
                       help="Programming language ID the code is written in, e.g. 'Python3'.")
        return handler

    @cli_command("Report service commands.")
    async def cmd_api__report(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Find the results report for a single puzzle submission.")
    async def cmd_api__report__find_report_by_submission(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            submission_id: int = self.args.submission_id
            client = await self.get_client()
            report = await client.services.report.find_report_by_submission(submission_id)
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("submission_id", type=int, metavar="SUBMISSION-ID",
                       help="Numeric ID of the submission.")
        return handler

    @cli_command("TestSessionQuestionSubmission service commands.")
    async def cmd_api__test_session_question_submission(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Find all past submissions for a puzzle, most recent first.")
    async def cmd_api__test_session_question_submission__find_all_submissions(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            test_session_handle: str = self.args.test_session_handle
            client = await self.get_client()
            submissions = await client.services.test_session_question_submission.find_all_submissions(
                    test_session_handle)
            print(json.dumps([s.to_dict() for s in submissions], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("test_session_handle", type=str, metavar="TEST-SESSION-HANDLE",
                       help="The puzzle's test session handle.")
        return handler

    @cli_command("CodinGamer service commands.")
    async def cmd_api__codingamer(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Find a codingamer's points/ranking stats by their opaque public handle.")
    async def cmd_api__codingamer__find_codingame_points_stats_by_handle(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            handle: str = self.args.handle
            client = await self.get_client()
            stats = await client.services.codingamer.find_codingame_points_stats_by_handle(handle)
            print(json.dumps(stats.to_dict(), indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("handle", type=str, metavar="HANDLE",
                       help="Opaque codingamer public handle string (not the numeric codingamer ID).")
        return handler

    @cli_command("Find a codingamer's public profile information by their numeric ID.")
    async def cmd_api__codingamer__find_codingamer_public_informations(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            codingamer = await client.services.codingamer.find_codingamer_public_informations(codingamer_id)
            print(json.dumps(codingamer.to_dict(), indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer numeric ID. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Find the followers of a codingamer.")
    async def cmd_api__codingamer__find_followers(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            current_codingamer_id: int | None = self.args.current_codingamer_id
            client = await self.get_client()
            followers = await client.services.codingamer.find_followers(codingamer_id, current_codingamer_id)
            print(json.dumps([f.to_dict() for f in followers], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose followers to list. Defaults to the logged-in codingamer's ID.")
        p.add_argument("--current-codingamer-id", "-c", type=int, default=None, metavar="ID",
                       help="Must equal the logged-in codingamer's ID (server-enforced). "
                            "Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Find the codingamers that a codingamer is following.")
    async def cmd_api__codingamer__find_following(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            current_codingamer_id: int | None = self.args.current_codingamer_id
            client = await self.get_client()
            following = await client.services.codingamer.find_following(codingamer_id, current_codingamer_id)
            print(json.dumps([f.to_dict() for f in following], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose followees to list. Defaults to the logged-in codingamer's ID.")
        p.add_argument("--current-codingamer-id", "-c", type=int, default=None, metavar="ID",
                       help="Must equal the logged-in codingamer's ID (server-enforced). "
                            "Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Find a codingamer's follow-card summary (profile plus follow-relationship flags).")
    async def cmd_api__codingamer__find_codingamer_follow_card(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            current_codingamer_id: int | None = self.args.current_codingamer_id
            client = await self.get_client()
            card = await client.services.codingamer.find_codingamer_follow_card(
                    codingamer_id, current_codingamer_id)
            print(json.dumps(card.to_dict(), indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose follow card to fetch. Defaults to the logged-in codingamer's ID.")
        p.add_argument("--current-codingamer-id", "-c", type=int, default=None, metavar="ID",
                       help="Must equal the logged-in codingamer's ID (server-enforced). "
                            "Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Find the numeric IDs of a codingamer's followers.")
    async def cmd_api__codingamer__find_follower_ids(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            follower_ids = await client.services.codingamer.find_follower_ids(codingamer_id)
            print(json.dumps(follower_ids, indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose follower IDs to list. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Find the numeric IDs of the codingamers that a codingamer is following.")
    async def cmd_api__codingamer__find_following_ids(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            codingamer_id: int | None = self.args.codingamer_id
            client = await self.get_client()
            following_ids = await client.services.codingamer.find_following_ids(codingamer_id)
            print(json.dumps(following_ids, indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="Codingamer whose followee IDs to list. Defaults to the logged-in codingamer's ID.")
        return handler

    @cli_command("Search service commands.")
    async def cmd_api__search(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Search for codingamers, puzzles, and other objects by name.")
    async def cmd_api__search__search(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            query: str = self.args.query
            locale: str = self.args.locale
            type_filter: str | None = self.args.type
            client = await self.get_client()
            results = await client.services.search.search(query, locale, type_filter)
            print(json.dumps([r.to_dict() for r in results], indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("query", type=str, metavar="QUERY",
                       help="Search query text, e.g. a codingamer's pseudo or part of a puzzle title.")
        p.add_argument("--locale", "-l", type=str, default="en", metavar="LOCALE",
                       help="Locale code for localized result names, e.g. 'en', 'fr'. Defaults to 'en'.")
        p.add_argument("--type", "-t", type=str, default=None, metavar="TYPE",
                       help="Restrict results to a single result type, e.g. 'USER', 'PUZZLE'. "
                            "Defaults to no filter (all types).")
        return handler

    @cli_command("ProgrammingLanguage service commands.")
    async def cmd_api__programming_language(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Find the IDs of all programming languages supported for contribution reference solutions.")
    async def cmd_api__programming_language__find_all_ids(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            client = await self.get_client()
            language_ids = await client.services.programming_language.find_all_ids()
            print(json.dumps(language_ids, indent=2, sort_keys=True))
        return handler

    @cli_command("Higher-level helper commands, layered on top of the plain API wrappers "
                 "(retries, polling, data normalization).")
    async def cmd_api_helper(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Contribution service helper commands.")
    async def cmd_api_helper__contribution(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Submit a new version of a contribution's content, with 524 retry/polling and "
                 "test-case data normalization. A JSON-serialized CgContributionData object is "
                 "read from stdin.")
    async def cmd_api_helper__contribution__update_contribution(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_id: str = self.args.contribution_id
            puzzle_type: str = self.args.puzzle_type
            prev_version: int = self.args.prev_version
            draft: bool = self.args.draft
            ready_for_moderation: bool = self.args.ready_for_moderation
            codingamer_id: int | None = self.args.codingamer_id
            strip_test_final_eols: bool = self.args.strip_test_final_eols
            max_wait_seconds: float = self.args.max_wait_seconds
            contribution_data = CgContributionData.loads(sys.stdin.read())
            client = await self.get_client()
            contribution = await client.services.contribution.helper.update_contribution(
                    contribution_id, puzzle_type, contribution_data, draft, ready_for_moderation,
                    prev_version, codingamer_id, strip_test_final_eols=strip_test_final_eols,
                    max_wait_seconds=max_wait_seconds)
            print(json.dumps(contribution.to_dict(), indent=2, sort_keys=True))
        p = cmd.get_parser()
        p.add_argument("contribution_id", type=str, metavar="CONTRIBUTION-ID",
                       help="Opaque contribution ID string.")
        p.add_argument("puzzle_type", type=str, metavar="PUZZLE-TYPE",
                       help="The type of the contribution, e.g. 'PUZZLE_INOUT'.")
        p.add_argument("prev_version", type=int, metavar="PREV-VERSION",
                       help="The contribution's current version number, as last retrieved via find-contribution "
                            "(an idempotency/concurrency check--rejected if stale).")
        p.add_argument("--draft", default=False, action="store_true",
                       help="Submit as a private, unpublished draft. Defaults to false.")
        p.add_argument("--ready-for-moderation", default=False, action="store_true",
                       help="Formally submit for moderation. Defaults to false.")
        p.add_argument("--codingamer-id", "-g", type=int, default=None, metavar="ID",
                       help="The authoring codingamer's numeric ID. Defaults to the logged-in codingamer's ID.")
        p.add_argument("--no-strip-test-final-eols", dest="strip_test_final_eols",
                       default=True, action="store_false",
                       help="Don't strip a single trailing newline from each test case's input/output text "
                            "before submitting. By default, this normalization is applied.")
        p.add_argument("--max-wait-seconds", type=float, default=0.0, metavar="SECONDS",
                       help="If the server returns HTTP 524 (Cloudflare/origin timeout), how long to keep "
                            "polling find-contribution for the version to increment before giving up, in "
                            "seconds. Defaults to 0, meaning wait indefinitely.")
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
