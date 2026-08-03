# CHANGELOG

## {{UNRELEASED}}

- **Documentation.** Everything beyond `README.md`/`CONTRIBUTING.md` now lives under `doc/`: an
  overview, concepts (authentication, profiles, working directories, languages), workflow guides for
  puzzles/contributions/debugging, the programmatic client and managers, and design notes recording
  the decisions that aren't obvious from the code.

  The 148-command CLI reference is **generated from the parser** by `pdm run gen-docs` (one page per
  command group, one per API service endpoint) and committed, so it stays readable on GitHub and
  shows interface changes as reviewable diffs. Three tests keep it honest, all offline: the
  generated pages must match a fresh run, every hand-written `cg ...` must resolve against the real
  parser, and every relative link between pages must point at a file that exists. Command renames
  are the drift that actually happens here — `cg puzzle push` became `cg puzzle submit`, `revert`
  became `discard-local` — and each would otherwise have silently invalidated every guide mentioning
  it.

  `CHANGELOG.md` deliberately stays at the repo root: `bin/cut-rc` and `bin/cut-prod` rewrite and
  `git add` it by path.

  **README links now survive PyPI.** PyPI renders `README.md` as the project front page but resolves
  relative links against `pypi.org`, so every `[docs](doc/...)` would 404 there. `bin/cut-rc` and
  `bin/cut-prod` now rewrite them to absolute URLs pinned to the release tag, in the same throwaway
  worktree they already patch `pyproject.toml`/`README.md`/`CHANGELOG.md` in. `main` keeps ordinary
  relative links (checked by the test suite); the tagged commit the package is built from — the one
  PyPI displays — gets fully-qualified ones, pointing at the docs as they were for *that* version.
  A second, deliberately unpinned link to the moving `prod-latest` tag gives readers of an old
  version's page a route to current docs.

- **`outputs_match` no longer accepts output CodinGame rejects.** It previously normalized away
  per-line trailing whitespace, and (via `splitlines`) CRLF line endings — both of which the server
  treats as failures. That's the dangerous direction: a solution passed locally and then failed on
  submission. Its rule is now equivalence with the server's: everything compared exactly, except a
  difference of **one** trailing newline in either direction.

  Mapped live against `CgPlayResult.comparison.success` rather than guessed, across two puzzles
  (one whose stored expected output ends in a newline, one whose doesn't — the rule only falls out
  of seeing both):

  | actual, relative to the stored expected output | server |
  |---|---|
  | verbatim | pass |
  | ± one trailing newline | pass |
  | ± two trailing newlines | fail |
  | trailing whitespace added to every line | fail |
  | per-line trailing whitespace stripped | fail |
  | leading space added to every line | fail |
  | CRLF line endings | fail |
  | a leading blank line | fail |

  The one-newline allowance isn't optional: a test's expected output usually has no final newline
  (it was typed into a textarea) while every language's `print` supplies one. The tolerance is a
  *difference*, not a cap — `expected + "\n\n"` fails even when the expected value itself ends in a
  newline.

