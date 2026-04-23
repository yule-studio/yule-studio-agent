# Naver Category Policy

Planning Agent uses Naver CalDAV `category_color` values to adjust todo priority.

## How To Identify Codes

Run a sync first.

```bash
yule calendar sync --force-refresh
```

Then inspect the local state database.

```bash
yule calendar categories
yule calendar categories --json
```

Naver exposes category colors as numeric codes, not color names. Add confirmed codes to `naver-category-policy.json`.

## Policy Fields

- `label`: Human-readable category label.
- `priority_boost`: Score added to matching calendar todos.
- `reason`: Briefing reason shown in Planning output.
- `coding_candidate`: Whether matching todos can be passed to Coding Agent.
- `alert_policy`: Reminder strategy hint for later Discord notifications.

## Current Mapping

- `27`: 회사 업무

Other colors should be added only after checking their actual numeric code with `yule calendar categories`.
