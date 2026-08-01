# CHANGELOG

## {{UNRELEASED}}

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
