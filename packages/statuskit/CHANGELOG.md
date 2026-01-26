# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