- **Fixed: the debugger fed contribution solutions one extra byte of stdin.** `cg contribution
  debug` bound the test-case file directly to stdin, while `cg contribution play` goes through
  `list_local_test_cases`, which decodes — so the terminator this client adds reached the solution
  only under the debugger, and the expected-output comparison ran against a window shifted by one
  newline. `run_debug_stdin` now takes `final_newline_added`, which the contribution wrapper passes
  and the puzzle wrapper deliberately doesn't (`.meta/tests/` holds byte-exact downloads).

  The same one-byte deviation existed on the attach-style (C++/gdbserver) path, which redirected the
  container's stdin straight from the test-case file. **Breaking, for `CgLanguage` implementors:**
  `start_debug_session` now takes `stdin_text: str` rather than `input_file: Path`, and the
  implementation materializes its own copy (`<meta_dir>/debug-stdin`) to redirect from. Redirecting
  from the caller's file cannot be made correct — the file is the *rendering* of a value for a
  contribution and the value itself for a puzzle — so the caller, which is the only party that knows
  which, now supplies the bytes. This also drops the old requirement that the input file live inside
  the working directory, along with the error path for when it didn't.

  Confirmed against the real thing: CodinGame's runner feeds stored test input **verbatim** and
  appends nothing — a probe reading `sys.stdin.buffer.read()` on a community puzzle whose stored
  input is the single unterminated byte `"7"` reported `bytes=1 repr=b'7'`. An unterminated final
  line of stdin is real, and solutions have to handle it. (It's a community-contribution
  phenomenon, incidentally: official CodinGame puzzles' test files are properly terminated.)

- **Fixed: `cg contribution` required a configured git identity, and said so obscurely.** Every
  command touching `.meta/`'s git repository failed with `Author identity unknown` for anyone who
  had never run `git config --global user.email` — and on CI, where a runner's hostname has no
  domain (`runner@fv-az123.(none)`), git's usual `user@host` auto-detection can't rescue it either.

  `git commit` now falls back to a synthetic `codingame-tools <codingame-tools@localhost>` identity
  **only when git can't resolve one of its own**, probed once per repository via `git var`. The
  conditional part matters: `-c` outranks every config file, so applying it unconditionally would
  stamp that name over the user's real one in the `git log` they read while resolving a merge
  conflict. `.meta/`'s commits are local scaffolding that is never pushed anywhere, so the identity
  on them carries no meaning — it just has to exist.

- Schema fixes for fields that are **omitted entirely** (not null) in real responses, all found by
  decoding the whole pending community-review queue rather than one report at a time:
  - `CgTopic` — only `label_map` is guaranteed. A topic can arrive as nothing but its localized
    label (e.g. `{"labelMap": {"2": "Logic Gates"}}`) with every catalogue field absent; `id`,
    `handle`, `category`, `puzzle_count` and `parent_topic_id` are now optional. Observed on 10 of
    80 topic objects.
  - `CgContribution.avatar` / `CgPersonalContribution.avatar` — now optional, for codingamers who
    never set an avatar (3 of 54 contributions). `CgPendingContribution` already allowed this;
    the three classes had simply drifted.
  - `CgLastActivityPuzzle.cover_binary_id` — now optional (absent for 7 of 30 puzzles from a single
    `Puzzle/findProgressByIds` call).

- New `cg contribution set-language LANGUAGE [--force]` — deliberately **stricter** than the puzzle
  equivalent, because a contribution stores exactly one solution with no per-language history.
  There is nothing to restore and nothing to switch back to: the existing solution is replaced by a
  starter stub, and the next `cg contribution push` overwrites the last durable copy. So it refuses
  unless `data/solution.src` is still exactly the stub cg generated (recorded in
  `.meta/solution-snapshot.json` by `create()` and by each switch). Notably, *matching what the
  server currently has* does **not** count as safe here — unlike `cg puzzle set-language`, where
  per-language recall makes switching reversible — since the server copy is precisely what the next
  push destroys. Purely local: no network call, as there's no per-language code to fetch.

  Only Python3 offers a create-stub that genuinely passes the seeded test cases, so switching to
  any other language leaves `data/solution.src` **empty** rather than writing a placeholder. That's
  required, not a shortfall: `updateContribution` skips solution validation entirely when
  `solutionSource` is null, but validates any non-null one against every test case — and `create()`
  seeds a real test/validator pair. Python3's stub echoes its input specifically so it passes them;
  a comment-only placeholder for another language would be non-null, fail validation, and block
  `push()`.

- **Fixed: local text no longer erodes a newline on every fetch/push cycle.** Server-side text and
  the local files holding it are now converted through one place, `codingame_tools.common.
  text_files`, unconditionally in both directions — append a terminator on the way in (unless the
  value is zero-length), strip up to one on the way out. That makes the pair exact inverses, so an
  untouched import-then-push submits byte-identical text.

  Previously the terminator was appended only when missing, which cannot be inverted: the reader
  can't tell whether the newline it sees belonged to the content or to the writer. Composed with the
  strip applied at submission, any value that genuinely ended in a newline lost one per cycle, with
  no user edit, until it ran out. Surveying the pending community-review queue and published
  community puzzles (1686 real values) shows why that mattered more than its 0.8% rate suggests:
  the trailing-newline habit is per-*author*, so this eroded **every** test case of roughly 1 in 12
  contributions, not the occasional stray one. All 1686 now round trip exactly, and keep doing so
  across repeated cycles.

  **Breaking, for `cg api` callers:** `strip_test_final_eols` is gone from
  `CgContributionServiceHelper.update_contribution`/`create_contribution`, along with the
  `--no-strip-test-final-eols` flags on `cg api helper contribution update-contribution`/
  `create-contribution`. The service layer no longer rewrites submitted data at all — normalization
  belongs with the file conversion, not half of it at the transport layer. Callers building a
  `CgContributionData` by hand now control their own text exactly.

  Puzzle test cases under `.meta/tests/` are deliberately untouched by this: they're byte-exact
  `fileservlet` downloads, read-only and never pushed, so the bytes on disk are already the bytes
  CodinGame feeds a solution's stdin remotely. A contribution's test cases need the conversion for
  the opposite reason — there the server holds a *string* and the file is this client's rendering
  of it.

- An **empty `data/solution.src` now means "no reference solution"** and is pushed as a null
  `solutionSource` — anything that decodes to the empty string, i.e. a zero-length file or one
  holding just a terminator. That second case is the single point where the conversion above isn't
  injective, and it lands usefully here: an editor with "insert final newline" enabled can't quietly
  turn "no reference solution" into a one-blank-line program. Nothing weaker qualifies — a
  whitespace-only file stays a real (broken) program that the server will reject rather than being
  silently reinterpreted as no solution. This
  replaces deleting the file: `create()` and `set-language` now always leave a `solution.src`
  present, so the `solution.<ext>` symlink resolves instead of dangling and there's a file to type
  into straight away. It conflates a server-side solution that is genuinely the empty string with a
  null one — accepted deliberately, since an empty program passes no test cases and so could never
  have been an accepted solution.

- **You can now switch a puzzle's language, and get your own saved code back.** CodinGame keeps
  your most recent source *per language* for a puzzle, not just one; a previously-unknown API
  (`TestSession/getPreviousCodeByLanguageId`, now wrapped as
  `CgTestSessionService.get_previous_code_by_language_id` and `cg api test-session
  get-previous-code-by-language-id`) reaches the languages the session isn't currently on.

  New `cg puzzle set-language LANGUAGE [--force]` switches `data/solution.src`,
  `data/puzzle-data.json` and the `solution.<ext>` symlink, seeding the file with whatever you'd
  previously written in that language — a placeholder only when you've genuinely never used it
  there. It refuses when the current file holds work the server doesn't have (switching would
  discard it); `--force` overrides.

  "Has the user edited this?" is answered from a **recorded snapshot** of what cg last wrote
  (`.meta/solution-snapshot.json`, written by every path that touches `solution.src`), not by
  regenerating a placeholder and comparing. Regeneration would break silently the moment
  placeholder output stopped being byte-identical across releases — a template tweak or an embedded
  timestamp would be enough — and an untouched working directory would start claiming unsaved
  changes. A missing snapshot (fresh clone, or a directory from an older version) falls back to
  comparing against the server, which errs toward refusing rather than discarding. Comparisons
  ignore a trailing newline, which the server's copy routinely differs by.

  `cg puzzle import --language` changes meaning to match: it now *switches to* that language
  (restoring saved code for it) instead of being silently ignored whenever any answer existed.
  Omit it to get whichever language you last used, as before. `import --language X` is now exactly
  `import` followed by `set-language X`, sharing one code path.

  Two API semantics confirmed live and documented, since both are easy to assume wrongly: fetching
  code for a language is a **pure read** that does *not* make it the session's current language
  (only running a test or submitting does), and a language you've never attempted returns **null**
  rather than a generated stub.

