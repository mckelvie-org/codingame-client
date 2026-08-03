# Services

Each service on `client.services` mirrors one of CodinGame's own service endpoints, with one method
per API call. Method names are snake_case versions of the wire names — `findContribution` becomes
`find_contribution`.

```python
async with CgClient() as client:
    session = await client.services.test_session.start_test_session(handle)
    print(session.current_question.question.title)
```

## The ones you'll actually use

| Service | Covers |
| --- | --- |
| `contribution` | Find, create, update and delete contributions; list pending ones; moderator vote state. |
| `puzzle` | Puzzle progress, resolving a puzzle to a test session, puzzle-of-the-week. |
| `test_session` | Solving: start a session, run a test (`play`), `submit`, per-language saved code. |
| `codingamer` | The logged-in user, profiles, points and ranking. |
| `report` | Results of a submission, once graded. |
| `vote` | The community up/down vote on a contribution — *not* the moderator approve/reject gate. |
| `search` | Find puzzles and users by name. |

Do not conflate the last two. `vote` is the ungated community vote; the moderator gate that decides
whether a contribution is published lives on `contribution.find_contribution_moderators` and takes a
numeric id, not a handle.

## The rest

`achievement`, `clash_of_code`, `clash_of_code_description`, `codingamer_puzzle_topic`,
`featured_event`, `intercom`, `last_activities`, `notification`, `programming_language`, `quest`,
`survey`, `test_session_question_submission`, `user` — mapped and typed, mostly used to round out
the protocol rather than because a workflow here needs them.

The full, always-current signature list is in the
[`cg api` reference](../cli/reference/api/index.md): the CLI exposes one subcommand per service
method, so that page is a faithful index of what exists.

## Helpers

Some endpoints need more than one call to use correctly. Those live on `.helper`:

```python
contribution = await client.services.contribution.helper.update_contribution(
        contribution_id, puzzle_type, data, draft, ready_for_moderation, prev_version,
        max_wait_seconds=600)
```

The helper layer adds retry and polling — notably surviving the HTTP 524 that a heavy
`updateContribution` provokes, where the origin usually committed the change anyway. It adds no data
normalization: text conversion belongs with the code that reads and writes files, not at the
transport layer.

`report.helper.find_report_by_submission_when_ready` is the other one worth knowing — grading is
usually done by the time `submit` returns, but not always.

## Docstrings are the reference

Each method's docstring records what it does, what raises, and — where it was established
empirically — what the endpoint actually does as opposed to what its name suggests. For example,
`test_session.get_previous_code_by_language_id` documents two things that are easy to assume wrongly
and were confirmed live: it's a pure read that does *not* switch the session's language, and a
language you've never attempted returns `None` rather than a generated stub.

That's the level of detail to expect, and it's why there's no separate hand-written method reference
to fall out of date.
