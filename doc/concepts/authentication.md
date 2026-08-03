# Authentication

CodinGame has no API tokens, no OAuth, and no documented way for a program to authenticate. The web
site logs you in with a browser flow and hands back two cookies; every subsequent request is
authorised by those cookies and nothing else. So that is what this client uses.

## Credentials

A session is exactly two cookie values:

| | |
| --- | --- |
| `cgSession` | The session cookie itself. |
| `rememberMe` | The long-lived cookie that lets the session be re-established. |

They're stored per [profile](profiles.md), and they are the whole of your identity to the service —
treat the file holding them the way you'd treat an SSH private key. Anyone with those two values is
you, on CodinGame, until they expire.

There is no refresh endpoint to call and no expiry timestamp to inspect. Credentials are either
accepted or they aren't, so `cg` doesn't try to predict staleness: it uses what it has and reports
the failure if the server rejects it. `cg login --force` is how you replace them.

## Browser login (the default)

```bash
cg login
```

This opens a real browser window, lets you log in however you normally do — password, Google,
GitHub, whatever your account uses — and captures the resulting cookies. Driving a browser is not a
convenience here; it's the only approach that works across every sign-in method, including ones
involving a third-party identity provider or a CAPTCHA.

Useful flags:

- `--clean` forces a fresh browser profile and a full sign-in flow. Without it, existing browser
  session state is reused, so repeat logins for the same profile are usually automatic and
  non-interactive.
- `--timeout SECONDS` bounds the wait for you to finish (default 300).
- `--force` re-logs-in even when credentials already exist. Without it, `cg login` is a no-op when
  the profile already has credentials — note it does *not* check whether they still work.
- `--no-validate` skips the post-login check that the credentials are actually usable.

## Manual login

If you can't or don't want to run a browser — a headless server, a container, CI — extract the two
cookies yourself from a logged-in browser's dev tools and pass them in:

```bash
cg login --remember-me "$REMEMBER_ME" --cg-session "$CG_SESSION"
```

`--manual` is implied by either flag. This is the same credential material by a different route;
nothing downstream can tell the difference.

## Checking and clearing

```bash
cg whoami     # who am I, on this profile?
cg status     # the above plus profile details and points/rank stats -- always live, never cached
cg logout     # discard this profile's stored credentials
```

`cg status` deliberately has no offline mode, unlike `cg contribution status` and `cg puzzle status`
— reporting a possibly-stale login state would defeat its purpose.

## What needs a login and what doesn't

Most of the interesting surface needs one. A few things genuinely don't — some file downloads are
public, and the client is written to let the *server* decide rather than refusing up front.

The commands that are entirely local touch no credentials at all: `cg puzzle play` and
`cg contribution play` run your solution against downloaded test cases with no network access
whatsoever, as do `build`, `description`, `where`, and the merge machinery.