- Fix: **official CodinGame puzzles couldn't be imported at all.** A puzzle the site provides
  itself was never a community contribution, so `TestSession/startTestSession` omits `contributor`
  and `contribution` **entirely** (not null) — and both were required fields, so `cg puzzle import
  Temperatures` failed to parse the response outright. The same omission broke
  `LastActivities/getLastActivities` via `CgLastActivityPuzzle.contributor`, which is what
  `communityCreation: false` marks. All three are now optional. A puzzle's `contributionType` is
  consequently unknowable for an official puzzle, so `import_` treats its absence as a standard
  in/out puzzle and records `puzzleType: null` rather than refusing — failing closed there would
  have blocked every official puzzle on the site. A type that *is* present and unsupported is still
  rejected as before.

- Containers are now strictly **one per working directory**. Container names are per-language, so
  changing a working directory's `solution_language` previously orphaned the old language's
  container--still running, still bind-mounted, never referenced again. Creating a container now
  sweeps away any other one bound to the same directory first, and `cg puzzle delete` /
  `cg contribution delete` already removed theirs (matched by label, so every language's is caught).
  Toolchain state is decided entirely from labels read back off Docker (`cg.root`/`cg.spec` on
  containers, `cg.managed` on images) rather than from any cache beside them, so removing a
  container or image out-of-band--`docker rm`, Docker Desktop, `cg docker clean`--just works and cg
  rebuilds on the next command. Speed comes from asking once instead of remembering: the common
  path is a single `docker ps` that answers existence, spec match, running state, and strays
  together, and a container that passes vouches for its image still existing. `cg puzzle play` over
  20 C++ test cases went from 2.6s to 1.7s.

- New `cg docker clean`: remove every container and image cg created, across all working
  directories. Deliberately never prompts and has no `--force`--a container holds nothing but build
  artifacts and an image is rebuilt from Dockerfiles on disk, so there is no user work in either and
  the next build recreates whatever is needed. Useful for reclaiming disk space or forcing a clean
  rebuild. Images are now labelled `cg.managed` when built, so they're identified by label rather
  than guessed from tag names (an unrelated image that happens to be called `cg-*` is never
  touched); containers are found by the `cg.root` label they already carry, which also catches ones
  for working directories that no longer exist.

- **Real C++ debugging in VS Code, with no local toolchain and no local debugger.** `cg puzzle
  vscode` now generates a `cppdbg` configuration that breaks at the first statement, binds
  breakpoints to the file you actually have open, and feeds the solution a test case's input on
  stdin. The host needs nothing but Docker.

  Both `gdbserver` and `gdb` run inside the container--VS Code reaches gdb through `pipeTransport`
  shelling out to `docker exec`, and gdb then dials the container's own localhost, so no port is
  published. Feeding stdin from a file is why a debug session is set up by `cg puzzle debug start`
  rather than left to the debug adapter: doing the redirection in a shell we control sidesteps
  cppdbg's stdin handling entirely. The debug profile compiles the `solution.<ext>` symlink
  specifically so the path recorded in the debug info maps back to the file in your editor, and
  `sourceFileMap` uses an absolute host path because the workspace root is usually a *parent* of the
  working directory. A `devcontainer.json` is generated too, for IntelliSense over the container's
  headers--optional, and not on the run/debug path.

  New: `cg puzzle debug start|stop` and `cg contribution debug start|stop` (normally invoked by the
  generated tasks, not by hand). Containers now run with `--init` and the ptrace allowances gdb
  needs; the drift check that decides whether to reuse a container covers all creation flags, not
  just the image, so changes like these recreate it automatically.

- **C++ solutions now build and run, entirely inside Docker--no local toolchain required.** The
  first non-Python language to go beyond a file extension. `cg puzzle play` / `cg contribution play`
  work on a C++ solution exactly as they do on a Python one, and `cg puzzle build` /
  `cg contribution build` compile without running.

  How it works: one long-lived container per (working directory x language), with the working
  directory bind-mounted **read-only** at `/src` and build artifacts living at `/build/` inside the
  container--so the solution source stays the only durable state outside it. Rebuilds are skipped
  when the source is unchanged (hashing the source file alone, never a tree, since `/src` contains a
  contribution's whole git object database); failed builds are cached too, so a repeat replays the
  same diagnostics instantly rather than recompiling. Runs enforce their timeout *inside* the
  container, because killing the local `docker exec` client doesn't stop the process in it, and
  force unbuffered output so a C++ solution streams progressively like Python3 does.

  The toolchain image is defined by two files under `<cg data dir>/docker/<lang>/`: a cg-owned
  `base.dockerfile` carrying a template version, and a `custom.dockerfile` that is **yours, appended
  verbatim, and never touched by cg**. That split is what makes upgrades safe--adding a library is
  purely additive, so cg can ship a new base without ever needing to merge with your edits (an
  unmodified stale base upgrades silently; an edited one is left alone with a warning). Image tags
  are content-addressed, so any change to either file rebuilds automatically, and a per-working-
  directory `.meta/docker/<lang>/` overrides the global files when one puzzle needs something
  different.

  Deleting a working directory now also removes its containers--orphaning one would matter, not just
  be untidy, since container names derive from the directory path and a future working directory at
  the same path would otherwise silently attach to the stale container and its stale artifacts.
  (`CgPuzzleManager.delete()` is `async` as a result.)

  Docker-requiring tests are marked `docker` and excluded by default; run them with
  `pdm run pytest -m docker`.

- New `cg puzzle vscode` / `cg contribution vscode`: generate this working directory's VS Code
  run/debug configuration instead of hand-maintaining it. The test-case dropdown is built from the
  test cases actually on disk, so it can't go stale--the hand-written configuration this replaces
  carried a note telling you to regenerate its 25-entry list by hand after every `cg puzzle import`.
  Languages describe what they need via the new `CgLanguage.build_vscode_provisioning`; where it
  goes and how it merges is `codingame_tools.language.vscode`'s job. Three things worth knowing:
  configuration is written to the **workspace root**'s `.vscode/` (VS Code never reads `launch.json`
  from a subdirectory, and a working directory is usually a subdirectory of the real workspace),
  with `--workspace-dir` to override; re-running replaces only the entries owned by that working
  directory, so your own configurations and other working directories' configurations survive; and
  since `launch.json` is really JSONC, a file with comments is **refused rather than rewritten**
  (`--force` overrides). This repo's own `.vscode/launch.json` is now generated.

- Groundwork for Docker-backed language toolchains: building a solution is now an explicit step
  separate from running it. `CgLanguage` gains `build()` (returning a `CgBuildResult`--never
  raising, since a compile error is a routine outcome to display, not a crash) and takes a new
  `CgLanguageContext` (working-directory root, solution file, `solution.<ext>` symlink, meta dir,
  toolchain dir) in place of a bare solution path. Both managers gain `language_context()` and
  `build_solution()`; `play_local()`/`run_local_tests()` build once before looping, while
  `play_local_one()`/`run_local_test()` deliberately do not build. `cg puzzle play` and
  `cg contribution play` build up front and report a build failure as such, instead of letting a
  compile error surface once per test case (or, for `cg puzzle play`, as a traceback), and both
  gain `--timeout` / `--build-timeout` (the build budget is far more generous, since a cold build
  may pull a container image and compile from scratch). No behavior change for Python3, which needs
  no build. `CgContributionManager` also gains a public, never-raising `meta_dir` property--unlike
  `git_dir`, it works on a directory that was never imported, which `language_context()` requires.

- New `codingame_tools.language` package: centralizes all per-language behavior (local execution,
  file extension, comment syntax, contribution-create starter stub) behind a single `CgLanguage`
  abstract interface, discovered by walking `language/languages/`'s flat modules at load time
  (`get_language()`/`get_language_by_extension()`/`list_language_cg_ids()`). Every
  CodinGame-supported language has its own real module (27 total, one file each--e.g.
  `languages/python3.py`, `languages/java.py`)--`Python3` is the only one with local
  execution/stub generation implemented so far; the other 26 currently implement only
  `extension`. `CgDefaultLanguage` is now a pure catch-all, used only for a `cg_id` CodinGame
  might add in the future that this client has never seen.

  Local execution is now actually async local execution, not just command-building:
  `CgLanguage.run_streaming()` runs a solution as a subprocess and yields its stdout/stderr
  progressively, chunk by chunk, as they're produced (tagged by stream--stdout and stderr are
  two independent, separately-buffered OS pipes, and this deliberately doesn't attempt to
  guarantee "correct" interleaving between them, only real-time delivery of each); `run()` is a
  convenience wrapper for a caller that just wants the final aggregated result. Contribution
  starter-stub generation (`build_contribution_create_stub_source()`) is likewise now an async
  method a plugin builds, not a static property.

  Replaces `test_runner.runner`'s `run_solution_locally`/`CgLocalRunResult`/
  `CgLocalRunUnsupportedLanguageError` (both managers' single-test methods are now `async def`
  and call `codingame_tools.language` directly; `CgLanguageOperationNotSupportedError` propagates
  with no manager-specific translation wrapper) and `client.common.protocol.schema`'s
  `cg_extension_to_solution_language`/`cg_solution_language_to_extension` (removed outright).
  Fixes a bug along the way: `cg puzzle import`'s placeholder stub for a puzzle with no existing
  answer used to emit an unconditional `# TODO: ...` line regardless of language, which is
  invalid syntax for any language whose single-line comments aren't `#`-prefixed--it now uses the
  language's own comment syntax where known, or an empty file otherwise, rather than guessing
  wrong.

