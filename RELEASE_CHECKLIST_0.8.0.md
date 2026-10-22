# Release preparation: FMI v0.8.0

The previous published release is **v0.7.2**. This PR prepares the next
**v0.8.0**; it does not publish a GitHub release or create a tag.

## Scope

- End-to-end config entry setup, sensor and weather entity registration, state
  updates, `weather.get_forecasts`, options flow, options-triggered reload,
  unloading, recovery after loading, and failure isolation.
- Integration test job using Python 3.14, real Home Assistant and its pytest
  fixtures, offline FMI API mocks and the actual root-layout integration
  staged under `custom_components/fmi`.
- Retain legacy config entry IDs, native sensor `unique_id` values and
  option keys. No migration or re-creation of existing entities.
- Bump `manifest.json` to `0.8.0` as part of the mergeable release candidate.

## Before merging PR8

- [ ] All required jobs, including real Home Assistant tests and Hassfest, pass.
- [ ] Upgrade the existing installed v0.7.2 integration and restart HA.
- [ ] Confirm current-weather, sensor, daily forecast, and observation entity IDs.
- [ ] Change options, reload, unload and restart without duplicate listeners.
- [ ] Confirm lightning and sea-level behavior against real FMI XML if available.
- [ ] Verify that HA entity registry and automation references remain unchanged.
- [ ] Review installed Home Assistant version in the CI log and supported HA
      versions in production, especially Python 3.14 requirements.

## After merging PR8

1. Confirm `master` contains manifest version `0.8.0`.
2. Create annotated tag `v0.8.0` from the tested merge commit.
3. Publish a GitHub release for `v0.8.0`, listing migration/testing notes.
4. Confirm HACS offers v0.8.0 as an update, then test a clean install.

**Do not tag before PR8 is merged or claim live FMI endpoints are CI-tested.**
