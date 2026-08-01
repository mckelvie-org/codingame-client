# CHANGELOG

## {{UNRELEASED}}

- Fix `cg puzzle submit` crashing on a puzzle with no prior submission: `CgSubmissionReport.
  best_score` was assumed always-present (based on one earlier partial-report example) but
  confirmed live absent too when there's no historical "best" yet--now Optional like every other
  field except `validator_shareable`, the only one confirmed present in every case seen so far.
  Also fixes a real `dataclass_wizard` CatchAll mis-binding introduced by that same edit
  (`extra_data` wasn't the first defaulted field, corrupting `best_score` into `{}` instead of
  `None`)--see this project's established "extra_data must be first among defaulted fields" rule.
- Rename `cg puzzle push` to `cg puzzle submit` (`CgPuzzleManager.push()` -> `.submit()`), unlike
  `cg contribution push`'s git vocabulary--confirmed live (2026-08-01) that a puzzle working
  directory has two independent server-side persistence phases, not one: the test session's
  current answer (durably updated by *any* `TestSession/play` call, not just a real submission--
  see below) and this method's actual graded submission via `TestSession/submit`. "Push" would
  ambiguously suggest either; "submit" (matching the underlying API method's own name) is
  unambiguous.
- Document (in `CgPuzzleManager.play()`'s docstring) a confirmed-live side effect of
  `TestSession/play`: the server durably persists whatever code was sent as the test session's
  current answer--the same answer visible in the web IDE from any browser--even though `play()`
  itself is not a grading/submission event. There's no separate "just save" API; running at
  least one test case is, in effect, this project's puzzle-working-directory autosave.
- Fix `cg config init`'s freshly-created project-local `config.yaml` showing an absolute
  `#dataDir:` example (resolved for the specific `--at` directory at creation time)--if the
  project directory is later renamed or moved, that absolute path would silently stop matching
  the real default. Now shows the literal relative `"../data"` instead, which keeps meaning "the
  sibling data dir next to wherever this config file actually lives" regardless. `--global` is
  unaffected--still shows the actual resolved absolute path, since there's no comparable sibling
  relationship to express relatively for the global (per-user) location. `default_config_template()`
  now takes the example value as a plain string rather than a `Path`, so the caller can pass
  either form.
- Fix `cg config dump` (and `default_profile`/`contribution_dir`/`puzzle_dir` resolution
  generally) silently masking the global (per-user) `config.yaml` whenever a project-local one
  existed, even if the project file never mentioned the field in question--previously
  `resolve_config()`'s single-file "first found wins" discovery meant a project config missing
  `defaultProfile` entirely still shadowed the global file's `defaultProfile`, discarding it. Fix:
  `CgConfigData` gains a `settings` sub-object (`CgConfigData.settings`), identical in shape to
  settings.json's own `CgSettingsData` (`defaultProfile`/`contributionDir`/`puzzleDir`), resolved
  field-by-field, base to most refined: the global config file's `settings`, then a project
  config file's own `settings` (if a different one resolved), then settings.json itself. Config
  files remain hand-edited only (no `cg config set`--only `cg settings set` exists, and only ever
  touches settings.json). `CgConfigData`'s old top-level `default_profile` field is removed
  (moved into `settings.defaultProfile`)--an existing config.yaml using the old top-level key
  needs a one-time manual edit to nest it under `settings:` (`cg config dump`/`cg config where`
  won't do this automatically; the field just silently stops being read otherwise, landing in
  `extra_data` instead). `CgConfig` gains `.settings`/`.contribution_dir`/`.puzzle_dir` alongside
  the existing `.default_profile`. `cg config dump`'s output nests `defaultProfile`/
  `contributionDir`/`puzzleDir` under a `"settings"` key (mirroring `CgConfigData.settings`'s own
  shape) rather than flattening them onto the config object directly--only `dataDir` (which isn't
  part of the merge--see below) stays top-level alongside `configFile`/`rawConfig`.
  `contribution_dir`/`puzzle_dir` previously had no config.yaml-level fallback at all (settings.json
  or nothing)--they now participate in the same 3-tier chain as
  `default_profile`.
- Fix `contribution_dir`/`puzzle_dir` (settings.json and config.yaml's `settings` alike) resolving
  a relative value against the *current working directory at read time* instead of a fixed base--
  meaning the effective directory silently moved around depending on where `cg` happened to be run
  from. `cg settings set contribution-dir`/`puzzle-dir` now converts whatever path was typed
  (resolved against cwd *at set time*, the natural way to type a path at the CLI) into one stored
  relative to settings.json's own directory (`CgSettings.settings_file.parent`, i.e. `data_dir`);
  absolute input is stored as-is. Reading back (`CgSettings.contribution_dir`/`puzzle_dir`,
  `CgConfig.contribution_dir`/`puzzle_dir`) now resolves a relative value against that same
  `data_dir`, never cwd. New `codingame_tools.settings.resolve_settings_dir`/
  `relativize_settings_dir` implement this pair. The real project `.cg/data/settings.json` here
  had old-style values (`"contribution"`/`"puzzle"`, implicitly relative to the project root) that
  would have started resolving to `.cg/data/contribution`/`.cg/data/puzzle` under the new rule--
  re-set via `cg settings set contribution-dir ./contribution`/`puzzle-dir ./puzzle` to fix (now
  stored as `"../../contribution"`/`"../../puzzle"`, correctly relative to `.cg/data`).
- Add `cg contribution status`: a human-friendly summary of a contribution's submission,
  review/approval, and server-sync status (`--refresh` to fetch fresh first, top-level `--json`
  for machine-readable output).
- Add the `Vote` service (`client.services.vote.find_votable_values_by_id`, `cg api vote
  find-votable-values-by-id`): CodinGame's generic community up/down-vote tally for a votable
  (e.g. a contribution's `votableId`).
- Add `Contribution/findContributionModerators` (`client.services.contribution.
  find_contribution_moderators`, `cg api contribution find-contribution-moderators`): the
  privileged moderator approve/reject gate that actually decides a PENDING contribution's
  outcome (3 `"validate"`/`"deny"` votes either way)--distinct from the ungated community vote
  above. `cg contribution status` now shows it (`Approvals`/`Rejections`, with named moderators).
- Add `.meta/contribution-status.json` (`CgContributionStatusCache`): an offline cache of every
  piece of server metadata that isn't tied to a content version (score/votes/comment count/
  views/moderator approve-reject tallies/etc.), refreshed unconditionally by
  `CgContributionManager.fetch()`/`import_()`/`repair()` on every real `findContribution` call
  (even when the content version hasn't changed, since none of this is tied to it)--not
  git-tracked. `cg contribution status` reads it by default (no network access); `--refresh`
  forces a fetch first, which also updates the cache for next time.
- Add `Contribution/getPersonalContributions` (`client.services.contribution.
  get_personal_contributions`, `cg api contribution get-personal-contributions`): every
  contribution (any status) authored by a codingamer--unlike `get_all_pending_contributions`,
  genuinely filtered to just that codingamer's own.
- Add `cg contributions`: a one-line-per-contribution listing (handle/id/status/type/title) of
  all pending contributions community-wide by default, or just your own with `--personal`;
  top-level `--json` for the raw underlying list.
- Add `cg puzzle status`: a human-friendly summary of a puzzle working directory (title, pretty
  id, puzzle type, difficulty, language, local-edit status vs. the server's last-submitted
  answer). By default entirely local (no network access, unlike `cg contribution status` there
  is no local cache to refresh either); `--refresh` also checks for local edits and fetches live
  progress/score (level/solved/score/solved-by/attempts/XP/last activity). Top-level `--json`
  for machine-readable output.
- Add `puzzle_type`/`difficulty` to `.meta/puzzle-server-data.json` (cached at `import_()`/
  `repair()` time, alongside `title`/`puzzle_pretty_id`)--`None` for a cache written by an older
  version until the next `cg puzzle repair`. Add `difficulty` to `cg contribution status` too
  (`local_difficulty`, from `data/contribution-data.json`, same as `puzzle_type`/language).
- Add `cg status`: a session-wide summary (login status, profile, points/rank stats, achievement
  count)--always hits the network (no cached/local mode, unlike the other `status` commands).
  Top-level `--json` for machine-readable output (`rankHistory`--thousands of dated snapshots--
  trimmed out, not appropriate for a status summary). Points/rank/per-category numbers are
  grouped under one "Gamer stats" label (informational only, not a breakdown of one
  another--rationale lives in `CgCodingamePointsRankingDto`'s docstring, not printed every run).
  `XP` shows progress toward the next level (e.g. `34019   (1855/2250 to level 37)`), derived
  from the already-fetched per-level `xp_thresholds` table--no separate formula/lookup needed.
- Correct `CgCodingamePointsRankingDto`/`CgCodingamePointsStats` docstrings: two previously
  documented "duplicate"/"sum of categories" relationships between `codingamer_points`,
  `codingame_points_total`, and the seven `codingame_points_*` category fields are disproven by
  live data (e.g. category fields summed to 43469 against a `codingame_points_total` of 2800).
- Add `cg puzzle delete`: removes the local puzzle working directory only--there is no
  server-side counterpart, since a puzzle already exists on the server before you can solve it.
  Destructive--prompts for confirmation unless `--force` is given; requires `--force` outright
  if stdin/stdout aren't a terminal (same pattern as `cg contribution delete`).
- `cg puzzle import` now accepts a general puzzle reference instead of requiring an exact pretty
  ID--tries, in order: a numeric puzzle ID, an exact pretty ID, an exact-matching title, a
  case-insensitive-matching title (the latter two via `Search/search`). `CgPuzzleManager.
  import_()`'s parameter is renamed `puzzle_ref` to match.
- Fix `cg puzzle import` crashing on puzzles whose TestSession has no recorded submission yet
  (found live via the new title-search path): `CgLastActivityContributor.pseudo`,
  `CgTestSessionQuestion.last_submission_id`, `CgTestSessionQuestionSummary.score` are now all
  correctly Optional (each confirmed live to be entirely absent, not just `null`, in that case),
  and `CgTestSessionAnswer`'s `code`/`programming_language_id` are Optional too--`answer` itself
  can be present as an empty placeholder object rather than `null`/absent when nothing's been
  submitted, which `puzzle_manager` now checks for correctly instead of mistaking it for a real
  saved answer.
- Add `cg puzzle description`: renders the cached `.meta/statement.html` (no network access) as
  readable text--section headers and the Example's input/output test data are color-highlighted
  when writing to a real terminal (auto-detected, via `rich`), plain elsewhere (piped/redirected
  output, or `--json`, which emits the parsed `[{kind, text}, ...]` blocks instead). New
  `codingame_tools.puzzle_manager.statement_render` module (`parse_statement_html`,
  `CgStatementBlock`)--a small purpose-built parser for CodinGame's specific statement HTML
  shape (confirmed live), not a general HTML-to-text converter.
- `cg puzzle play` now runs every downloaded test case (`.meta/tests/`) by default instead of
  just test 1, or one or more explicit 1-based test indices given as positional arguments (e.g.
  `cg puzzle play 2 4`--need not be locally downloaded, the server runs by index alone). Exits 1
  if any run errored or didn't match the expected output. `CgPuzzleManager.play()`'s signature
  changed to match: `test_indices: list[int] | None = None`, returning
  `list[CgPuzzleRemoteTestResult]` (index/label/result) instead of a single `CgPlayResult`.
- `cg puzzle push` now calls `Report/findReportBySubmission` right after submitting and prints a
  summary (score/best score, achievements-completed, per-validator pass/fail), instead of just
  the bare new submission ID. `CgPuzzleManager.push()`'s return type changed to match:
  `CgSubmissionReport` (also now re-exported from `codingame_tools.puzzle_manager`) instead of
  `int`--its `.submission_id` is the same numeric ID `TestSession/submit` itself returns. `--json`
  prints the raw report.
- Fix `cg puzzle push` crashing on a fresh submission: confirmed live that
  `findReportBySubmission` called immediately after `TestSession/submit` can race server-side
  grading--every `CgSubmissionReport` field but `best_score`/`validator_shareable` was entirely
  absent in one observed case, not just `null`. Those fields are now all Optional, with a new
  `CgSubmissionReport.is_ready()` and `CgAsyncReportServiceHelper.find_report_by_submission_when_ready`
  (`client.services.report.helper...`)--polls every 3s, up to 60s by default--that `push()` now
  uses instead of the plain `find_report_by_submission`. `find_report_by_submission_when_ready`
  also takes an optional async `on_poll` callback, awaited with each not-yet-ready report--
  currently no real progress info to report (the API gives no partial/percentage signal we've
  found), but it doubles as a cancellation hook: raise from it (or from an `await` inside it) to
  abort the wait before `max_wait_seconds`.
- `CgAsyncContributionServiceHelper.update_contribution`'s existing HTTP-524 retry/polling (for
  contributions whose test-suite re-validation is slow enough that Cloudflare's edge disconnects
  the request) gets the same `on_poll` pattern: an optional async callback awaited with each
  still-stale `CgContribution` observed while polling `find_contribution` after a 524--unlike the
  Report helper's, this one always carries real (if stale) data. Never called if no 524 occurs;
  same cancellation-hook behavior (raise to abort early).