- Fix `cg puzzle play` (the local one) missing the final `N/M passed` summary line that `cg
  puzzle play-server` already had--lost when it was restructured to stream results one at a time.
  Also added the same summary line to `cg contribution play`, which never had one.

- `cg puzzle play` (the local one) gets the same streaming treatment as `cg puzzle play-server`:
  displays each test's result as it finishes instead of running the whole batch first.
  `CgPuzzleManager.play_local()` is split the same way `play()` was: `resolve_play_local_test_cases()`
  (sync, resolves the given/default test case list) and `play_local_one()` (runs a single
  downloaded test case, never raising just because it failed)--`play_local()` itself is now just
  a loop over those two, kept as a convenience for callers that want the whole batch (and still
  raises `CgPuzzleLocalTestFailedError` if any failed, as before). `cg contribution play` already
  worked this way (it was never restructured to batch-collect-then-display), so no change was
  needed there.

- `cg puzzle play-server` now displays each test's result as soon as it's available, instead of
  running every requested test first and only then printing anything--a multi-test run no longer
  looks stalled while the server works through earlier tests. `CgPuzzleManager.play()`'s single
  batch call is split into two pieces a caller can use directly for this: `resolve_play_indices()`
  (sync, resolves the given/default index list, no network) and `play_one()` (one `TestSession/
  play` call for a single index)--`play()` itself is now just `[await play_one(i) for i in
  resolve_play_indices(...)]`, kept as a convenience for callers that do want the whole batch.

