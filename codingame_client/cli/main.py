"""CLI interface for contribution manager."""

from __future__ import annotations

import difflib
import json
import logging
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import cast

import aiohttp
from argparse_wizard import CliBase, CliCommand, CliError, OptCmdFunc, cli_command
from json_data_types import JsonData, JsonList
from rich.console import Console

from ..client.async_.client import CgAsyncClient
from ..client.common.protocol.contribution import CgContributionData
from ..client.common.protocol.test_session import CgMultipleLanguagesTestParams, CgPlayRequest, CgSubmitRequest
from ..client.common.protocol.user import CgUserProperties
from ..client.common.raw_client import CgAuthenticationError, CgDownloadFileResult, compute_content_hash
from ..common.timestamps import parse_timestamp
from ..common.typedefs import Self, override
from ..config import (
    CONFIG_FILE_NAME,
    CONFIG_SUBDIR_NAME,
    PROJECT_CONFIG_MARKER_DIR_NAME,
    CgConfig,
    CgConfigData,
    default_global_config_file,
    find_config_file,
    resolve_config,
)
from ..contribution_manager import (
    DATA_SUBDIR_NAME,
    DEFAULT_MERGE_TOOL,
    TESTS_SUBDIR_NAME,
    CgContributionCommitData,
    CgContributionManager,
    CgContributionView,
    CgMergeStartStatus,
    CgMergeToolNotFoundError,
    CgRebaseStatus,
    TwoWayEntry,
    diff_three_trees,
    diff_two_trees,
    find_contribution_dir,
    launch_merge_tool,
    render_three_way_diff,
    render_two_way_diff,
    renormalize_test_case_dirs,
    resolve_contribution_dir,
)
from ..credentials.browser_login import async_cg_browser_login, cg_browser_delete_session
from ..credentials.cg_credentials import (
    CgCredentials,
    get_credentials_with_override,
    set_credentials,
    validate_profile_name,
)
from ..settings import CgSettings, resolve_settings

logger = logging.getLogger(__name__)

def default_config_template(default_data_dir: Path) -> str:
    """Build the content for a freshly-`init`'d config.yaml.

       Hand-written (not generated via CgConfigData.to_yaml()) so it can carry comments--plain
       YAML dumping can't emit those. Deliberately kept in sync with CgConfigData's actual fields
       by a test that parses this (for some placeholder path) and asserts it equals
       CgConfigData() (all defaults); update both together if a field is added, renamed, or its
       default changes.

       `default_data_dir` is the actual resolved default for the specific config file being
       created (project-local sibling "data" dir, or the global per-user data location for
       --global)--shown as the commented-out example value instead of a static description,
       since the two cases genuinely differ and a fixed comment describing one would be
       misleading for the other.
    """
    return f"""\
# codingame-client configuration file.
#
# Run `cg config where` to see which config file is currently active (this one, unless
# shadowed by a more specific one), and `cg config dump` to see the fully resolved
# configuration, including defaults for anything left unset here.

# Override the persistent, app-writable data directory. A relative path is resolved relative
# to the directory containing this file; an absolute path (or a "~"-prefixed path) is used
# as-is. Currently defaults to (uncomment to pin explicitly):
#dataDir: {default_data_dir}
"""

