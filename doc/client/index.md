# The programmatic client

`CgClient` is an async, fully typed wrapper over CodinGame's private web API. Every request and
response is a dataclass; every endpoint the project knows about is a method with a docstring saying
what it does and, where relevant, what was confirmed live rather than assumed.

```python
import asyncio
from codingame_tools.client import CgClient

async def main() -> None:
    async with CgClient() as client:
        pending = await client.services.contribution.get_all_pending_contributions()
        for c in pending[:5]:
            print(c.public_handle, c.title)

asyncio.run(main())
```

## Authentication

The client reuses the same credentials and [profiles](../concepts/profiles.md) the CLI does, so a
`cg login` in your shell is all a script needs:

```python
async with CgClient() as client:            # default profile
    ...

async with CgClient(profile="dev") as client:
    ...
```

Credentials are resolved best-effort at first use — available ones are applied, and nothing raises
just because there aren't any. That's deliberate: some endpoints are public, so the *server* gets to
decide rather than the client refusing up front. Methods that genuinely require a login raise
`CgAuthenticationError`.

There is no synchronous client and none is planned. Everything is `async`.

## Layout

```
client.services.<service>.<method>()      typed endpoint wrappers
client.services.<service>.helper.<...>    retries, polling, multi-call workflows
client.servlets.file_servlet(...)         file download
client.servlets.file_upload(...)          file upload
```

- **[Services](services.md)** — what each of the 22 service endpoints covers.
- **[Files](files.md)** — uploading and downloading binary content.

## Errors

| | |
| --- | --- |
| `CgAuthenticationError` | Not logged in, and couldn't implicitly log in. |
| `CgClientHttpError` | Transport failure, non-2xx status, or an undecodable response. Carries `status_code`. |

`CgClientHttpError.status_code == 524` deserves special mention: CodinGame's CDN cuts off requests
that take too long at the origin, and for heavy contribution updates the operation often *succeeded*
anyway. The helper layer handles this by polling until the version increments rather than
propagating the error. If you call the plain service method yourself, you own that problem.

## Schemas and unknown fields

Every response is parsed into a dataclass. Fields the client doesn't know about are captured in
`extra_data` rather than being dropped or raising — the API is undocumented and changes without
notice, so tolerating additions is the only workable stance.

The reverse isn't tolerated: a field the client believes is required, which the server then omits,
is a hard error naming the field. That's intentional. It surfaces protocol drift as a clear message
instead of a `None` propagating somewhere strange, and those reports are how most of the schema has
been corrected. If you hit one, it's a bug worth filing — usually a one-line fix making the field
optional.

## Raw requests

For an endpoint the client doesn't wrap yet:

```python
raw = await client.services.contribution.service_request("findContribution", [handle, True])
```

Returns parsed JSON with no schema applied. The CLI equivalent is `cg raw-api`, and it's how new
endpoints get mapped before they're wrapped.
