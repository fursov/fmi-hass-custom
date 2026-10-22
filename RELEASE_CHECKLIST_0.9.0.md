# FMI v0.9.0 — release checklist

**Status:** release candidate only. **Do not create or move a tag until PR10
is merged, CI is green, and the live-Home-Assistant upgrade smoke test passes.**

Latest published integration release: [v0.8.0](https://github.com/fursov/fmi-hass-custom/releases/tag/v0.8.0).

## Contents

- PR9 (already merged): canonical `custom_components/fmi/` layout, direct
  Hassfest validation, updated HACS packaging; obsolete `debug/` removed.
- PR10: replace `fmi-weather-client==0.7.0` with **1.0.0** in the manifest and
  test requirements; check real installed client exports and data models.
- Update `custom_components/fmi/manifest.json` to integration version
  **0.9.0** (client and integration versions are independent).
- Move detailed PR1–PR10 history out of README into `CHANGELOG.md`; keep
  README focused on setup, features, compatibility and documentation links.

## Automated checks before merge

- [ ] Python 3.12 and 3.13 build + lint jobs pass.
- [ ] All offline regression tests pass on Python 3.13 and 3.14.
- [ ] Home Assistant 2026.9.4 / Python 3.14 integration tests pass, including
      actual `fmi-weather-client 1.0.0` model/signature checks.
- [ ] Hassfest passes against `custom_components/fmi/`.
- [ ] `manifest.json`, `CHANGELOG.md`, release notes and version tests say
      `0.9.0`; client is pinned to `1.0.0`.

## Manual checks before publication

- [ ] Upgrade an existing **v0.8.0** HACS installation to PR10 or a packaged
      release candidate, then restart Home Assistant.
- [ ] Verify HACS installs `custom_components/fmi/` without root-layout files
      and shows the same FMI config entry and entity registry identifiers.
- [ ] Confirm live FMI current weather and location are populated, including
      temperature, rainfall, humidity and wind.
- [ ] Check the hourly and daily `weather.get_forecasts` results; test a
      different `offset` and `forecast_days` setting.
- [ ] When an FMI station is configured, verify live observation values and
      station availability.
- [ ] When enabled, check lightning; inspect sea level when source data exist.
      XML tests are synthetic and do **not** prove live WFS compatibility.
- [ ] Exercise options changes, reload and full HA restart. Check the HA log
      for client parsing errors, exceptions and stale data.
- [ ] Check that dashboards and automations still refer to the same entities.

## Publication after merge

1. Verify the **PR10 merge commit** on `master` has `manifest.version == 0.9.0`.
2. Create the **new** Git tag `v0.9.0` on that tested merge commit.
3. Publish a GitHub Release `v0.9.0` using
   [RELEASE_NOTES_0.9.0.md](RELEASE_NOTES_0.9.0.md) as draft content.
4. Confirm the correct spelling `v0.9.0` (not `v.0.9.0`) and that HACS
   discovers and installs this release.
5. Keep the already published `v0.8.0` tag unchanged.

**Limitations:** CI uses mocked FMI transport. Real FMI endpoints, WFS schemas,
and Home Assistant versions beyond the pinned CI fixture require separate
validation. No minimum HA version is declared in HACS metadata in this PR.
