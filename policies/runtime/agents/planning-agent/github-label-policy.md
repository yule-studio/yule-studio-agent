# GitHub Label Policy

Planning Agent uses GitHub issue labels to adjust open-issue priority so that the recommended development order matches actual layering (foundation → feature → surface).

## How To Identify Labels

Run a sync first.

```bash
yule github issues --limit 30 --force-refresh --json
```

Each issue payload now includes a `labels` field. Add confirmed label names to `github-label-policy.json` with a `priority_boost` and a short `reason`.

## Policy Fields

- `priority_boost`: Score added to matching open issues. Positive boosts move the issue toward the top of the daily plan. Negative values push it down.
- `reason`: Briefing reason shown in Planning output.

When an issue has multiple matching labels, every matching boost is applied (sum) and every reason is appended.

## Default Mapping

The shipped defaults reflect a typical layered web project:

- `infrastructure`: +30 (foundation layer)
- `domain`: +25 (domain layer)
- `schema`: +25 (schema/migration)
- `auth`: +20 (auth foundation)
- `bug`: +25 (bug fix)
- `feature`: +10 (feature work)
- `chore`: -5 (chore)
- `docs`: -5 (documentation)
- `ui`: -10 (ui/surface)
- `design`: -10 (design/surface)

Override with `YULE_GITHUB_LABEL_POLICY_FILE` (path) or `YULE_GITHUB_LABEL_POLICY_JSON` (inline JSON).
