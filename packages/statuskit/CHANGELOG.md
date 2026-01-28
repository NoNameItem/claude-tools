# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.2](https://github.com/NoNameItem/claude-tools/compare/statuskit-0.3.1...statuskit-0.3.2) (2026-01-28)


### Bug Fixes

* **statuskit:** handle null resets_at in usage_limits module ([#44](https://github.com/NoNameItem/claude-tools/issues/44)) ([ab05359](https://github.com/NoNameItem/claude-tools/commit/ab05359fa9e63b89f64a1f8c95a4f6dbda2a8552))

## [0.3.1](https://github.com/NoNameItem/claude-tools/compare/statuskit-0.3.0...statuskit-0.3.1) (2026-01-28)


### Bug Fixes

* **statuskit:** decompose commit age into d/h/m units ([#39](https://github.com/NoNameItem/claude-tools/issues/39)) ([52d83f8](https://github.com/NoNameItem/claude-tools/commit/52d83f8444a97c8ed73f45d10fb4af8b2a2d21f3))
* **statuskit:** enable ANSI colors in Claude Code statusline ([#35](https://github.com/NoNameItem/claude-tools/issues/35)) ([e2d265c](https://github.com/NoNameItem/claude-tools/commit/e2d265c29362d8ffbb49bcc276bce620e55df7b7))
* **statuskit:** resolve relative git path for project name ([#37](https://github.com/NoNameItem/claude-tools/issues/37)) ([9caf51d](https://github.com/NoNameItem/claude-tools/commit/9caf51d4dfd6b4548833c30a3d485041b68f0a3b))
* **statuskit:** return stale cache when rate-limited ([#41](https://github.com/NoNameItem/claude-tools/issues/41)) ([9772f05](https://github.com/NoNameItem/claude-tools/commit/9772f050d952e729ff18842703f5f34dc9606ce1))
* **statuskit:** update default config as documentation template ([#36](https://github.com/NoNameItem/claude-tools/issues/36)) ([07ed745](https://github.com/NoNameItem/claude-tools/commit/07ed745f3cd14b9e1375f5bc628ceaedb2e40d51))

## [0.3.0](https://github.com/NoNameItem/claude-tools/compare/statuskit-0.2.1...statuskit-0.3.0) (2026-01-27)


### Features

* statuskit MVP implementation ([1ce5ea4](https://github.com/NoNameItem/claude-tools/commit/1ce5ea486a55f6470cd7711257d2d5651281cc41))
* **statuskit:** add CLI interface and setup command ([#2](https://github.com/NoNameItem/claude-tools/issues/2)) ([469ca00](https://github.com/NoNameItem/claude-tools/commit/469ca0022051e37992fb645058daeca075fc7e9f))
* **statuskit:** add git module ([#26](https://github.com/NoNameItem/claude-tools/issues/26)) ([4fc5615](https://github.com/NoNameItem/claude-tools/commit/4fc56155a8b0db07ae742f07a2e53c5818745aa4))
* **statuskit:** add usage_limits module ([#27](https://github.com/NoNameItem/claude-tools/issues/27)) ([8c2f6f2](https://github.com/NoNameItem/claude-tools/commit/8c2f6f2d60ab2e121e73f7ba0159ba76776b54e4))


### Bug Fixes

* **statuskit:** example output ([#30](https://github.com/NoNameItem/claude-tools/issues/30)) ([369fb54](https://github.com/NoNameItem/claude-tools/commit/369fb54bdd0b557b17f77421b57b0d17c40bfffb))
* **statuskit:** resolve ty type checker warnings ([#4](https://github.com/NoNameItem/claude-tools/issues/4)) ([9207737](https://github.com/NoNameItem/claude-tools/commit/9207737257d75b966506752001d62ec25747939d))


### Documentation

* **statuskit:** update README for PyPI ([#29](https://github.com/NoNameItem/claude-tools/issues/29)) ([c8af389](https://github.com/NoNameItem/claude-tools/commit/c8af389d92ad9d12e345e2892e94011eeec0f47f))

## [0.2.1](https://github.com/NoNameItem/claude-tools/compare/statuskit-0.2.0...statuskit-0.2.1) (2026-01-27)


### Bug Fixes

* **statuskit:** example output ([#30](https://github.com/NoNameItem/claude-tools/issues/30)) ([369fb54](https://github.com/NoNameItem/claude-tools/commit/369fb54bdd0b557b17f77421b57b0d17c40bfffb))

## [0.2.0](https://github.com/NoNameItem/claude-tools/compare/statuskit-0.1.0...statuskit-0.2.0) (2026-01-27)


### Features

* statuskit MVP implementation ([1ce5ea4](https://github.com/NoNameItem/claude-tools/commit/1ce5ea486a55f6470cd7711257d2d5651281cc41))
* **statuskit:** add CLI interface and setup command ([#2](https://github.com/NoNameItem/claude-tools/issues/2)) ([469ca00](https://github.com/NoNameItem/claude-tools/commit/469ca0022051e37992fb645058daeca075fc7e9f))
* **statuskit:** add git module ([#26](https://github.com/NoNameItem/claude-tools/issues/26)) ([4fc5615](https://github.com/NoNameItem/claude-tools/commit/4fc56155a8b0db07ae742f07a2e53c5818745aa4))
* **statuskit:** add usage_limits module ([#27](https://github.com/NoNameItem/claude-tools/issues/27)) ([8c2f6f2](https://github.com/NoNameItem/claude-tools/commit/8c2f6f2d60ab2e121e73f7ba0159ba76776b54e4))


### Bug Fixes

* **statuskit:** resolve ty type checker warnings ([#4](https://github.com/NoNameItem/claude-tools/issues/4)) ([9207737](https://github.com/NoNameItem/claude-tools/commit/9207737257d75b966506752001d62ec25747939d))


### Documentation

* **statuskit:** update README for PyPI ([#29](https://github.com/NoNameItem/claude-tools/issues/29)) ([c8af389](https://github.com/NoNameItem/claude-tools/commit/c8af389d92ad9d12e345e2892e94011eeec0f47f))

## [0.1.0] - 2026-01-19

### Added

- Modular statusline architecture with plugin system
- Built-in module `model` displaying:
  - Current Claude model name
  - Session duration (e.g., `2h 15m`)
  - Context window usage with color coding (green/yellow/red)
  - Multiple display formats: `free`, `used`, `ratio`, `bar`
  - Compact number formatting option (e.g., `150k` instead of `150,000`)
- CLI interface with `--version` and `--help`
- Setup command for hook installation:
  - `statuskit setup` — interactive installation
  - `statuskit setup --check` — verify installation
  - `statuskit setup --remove` — uninstall hook
- Hierarchical config loading (global, project, local)
- Automatic detection of higher-scope installations
- Backup creation before modifying settings
- Gitignore handling for local scope configs

### Fixed

- Type checker warnings resolved
