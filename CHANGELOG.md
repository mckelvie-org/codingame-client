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
