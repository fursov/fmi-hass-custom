# FMI v0.9.0

Release notes draft — publish only after the tested PR10 merge and a successful
real-Home-Assistant smoke test.

## Changes since v0.8.0

- **Standard Home Assistant repository structure:** the integration now lives
  under `custom_components/fmi/`; HACS no longer needs `content_in_root`.
  Obsolete lightning debug code was removed. (PR9)
- **Updated FMI Python client:** pinned `fmi-weather-client` from `0.7.0`
  to `1.0.0`. The integration version is **0.9.0**; the library has its own
  independent version. (PR10)
- **More compatibility tests:** added real installed-client function/model
  contracts and actual `WeatherData` models feeding Home Assistant sensor
  entities; retained the existing isolated regression and HA lifecycle tests.
- **Clearer documentation:** development history moved to
  [CHANGELOG.md](CHANGELOG.md); installation and compatibility instructions
  remain in README.

## Upgrade notes

Update the existing FMI integration in HACS and restart Home Assistant.
The FMI integration domain, configured locations, option keys and entity
identifiers are not intentionally changed; there is no config-entry migration.
For manual installations, copy only `custom_components/fmi/` to the
corresponding directory in your HA configuration.

## Validation and limitations

CI tests the client library and Home Assistant with locally mocked FMI
HTTP responses. Real FMI live-weather, forecast, optional observation and WFS
responses must be verified manually before publishing this release.
The CI-tested HA version is **2026.9.4** on Python 3.14; this is not a
compatibility guarantee for every HA version.

Full change history: [CHANGELOG.md](CHANGELOG.md).