- **Breaking**: renamed CLI play commands for consistency--the entirely-local, no-network variant
  is now plain `play` in both working-directory types, freeing up the old `play`/`play-local`
  names' asymmetry:
  - `cg puzzle play-local` -> `cg puzzle play`
  - `cg puzzle play` (the real server-side `TestSession/play` call) -> `cg puzzle play-server`
  - `cg contribution play-local` -> `cg contribution play` (unchanged behavior/output--
    contribution has no server-side "play" equivalent, so no swap was needed there)

- `cg contribution play-local`'s output now matches `cg puzzle play-local`'s format: a single
  colored `[PASS]`/`[FAIL] ordinal side: title` line per test (folding in the ordinal/side/title
  that used to be a separate `=== ... ===` announcement before each run), printed as each test
  finishes rather than deferred to a separate `=== Summary ===` section at the end (removed). On
  failure, shows a diff (via the same `show_diff` helper, instead of an unconditional raw dump)
  for a genuine output mismatch, or the exception/timeout/crash reason otherwise, then `---
  stderr ---` (also now colored) if there's any. `--show-stdout`/`--update-expected` still print
  the raw captured output as before.
- `cg puzzle play-local` now accepts one or more 1-based TEST-INDEX arguments (previously just
  one, or none for "all downloaded")--matching `cg puzzle play`'s already-normalized argument
  style. `CgPuzzleManager.play_local()`'s signature changed to match: `test_indices: list[int] |
  None = None`, run in the order given.

- Fix `cg puzzle play`/`play-local` and `cg contribution play-local` running captured stdout
  straight into whatever gets printed next (the following test's `[PASS]`/`[FAIL]` header, or the
  shell prompt) when the program under test didn't itself end its output with a newline--`print(
  ..., end="")` preserved the output byte-for-byte but assumed it already ended in `\n`, which
  isn't guaranteed. New `_print_captured_output()` helper prints the captured text verbatim and
  then guarantees exactly one trailing newline regardless.

- `cg puzzle play`, `cg puzzle play-local`, and `cg contribution play-local` no longer dump a
  passing test's captured stdout by default--only a failing (or errored) test's output is shown,
  same as before. Pass `--show-stdout` to always print it regardless of pass/fail.
  `cg contribution play-local --update-expected` implies `--show-stdout` (the point of that flag
  is to review the new output being accepted as the baseline).
- `cg puzzle play`'s output now matches `cg puzzle play-local`'s format: `[PASS]`/`[FAIL] test N
  (label)` per test (bold blue, like the section headers below it) instead of the old `--- test N
  ---`/`success: True`/`expected:`/`found:` lines. On failure, shows a unified diff (via the same
  `show_diff` play-local uses) when the server's comparison data has both `expected`/`found`, then
  the raw combined output under a `--- output ---` header (bold blue)--the closest remote analog
  to play-local's `--- stderr ---` section. `cg puzzle play-local`'s own `[PASS]`/`[FAIL]`/
  `--- stderr ---` lines are now colored the same way (previously plain).

- **Breaking**: collapsed the never-built sync/async client split. `codingame_tools.client.sync`
  (an empty placeholder) is deleted; `codingame_tools.client.async_` is flattened up to
  `codingame_tools.client` (e.g. `codingame_tools.client.async_.client` -> `codingame_tools.
  client.client`, `...async_.service...` -> `...client.service...`); every `CgAsync*` class drops
  the `Async` infix (`CgAsyncClient` -> `CgClient`, `CgAsyncRawClient` -> `CgRawClient`,
  `CgAsyncContributionService` -> `CgContributionService`, etc.--51 classes total across the raw
  client, the top-level facade, all 19 service/service-helper pairs, and both servlet/
  servlet-helper pairs). `CgRawClient`/`CgClientHttpError` (previously abstract-ish bases in
  `client/common/raw_client.py`, split from their concrete `CgAsync*` counterparts purely to leave
  room for a future sync HTTP backend) are merged into single concrete classes--`set_cookie` is no
  longer `abstractmethod`. Also fixes a pre-existing gap where `client/service/services/__init__.py`
  never imported/exported the `vote` service pair. No behavior change otherwise; every consumer
  (CLI, contribution/puzzle managers, tests) updated to the new names/paths.

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