class CgCli(CliBase):
    """Command-line interface for the contribution manager."""

    _client: CgAsyncClient | None = None
    _client_authenticated: bool = False
    _client_validated: bool = False
    _console: Console | None = None
    _resolved_config: CgConfig | None = None
    _resolved_settings: CgSettings | None = None
    
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
            # resolve_default_settings() (rather than CgAsyncClient's own no-args best-effort
            # fallback) so that -c/--config actually controls the client's default-profile
            # resolution too--not just cg config/cg settings commands--and so this agrees with
            # login_helper()'s own resolution (see resolve_default_settings()'s docstring for why
            # that matters). Only attempted when actually needed (profile is None); skipping it
            # otherwise avoids a spurious FileNotFoundError from a broken --config that the
            # client wouldn't even consult in that case.
            settings = None if profile is not None else self.resolve_default_settings()
            self._client = CgAsyncClient(
                profile_name=profile,
                trace_configs=self.get_trace_configs(),
                settings=settings,
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

    async def get_config(self) -> CgConfig:
        """Return the resolved configuration for this invocation, resolving it lazily on first
           use (honoring the --config/-c flag) and caching the result for the rest of the process.

           Raises CgConfigNotFoundError if none can be found. Any predispatch hook or command
           handler that needs config can just call this--call order and command hierarchy depth
           don't matter, since the first caller triggers resolution and everyone after gets the
           cached value. `cg config init` never calls this (it constructs its own target path
           from scratch); `cg config where` calls `find_config_file()` directly instead, since it
           needs to report absence as normal output rather than let it raise.
        """
        if self._resolved_config is None:
            explicit: str | None = self.args.config
            self._resolved_config = resolve_config(explicit)
        return self._resolved_config

    async def get_settings(self) -> CgSettings:
        """Return the resolved settings for this invocation, resolving it lazily on first use
           (which itself lazily resolves the config via `get_config()`) and caching the result.

           Unlike `get_config()`, never raises for "not found"--a missing settings.json just
           means all-default settings (see `resolve_settings()`).
        """
        if self._resolved_settings is None:
            config = await self.get_config()
            self._resolved_settings = resolve_settings(config)
        return self._resolved_settings

    def resolve_default_settings(self) -> CgSettings:
        """Best-effort settings resolution: honors -c/--config, but--unlike `get_settings()`--
           never raises `CgConfigNotFoundError` if no config.yaml exists (see
           `resolve_config(allow_default=True)`).

           This exists specifically so `get_client()` and `login_helper()` resolve the effective
           default profile name (when --profile isn't given) via the exact same logic and always
           agree with each other--previously, `login_helper()` saved credentials under whatever
           `credentials.cg_credentials`'s own hardcoded default profile resolved to, while
           `get_client()` separately resolved the profile via settings/config, and the two could
           silently disagree (e.g. settings.json overriding the default profile) with the
           confusing symptom of "login succeeded but the client reports unauthenticated". `cg
           settings dump`/`cg config dump` intentionally keep using the strict
           `get_settings()`/`get_config()` instead--those exist specifically to tell the user
           "nothing configured yet", which this method must never do.

           Not cached on the CLI instance (unlike `get_config()`/`get_settings()`)--cheap to
           recompute (pure filesystem checks), and giving it its own cache would either diverge
           from `get_config()`/`get_settings()`'s cache or require unifying them despite their
           different failure semantics, both worse than just recomputing.
        """
        return resolve_settings(resolve_config(self.args.config, allow_default=True))

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
        if profile_name is None:
            # Resolved once, up front, via the same best-effort settings/config logic
            # get_client() uses (see resolve_default_settings()'s docstring)--every use of
            # profile_name below (credential lookup, save, and the validation client
            # construction) must agree on the same concrete profile name, or credentials can be
            # saved under one profile and then looked up under another.
            profile_name = self.resolve_default_settings().default_profile
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
            # profile_name here is self.args.profile, possibly still None (login_helper resolves
            # its own local copy internally)--not guessing "default" avoids this message being
            # wrong when the resolved default profile is actually something else.
            resolved_profile_desc = profile_name if profile_name is not None else "<resolved default>"
            self.logger.debug(f"Login completed successfully for profile {resolved_profile_desc!r}")

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

    @cli_command("Download a file by server object ID (the fileservlet servlet).")
    async def cmd_api__file_servlet(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            file_id: int = self.args.file_id
            timestamp: datetime | None = self.args.timestamp
            format: str | None = self.args.format
            self.eprint(f"Downloading file with ID: {file_id}")
            # level 2: not every file requires a login--attach credentials if available and let
            # the server decide (401/403) whether this particular file actually needs them.
            client = await self.get_client()
            file_info: CgDownloadFileResult = await client.servlets.file_servlet(
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

    @cli_command("Upload a file from stdin (the fileupload servlet).")
    async def cmd_api__file_upload(self, cmd: CliCommand[Self]) -> OptCmdFunc:
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
            result = await client.servlets.file_upload(
                    content,
                    filename=filename,
                    content_type=content_type,
                )
            print(str(result.id))
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

    @cli_command("Contribution working directory commands--manage a local, possibly-uncommitted "
                 "working view of a single contribution (see `cg api contribution`/`cg api-helper "
                 "contribution` for the raw, stateless API this is built on).")
    async def cmd_contribution(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        p = cmd.get_parser()
        p.add_argument("--contribution-dir", type=Path, default=None, metavar="DIR",
                       help="Working directory to operate on. Defaults to CG_CONTRIBUTION_DIR, then "
                            "the configured default (`cg settings set contribution-dir`), then the "
                            "current directory or \"./contribution\" if it contains contribution.json. "
                            "Ignored by `cg contribution import`, which always takes an explicit new "
                            "target directory as a positional argument instead.")
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Build a fresh contribution working directory from an existing server-side "
                 "contribution: findContribution, plus downloading the cover image if one is set. "
                 "DIRECTORY must not already exist. Ignores --contribution-dir.")
    async def cmd_contribution__import(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_id: str = self.args.contribution_id
            directory: Path = self.args.directory
            if directory.exists():
                raise CliError(
                        f"Directory already exists: {directory}. `cg contribution import` only "
                        "creates a new working directory; import into an existing one by editing "
                        "it directly, or remove the directory first."
                    )
            client = await self.get_client()
            manager = CgContributionManager(directory, client)
            working = await manager.import_(contribution_id)
            self.eprint(f"Imported contribution {contribution_id!r} into {directory}")
            self.eprint(f"  title: {working.data.title!r}")
            self.eprint(f"  puzzleType: {working.puzzle_type!r}")
        p = cmd.get_parser()
        p.add_argument("contribution_id", type=str, metavar="CONTRIBUTION-ID",
                       help="Opaque contribution ID string (see `cg api contribution find-contribution`).")
        p.add_argument("directory", type=Path, metavar="DIRECTORY",
                       help="New directory to create the working directory in. Must not already exist.")
        return handler

    @cli_command("Push this working directory's content to the server via updateContribution "
                 "(with 524 retry/polling and test-case data normalization). Requires "
                 ".meta/last_committed/ to already exist--submitting a brand-new contribution isn't "
                 "supported yet.")
    async def cmd_contribution__commit(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            resolved_dir = resolve_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            client = await self.get_client(require_credentials=True)
            manager = CgContributionManager(resolved_dir, client)
            result = await manager.commit()
            self.eprint(
                    f"Committed {resolved_dir} -> contribution {result.public_handle!r}, "
                    f"version {result.last_version.version}"
                )
        return handler

    @cli_command("Show which contribution working directory would be used.")
    async def cmd_contribution__where(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            found = find_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            if found is None:
                print("No contribution working directory found. Run `cg contribution import CONTRIBUTION-ID DIRECTORY` to create one.")
                return
            print(f"Contribution directory: {found}")
        return handler

    @cli_command("Revert this working directory's content to match .meta/last_committed/ (the cached "
                 "base state) exactly, discarding local edits. Purely local--no network access, "
                 "unlike `cg contribution merge discard-local`, which re-fetches from the server.")
    async def cmd_contribution__revert(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            resolved_dir = resolve_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            manager = CgContributionManager(resolved_dir, await self.get_client())
            working = manager.revert()
            self.eprint(f"{resolved_dir}: reverted to .meta/last_committed/ (title: {working.data.title!r}).")
        return handler

    @cli_command("Renumber tests/'s ordinal directories to a clean, sequential, zero-padded sort "
                 "key, preserving relative order (see the tests/ directory layout in "
                 "codingame_client.contribution_manager.test_cases_dir).")
    async def cmd_contribution__renormalize_tests(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            resolved_dir = resolve_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            renormalize_test_case_dirs(resolved_dir / TESTS_SUBDIR_NAME)
            self.eprint(f"Renormalized {resolved_dir / TESTS_SUBDIR_NAME}")
        return handler

    @cli_command("Detect drift between the server and this working directory, resolving it "
                 "automatically when unambiguous: a no-op if the server hasn't changed since "
                 ".meta/last_committed/ (regardless of local edits), a fast-forward if only the server "
                 "changed (equivalent to `merge discard-local`), or a reported conflict--left "
                 "entirely alone--if both sides changed (see `cg contribution diff`/`merge`).")
    async def cmd_contribution__rebase(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            resolved_dir = resolve_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            client = await self.get_client()
            manager = CgContributionManager(resolved_dir, client)
            status = await manager.rebase()
            if status == CgRebaseStatus.UP_TO_DATE:
                self.eprint(f"{resolved_dir}: up to date.")
            elif status == CgRebaseStatus.FAST_FORWARDED:
                self.eprint(f"{resolved_dir}: fast-forwarded to the current server state.")
            else:
                self.eprint(
                        f"{resolved_dir}: server and local have both changed since the last sync--conflict. "
                        "Run `cg contribution diff` to inspect, and `cg contribution merge` to resolve."
                    )
        return handler

    @staticmethod
    def _commit_version(loaded: tuple[CgContributionView, CgContributionCommitData] | None) -> int | str:
        """The commit version number from a `load_last_committed()`/`load_remote()` result, for
           display--"?" if not yet populated (shouldn't normally happen where this is used)."""
        return loaded[1].prev_version if loaded is not None else "?"

    async def _merge_start(self, resolved_dir: Path) -> None:
        client = await self.get_client()
        manager = CgContributionManager(resolved_dir, client)
        result = await manager.merge_start()
        if result.status == CgMergeStartStatus.ALREADY_IN_PROGRESS:
            self.eprint(
                    f"{resolved_dir}: a merge is already in progress. Run `cg contribution merge "
                    "continue` or `cg contribution merge abort`."
                )
            return
        if result.status == CgMergeStartStatus.UP_TO_DATE:
            version = self._commit_version(manager.load_last_committed())
            self.eprint(f"{resolved_dir}: server unchanged since the last commit, version {version}--nothing to merge.")
            return
        base_version = self._commit_version(manager.load_last_committed())
        remote_version = self._commit_version(manager.load_remote())
        self.eprint(f"{resolved_dir}: merge started (local was at version {base_version}, server is at version {remote_version}).")
        if result.text_conflicts:
            self.eprint(
                    "  text conflicts (resolve by hand, then `cg contribution merge continue`): "
                    + ", ".join(result.text_conflicts)
                )
        if result.binary_conflicts:
            self.eprint(
                    "  binary conflicts (kept local; see .meta/remote/<path> for the "
                    "server's version): " + ", ".join(result.binary_conflicts)
                )
        if not result.text_conflicts and not result.binary_conflicts:
            self.eprint("  no conflicts--run `cg contribution merge continue` to finish.")

    async def _launch_interactive_merge(self, resolved_dir: Path, tool_name: str | None) -> None:
        client = await self.get_client()
        manager = CgContributionManager(resolved_dir, client)
        result = await manager.merge_start()
        if result.status == CgMergeStartStatus.UP_TO_DATE:
            version = self._commit_version(manager.load_last_committed())
            self.eprint(f"{resolved_dir}: server unchanged since the last commit, version {version}--nothing to merge.")
            return
        if result.status == CgMergeStartStatus.STARTED:
            base_version = self._commit_version(manager.load_last_committed())
            remote_version = self._commit_version(manager.load_remote())
            self.eprint(f"{resolved_dir}: merge started (local was at version {base_version}, server is at version {remote_version}).")
        settings = self.resolve_default_settings()
        resolved_tool = tool_name or settings.merge_tool or DEFAULT_MERGE_TOOL
        self.eprint(f"base:   {manager.last_committed_dir}")
        self.eprint(f"local:  {resolved_dir}")
        self.eprint(f"remote: {manager.remote_dir}")
        try:
            exit_code = launch_merge_tool(
                    resolved_tool, base_dir=manager.last_committed_dir, local_dir=resolved_dir,
                    remote_dir=manager.remote_dir,
                )
        except CgMergeToolNotFoundError as e:
            raise CliError(str(e)) from e
        self.eprint(
                f"{resolved_tool} exited with code {exit_code}. Merge is still in progress--run "
                "`cg contribution merge continue` (or `abort`) when done."
            )

    @cli_command("Resolve drift between the server and this working directory--parent for the "
                 "merge state machine (start/continue/abort/interactive) and the instant "
                 "discard-local/discard-server resolutions. Bare `cg contribution merge` is an "
                 "alias for `merge start`.")
    async def cmd_contribution__merge(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            resolved_dir = resolve_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            await self._merge_start(resolved_dir)
        return handler

    @cli_command("Begin a merge: materialize base/local/remote into .meta/merge/, auto-resolve "
                 "unambiguous changes directly into the working directory, and write diff3 "
                 "conflict markers for genuine text conflicts (keeping local, with a warning, for "
                 "binary conflicts). Idempotent--does nothing (and doesn't error) if a merge is "
                 "already in progress, or if the server's version already matches "
                 ".meta/last_committed/ (nothing to merge).")
    async def cmd_contribution__merge__start(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            resolved_dir = resolve_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            await self._merge_start(resolved_dir)
        return handler

    @cli_command("Finish an in-progress merge: verify no unresolved diff3 conflict markers "
                 "remain anywhere in the working directory, promote the merge's captured remote "
                 "snapshot to .meta/last_committed/, refresh the solution symlink, and remove "
                 ".meta/merge/.")
    async def cmd_contribution__merge__continue(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            resolved_dir = resolve_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            manager = CgContributionManager(resolved_dir, await self.get_client())
            manager.merge_continue()
            version = self._commit_version(manager.load_last_committed())
            self.eprint(f"{resolved_dir}: merge complete, now at version {version}.")
        return handler

    @cli_command("Abort an in-progress merge: restore the working directory from the local "
                 "snapshot taken when the merge started (discarding any auto-resolution/manual "
                 "edits made since), and remove .meta/merge/. .meta/last_committed/ is left untouched.")
    async def cmd_contribution__merge__abort(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            resolved_dir = resolve_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            manager = CgContributionManager(resolved_dir, await self.get_client())
            manager.merge_abort()
            version = self._commit_version(manager.load_last_committed())
            self.eprint(
                    f"{resolved_dir}: merge aborted; working directory restored to its pre-merge "
                    f"state (still at version {version})."
                )
        return handler

    @cli_command("Show the 3-way base/local/remote diff of an in-progress merge's persistent "
                 ".meta/merge/ state, with genuine conflicts rendered diff3-style (conflict "
                 "markers) via the system `diff3`. Equivalent to bare `cg contribution diff` "
                 "while a merge is in progress--doesn't take --remote/--cached (there's no "
                 "server round-trip involved; the merge already froze its own remote snapshot). "
                 "Fails if no merge is in progress.")
    async def cmd_contribution__merge__diff(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            resolved_dir = resolve_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            manager = CgContributionManager(resolved_dir, await self.get_client())
            if not manager.merge_in_progress:
                raise CliError("No merge in progress (run `cg contribution merge` to start one).")
            self._print_three_way_diff(
                    manager, manager.last_committed_dir / DATA_SUBDIR_NAME, manager.data_dir, manager.remote_dir / DATA_SUBDIR_NAME)
        return handler

    @cli_command("Start a merge if one isn't already in progress, then launch an external 3-way "
                 "merge tool pointed at .meta/last_committed (base) and .meta/remote (remote) plus "
                 "the real working directory as \"local\" (so edits apply directly). The merge "
                 "remains in progress after the tool exits--run `cg contribution merge continue` "
                 "(or `abort`) when done.")
    async def cmd_contribution__merge__interactive(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            resolved_dir = resolve_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            tool_name: str | None = self.args.tool
            await self._launch_interactive_merge(resolved_dir, tool_name)
        p = cmd.get_parser()
        p.add_argument("--tool", type=str, default=None, metavar="NAME",
                       help="Merge tool to use (see codingame_client.contribution_manager"
                            ".merge_tools.MERGE_TOOL_COMMANDS). Defaults to the configured "
                            "`cg settings set merge-tool`, then \"meld\".")
        return handler

    @cli_command("Discard all local edits; replace the working directory (and .meta/last_committed/) "
                 "with the current server state. Instant--doesn't use the merge state machine.")
    async def cmd_contribution__merge__discard_local(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            resolved_dir = resolve_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            manager = CgContributionManager(resolved_dir, await self.get_client())
            working = await manager.merge_discard_local()
            self.eprint(f"{resolved_dir}: discarded local changes--now matches the server (title: {working.data.title!r}).")
        return handler

    @cli_command("Update .meta/last_committed/ to match the current server state, without touching any "
                 "working-directory content files. Instant--doesn't use the merge state machine.")
    async def cmd_contribution__merge__discard_server(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            resolved_dir = resolve_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            manager = CgContributionManager(resolved_dir, await self.get_client())
            snapshot = await manager.merge_discard_server()
            self.eprint(
                    f"{resolved_dir}: .meta/last_committed/ now matches the server (version "
                    f"{snapshot.prev_version}); working directory content left untouched."
                )
        return handler

    def _print_two_way_diff(self, entries: list[TwoWayEntry], *, a_label: str, b_label: str, no_changes_message: str) -> None:
        text = render_two_way_diff(entries, a_label=a_label, b_label=b_label)
        if text:
            print(text, end="")
        else:
            self.eprint(no_changes_message)

    def _print_three_way_diff(self, manager: CgContributionManager, base_dir: Path, local_dir: Path, remote_dir: Path) -> None:
        """Render the 3-way base/local/remote diff of an in-progress merge's persistent
           `.meta/merge/` state (see `cmd_contribution__diff`)."""
        entries3 = diff_three_trees(base_dir, local_dir, remote_dir)
        text = render_three_way_diff(entries3, base_dir, local_dir, remote_dir)
        if text:
            print(text, end="")
        else:
            base_version = self._commit_version(manager.load_last_committed())
            remote_version = self._commit_version(manager.load_remote())
            self.eprint(f"No differences in the merge state (local was at version {base_version}, server is at version {remote_version}).")

    @cli_command("Show what's changed. With no flags: a plain 2-way diff of local changes against "
                 ".meta/last_committed/ (no network access)--unless a merge is in progress, in "
                 "which case a 3-way base/local/remote diff of the persistent .meta/merge/ state "
                 "is shown instead, with genuine conflicts rendered diff3-style (conflict "
                 "markers) via the system `diff3`. Pass --remote to compare against the current "
                 "server state instead (always a 2-way diff, merge or not): a fresh "
                 "findContribution refreshes .meta/remote/ first (unless a merge is in progress, "
                 "in which case fetching is skipped--merge start already fetched it, and nothing "
                 "may refresh it again until the merge ends--so whatever's cached is used "
                 "as-is). Add --cached to always skip the fetch and use whatever's most recently "
                 "cached in .meta/remote/, regardless of merge state. Pass --interactive to "
                 "launch an external merge tool instead of printing text (same as "
                 "`cg contribution merge interactive`).")
    async def cmd_contribution__diff(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            resolved_dir = resolve_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            interactive: bool = self.args.interactive
            tool_name: str | None = self.args.tool
            remote: bool = self.args.remote
            cached: bool = self.args.cached

            if interactive:
                await self._launch_interactive_merge(resolved_dir, tool_name)
                return

            client = await self.get_client()
            manager = CgContributionManager(resolved_dir, client)

            if not remote:
                if manager.merge_in_progress:
                    self._print_three_way_diff(
                            manager, manager.last_committed_dir / DATA_SUBDIR_NAME, manager.data_dir,
                            manager.remote_dir / DATA_SUBDIR_NAME,
                        )
                else:
                    base_version = self._commit_version(manager.load_last_committed())
                    self._print_two_way_diff(
                            diff_two_trees(manager.last_committed_dir / DATA_SUBDIR_NAME, manager.data_dir),
                            a_label="last-commit", b_label="local",
                            no_changes_message=f"No local changes since the last commit, version {base_version}.",
                        )
                return

            if cached or manager.merge_in_progress:
                if not manager.remote_dir.is_dir():
                    raise CliError(
                            f"{manager.remote_dir} doesn't exist yet--run `cg contribution fetch` "
                            "first, or drop --cached."
                        )
            else:
                await manager.materialize_remote(manager.remote_dir)
            remote_version = self._commit_version(manager.load_remote())
            self._print_two_way_diff(
                    diff_two_trees(manager.remote_dir / DATA_SUBDIR_NAME, manager.data_dir),
                    a_label="remote", b_label="local",
                    no_changes_message=f"No local changes since the current server version {remote_version}.",
                )
        p = cmd.get_parser()
        p.add_argument("--remote", default=False, action="store_true",
                       help="Compare against the current server state (.meta/remote/) instead of "
                            ".meta/last_committed/.")
        p.add_argument("--cached", default=False, action="store_true",
                       help="With --remote, don't fetch--use whatever's already cached in "
                            ".meta/remote/ from a prior fetch/rebase/merge start/diff --remote.")
        p.add_argument("--interactive", default=False, action="store_true",
                       help="Launch an external merge tool instead of printing a text diff.")
        p.add_argument("--tool", type=str, default=None, metavar="NAME",
                       help="Merge tool to use with --interactive. Defaults to the configured "
                            "`cg settings set merge-tool`, then \"meld\".")
        return handler

    @cli_command("Refresh .meta/remote/--the cached current server state--via a fresh "
                 "findContribution. Leaves it untouched if the version hasn't changed, and avoids "
                 "re-downloading the cover image if its binary ID hasn't changed either. `rebase` "
                 "and `merge start` do this automatically; use this to refresh the cache for "
                 "`diff --remote --cached` without either of those. Refuses while a merge is in "
                 "progress.")
    async def cmd_contribution__fetch(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path | None = self.args.contribution_dir
            resolved_dir = resolve_contribution_dir(contribution_dir, settings=self.resolve_default_settings())
            client = await self.get_client()
            manager = CgContributionManager(resolved_dir, client)
            contribution = await manager.materialize_remote(manager.remote_dir)
            self.eprint(f"{resolved_dir}: .meta/remote/ refreshed (version {contribution.last_version.version}).")
        return handler

    @cli_command("Configuration commands.")
    async def cmd_config(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Create a new config.yaml--project-local (under the current directory, or "
                 "--at DIR) by default, or the shared per-user fallback location with --global. "
                 "Does not consult the top-level --config/-c flag or CG_CONFIG--that's a "
                 "discovery override for reading an existing config, not a placement option for "
                 "creating a new one.")
    async def cmd_config__init(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            use_global: bool = self.args.global_
            force: bool = self.args.force
            at: Path = self.args.at
            if use_global:
                target = default_global_config_file()
                existing: Path | None = None
            else:
                target = at / PROJECT_CONFIG_MARKER_DIR_NAME / CONFIG_SUBDIR_NAME / CONFIG_FILE_NAME
                existing = find_config_file(start_dir=at)
                if existing is not None and existing not in (target, default_global_config_file()):
                    self.eprint(f"Note: this will shadow the existing configuration found at {existing}")
            if target.is_file() and not force:
                raise CliError(f"Config file already exists: {target}. Use --force to overwrite.")
            target.parent.mkdir(parents=True, exist_ok=True)
            # Computed before writing, from an empty CgConfigData, so the template can show the
            # actual default for this specific file (project-local sibling dir, or the global
            # per-user location for --global)--not a static description that would be wrong for
            # one of the two cases.
            default_data_dir = CgConfig(config_file=target.resolve(), raw_data=CgConfigData()).data_dir
            target.write_text(default_config_template(default_data_dir))
            raw_data = CgConfigData.load_yaml(target)
            resolved = CgConfig(config_file=target.resolve(), raw_data=raw_data)
            resolved.data_dir.mkdir(parents=True, exist_ok=True)
            self.eprint(f"Created config file: {resolved.config_file}")
            self.eprint(f"Data directory: {resolved.data_dir}")
        p = cmd.get_parser()
        p.add_argument("--global", dest="global_", default=False, action="store_true",
                       help="Create the shared, per-user fallback config instead of a project-local one.")
        p.add_argument("--at", type=Path, default=Path.cwd(), metavar="DIR",
                       help="Project-local only: directory to create .cg/config/config.yaml under. "
                            "Defaults to the current directory.")
        p.add_argument("--force", "-f", default=False, action="store_true",
                       help="Overwrite an existing config file at the target location.")
        return handler

    @cli_command("Show which config.yaml (if any) would be used, and where its persistent data "
                 "directory resolves to.")
    async def cmd_config__where(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            explicit: str | None = self.args.config
            try:
                config_file = find_config_file(explicit)
            except FileNotFoundError as e:
                raise CliError(str(e)) from e
            if config_file is None:
                print("No configuration file found. Run `cg config init` to create one.")
                return
            raw_data = CgConfigData.load_yaml(config_file)
            resolved = CgConfig(config_file=config_file.resolve(), raw_data=raw_data)
            print(f"Config file: {resolved.config_file}")
            print(f"Data directory: {resolved.data_dir}")
        return handler

    @cli_command("Dump the resolved configuration as JSON.")
    async def cmd_config__dump(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            resolved = await self.get_config()
            print(json.dumps(resolved.to_dump_dict(), indent=2, sort_keys=True))
        return handler

    @cli_command("Settings commands (app-managed persistent state in settings.json, as opposed "
                 "to the user-edited config.yaml--see `cg config`).")
    async def cmd_settings(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Dump the resolved settings as JSON.")
    async def cmd_settings__dump(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            settings = await self.get_settings()
            print(json.dumps(settings.to_dump_dict(), indent=2, sort_keys=True))
        return handler

    @cli_command("Set a settings.json value.")
    async def cmd_settings__set(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Set the default codingame-client credential profile name.")
    async def cmd_settings__set__default_profile(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            profile_name: str = self.args.profile_name
            validate_profile_name(profile_name)
            settings = await self.get_settings()
            settings.raw_data.default_profile = profile_name
            settings.save()
            self.eprint(f"defaultProfile set to {profile_name!r} in {settings.settings_file}")
        p = cmd.get_parser()
        p.add_argument("profile_name", type=str, metavar="PROFILE-NAME",
                       help="The credential profile name to record as the default--used "
                            "whenever --profile isn't given (see `cg login`, `cg api ...`, etc.), "
                            "and shown resolved by `cg config dump`/`cg settings dump`.")
        return handler

    @cli_command("Set the default contribution working directory.")
    async def cmd_settings__set__contribution_dir(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            contribution_dir: Path = self.args.contribution_dir
            settings = await self.get_settings()
            settings.raw_data.contribution_dir = str(contribution_dir)
            settings.save()
            self.eprint(f"contributionDir set to {str(contribution_dir)!r} in {settings.settings_file}")
        p = cmd.get_parser()
        p.add_argument("contribution_dir", type=Path, metavar="DIR",
                       help="Directory to use as the default contribution working directory--used "
                            "whenever --contribution-dir isn't given and CG_CONTRIBUTION_DIR isn't "
                            "set (see `cg contribution import`/`cg contribution commit`).")
        return handler

    @cli_command("Set the default external 3-way diff/merge tool.")
    async def cmd_settings__set__merge_tool(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            tool_name: str = self.args.tool_name
            settings = await self.get_settings()
            settings.raw_data.merge_tool = tool_name
            settings.save()
            self.eprint(f"mergeTool set to {tool_name!r} in {settings.settings_file}")
        p = cmd.get_parser()
        p.add_argument("tool_name", type=str, metavar="TOOL-NAME",
                       help="Name of a known merge tool (see codingame_client.contribution_manager"
                            ".merge_tools.MERGE_TOOL_COMMANDS)--used whenever --tool isn't given "
                            "to `cg contribution diff`/`merge --interactive`.")
        return handler

    @cli_command("Delete a settings.json value.")
    async def cmd_settings__delete(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        return None  # No handler for the parent command; subcommands will be handled by their own handlers.

    @cli_command("Delete (unset) the default codingame-client credential profile name override.")
    async def cmd_settings__delete__default_profile(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            settings = await self.get_settings()
            settings.raw_data.default_profile = None
            settings.save()
            self.eprint(
                    f"defaultProfile unset in {settings.settings_file} "
                    f"(now falls back to config.yaml's defaultProfile, or \"default\")."
                )
        return handler

    @cli_command("Delete (unset) the default contribution working directory override.")
    async def cmd_settings__delete__contribution_dir(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            settings = await self.get_settings()
            settings.raw_data.contribution_dir = None
            settings.save()
            self.eprint(f"contributionDir unset in {settings.settings_file}.")
        return handler

    @cli_command("Delete (unset) the default external 3-way diff/merge tool override.")
    async def cmd_settings__delete__merge_tool(self, cmd: CliCommand[Self]) -> OptCmdFunc:
        async def handler() -> None:
            settings = await self.get_settings()
            settings.raw_data.merge_tool = None
            settings.save()
            self.eprint(f"mergeTool unset in {settings.settings_file}.")
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
        p.add_argument(
                "--config", "-c", default=None, metavar="PATH",
                help="Explicit config.yaml file, or a directory containing config/config.yaml. "
                     "Overrides the normal discovery search (see `cg config where`). Same as the "
                     "CG_CONFIG environment variable; this flag takes precedence if both are set.",
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
