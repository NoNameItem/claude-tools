"""Tests for the `statuskit config` subcommand."""

import sys
from pathlib import Path

import pytest
from statuskit import main
from statuskit.setup.config_gen import build_config


@pytest.fixture
def env(monkeypatch, tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(project)
    return tmp_path


@pytest.fixture
def user_cfg(env):
    return env / "home" / ".claude" / "statuskit.toml"


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["statuskit", "config", *argv])
    main()


def run_exit1(monkeypatch, *argv):
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, *argv)
    assert exc.value.code == 1


def lines(capsys):
    return capsys.readouterr().out.splitlines()


def test_init_creates_user_config(env, user_cfg, monkeypatch, capsys):
    run(monkeypatch, "init")
    assert user_cfg.exists()
    assert lines(capsys) == [f"✓ Created {user_cfg}"]


def test_init_twice_reports_exists(env, user_cfg, monkeypatch, capsys):
    run(monkeypatch, "init")
    capsys.readouterr()
    run_exit1(monkeypatch, "init")
    assert lines(capsys) == [
        f"{user_cfg} already exists. Run 'statuskit config sync' to update it, "
        "or 'statuskit config init --force' to reset it to defaults."
    ]


def test_init_force_resets_with_backup(env, user_cfg, monkeypatch, capsys):
    run(monkeypatch, "init")
    capsys.readouterr()
    run(monkeypatch, "init", "--force")
    (line,) = lines(capsys)
    assert line.startswith(f"✓ Reset {user_cfg} to defaults (backup: ")
    assert "statuskit.toml.bak" in line


def test_init_project_scope_creates_claude_dir(env, monkeypatch, capsys):
    run(monkeypatch, "init", "--scope", "project")
    assert (env / "project" / ".claude" / "statuskit.toml").exists()
    assert lines(capsys) == ["✓ Created .claude/statuskit.toml"]


def test_sync_updates_and_lists_removals(env, user_cfg, monkeypatch, capsys):
    user_cfg.parent.mkdir(parents=True)
    user_cfg.write_text("[git]\nshow_prr = true\n")
    run(monkeypatch, "sync")
    out = lines(capsys)
    assert out[0].startswith(f"✓ Updated {user_cfg} (backup: ")
    assert out[1:] == ["Removed:", "  git.show_prr — unknown key"]


def test_sync_template_is_up_to_date(env, user_cfg, monkeypatch, capsys):
    user_cfg.parent.mkdir(parents=True)
    user_cfg.write_text(build_config()[0])
    run(monkeypatch, "sync")
    assert lines(capsys) == [f"{user_cfg} is up to date."]


def test_sync_invalid_toml_is_error(env, user_cfg, monkeypatch, capsys):
    user_cfg.parent.mkdir(parents=True)
    user_cfg.write_text("[git\n")
    run_exit1(monkeypatch, "sync")
    (line,) = lines(capsys)
    assert line.startswith("Cannot read")


def test_sync_dry_run_with_removals_exits_1(env, user_cfg, monkeypatch, capsys):
    user_cfg.parent.mkdir(parents=True)
    content = b"[git]\nshow_prr = true\n"
    user_cfg.write_bytes(content)
    run_exit1(monkeypatch, "sync", "--dry-run")
    out = lines(capsys)
    assert out[0] == f"Would update {user_cfg}"
    assert out[1:] == ["Would remove:", "  git.show_prr — unknown key"]
    assert user_cfg.read_bytes() == content


def test_sync_dry_run_empty_file_exits_0(env, user_cfg, monkeypatch, capsys):
    user_cfg.parent.mkdir(parents=True)
    user_cfg.write_text("")
    run(monkeypatch, "sync", "--dry-run")
    assert lines(capsys) == [f"Would update {user_cfg}"]
    assert user_cfg.read_text() == ""


def test_sync_dry_run_missing_file(env, user_cfg, monkeypatch, capsys):
    run(monkeypatch, "sync", "--dry-run")
    assert lines(capsys) == [f"{user_cfg} does not exist; sync would create it."]
    assert not user_cfg.exists()


def test_sync_creates_missing_file(env, user_cfg, monkeypatch, capsys):
    run(monkeypatch, "sync")
    assert user_cfg.exists()
    assert lines(capsys) == [f"✓ Created {user_cfg}"]


def test_sync_write_failure_is_error(env, user_cfg, monkeypatch, capsys):
    user_cfg.parent.mkdir(parents=True)
    user_cfg.write_text("")

    def boom(self, *args, **kwargs):
        msg = "denied"
        raise PermissionError(msg)

    monkeypatch.setattr(Path, "write_text", boom)
    run_exit1(monkeypatch, "sync")
    (line,) = lines(capsys)
    assert line.startswith("Cannot write")


@pytest.mark.parametrize(
    ("argv", "attr"),
    [(("sync",), "read_bytes"), (("sync", "--dry-run"), "read_bytes"), (("init",), "stat")],
)
def test_unreadable_config_prints_cannot_read(env, user_cfg, monkeypatch, capsys, argv, attr):
    user_cfg.parent.mkdir(parents=True)
    user_cfg.write_text("debug = true\n")

    def deny(self, *args, **kwargs):
        msg = "denied"
        raise PermissionError(msg)

    monkeypatch.setattr(Path, attr, deny)
    run_exit1(monkeypatch, *argv)
    captured = capsys.readouterr()
    assert f"Cannot read {user_cfg}" in captured.out + captured.err
    monkeypatch.undo()
    assert user_cfg.read_text() == "debug = true\n"
