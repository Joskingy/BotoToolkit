"""Exercise real disposable Git histories; no GitHub, AWS, or downloads."""

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "dev_workflow", Path(__file__).resolve().parents[1] / "scripts/dev.py"
)
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, text=True, capture_output=True, timeout=30
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    root = tmp_path / "toolkit"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    (root / "scripts").mkdir()
    (root / "scripts/dev.py").write_text("# synthetic helper\n")
    (root / ".gitignore").write_text(".uv/\n.venv/\n")
    (root / "README.md").write_text("Synthetic fixture\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "Initial fixture")
    git(root, "branch", "dev")
    remote = tmp_path / "remote.git"
    git(root, "init", "--bare", str(remote))
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "origin", "main", "dev")
    return root


def feature(repo):
    git(repo, "switch", "-c", "feature/example", "origin/dev")
    (repo / "feature.md").write_text("Synthetic feature\n")
    git(repo, "add", "feature.md")
    git(repo, "commit", "-m", "Feature fixture")


def publishing(repo, monkeypatch):
    workflow = dev.Workflow(repo)
    monkeypatch.setattr(workflow, "repository", lambda: "example/toolkit")
    monkeypatch.setattr(workflow, "authenticate", lambda: None)
    monkeypatch.setattr(workflow, "check", lambda: None)
    return workflow


def test_start_uses_remote_dev_and_separate_sibling_even_from_feature(repo, monkeypatch):
    feature(repo)
    initialized = []
    monkeypatch.setattr(dev.Workflow, "setup", lambda self: initialized.append(self.root))
    current = repo.parent / "existing"
    git(repo, "worktree", "add", "-b", "feature/existing", str(current))
    (repo / ".venv").mkdir()
    (repo / ".venv/private-marker").write_text("local only")
    target = dev.Workflow(current).start("new-help", "feature")
    assert target == repo.parent / "toolkit-feature-new-help"
    assert git(target, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/dev")
    assert git(target, "branch", "--show-current") == "feature/new-help"
    assert not (target / "feature.md").exists()
    assert not (target / ".venv/private-marker").exists()
    assert git(current, "branch", "--show-current") == "feature/existing"
    assert initialized == [target]


@pytest.mark.parametrize("slug", ["../escape", "--force", "nested/name", "", "UPPER"])
def test_invalid_feature_names_make_no_git_changes(repo, slug):
    before = git(repo, "worktree", "list")
    with pytest.raises(dev.WorkflowError, match="lowercase"):
        dev.Workflow(repo).start(slug, "feature")
    assert git(repo, "worktree", "list") == before


def test_start_refuses_dirty_checkout_and_existing_paths(repo):
    (repo / "pending.md").write_text("unsaved work")
    with pytest.raises(dev.WorkflowError, match="Commit or save"):
        dev.Workflow(repo).start("help", "feature")
    git(repo, "add", "pending.md")
    git(repo, "commit", "-m", "Save fixture")
    target = repo.parent / "toolkit-feature-help"
    target.mkdir()
    (target / "keep.md").write_text("keep")
    with pytest.raises(dev.WorkflowError, match="folder already exists"):
        dev.Workflow(repo).start("help", "feature")
    assert (target / "keep.md").read_text() == "keep"


def test_setup_failure_keeps_created_worktree_for_recovery(repo, monkeypatch):
    def fail(self):
        raise dev.WorkflowError("download unavailable")

    monkeypatch.setattr(dev.Workflow, "setup", fail)
    with pytest.raises(dev.WorkflowError, match="download unavailable"):
        dev.Workflow(repo).start("help", "codex")
    target = repo.parent / "toolkit-codex-help"
    assert target.is_dir()
    assert git(target, "branch", "--show-current") == "codex/help"


def test_child_environment_does_not_share_activated_project(repo, monkeypatch):
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/other/project/.venv")
    monkeypatch.setenv("VIRTUAL_ENV", "/other/project/.venv")
    monkeypatch.setenv("PYTHONPATH", "/other/project/src")
    monkeypatch.setenv("GH_HOST", "other.example.invalid")
    monkeypatch.setenv("GH_REPO", "unrelated/repository")
    monkeypatch.setenv("GIT_WORK_TREE", "/other/project")
    workflow = dev.Workflow(repo)
    assert workflow.env["UV_PROJECT_ENVIRONMENT"] == str(repo / ".venv")
    assert "VIRTUAL_ENV" not in workflow.env
    assert "PYTHONPATH" not in workflow.env
    assert workflow.env["GH_HOST"] == "github.com"
    assert "GH_REPO" not in workflow.env
    assert "GIT_WORK_TREE" not in workflow.env
    assert os.environ["UV_PROJECT_ENVIRONMENT"] == "/other/project/.venv"


def test_check_stops_on_test_failure(repo, monkeypatch):
    workflow = dev.Workflow(repo)
    calls = []
    monkeypatch.setattr(workflow, "setup", lambda: None)

    def run(*args, **kwargs):
        calls.append(args)
        if "pytest" in args:
            raise subprocess.CalledProcessError(1, "pytest")

    monkeypatch.setattr(workflow, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        workflow.check()
    assert any("pytest" in call for call in calls)
    assert not any("ruff" in call or "scripts/check_distribution.py" in call for call in calls)


@pytest.mark.parametrize("branch", ["main", "dev"])
def test_pr_refuses_long_lived_branches(repo, branch):
    git(repo, "switch", branch)
    with pytest.raises(dev.WorkflowError, match="Feature PRs"):
        dev.Workflow(repo).pr(None, None, False)


def test_failed_checks_never_push_feature(repo, monkeypatch):
    feature(repo)
    workflow = publishing(repo, monkeypatch)

    def fail():
        raise dev.WorkflowError("failing checks")

    monkeypatch.setattr(workflow, "check", fail)
    with pytest.raises(dev.WorkflowError, match="failing checks"):
        workflow.pr(None, None, False)
    assert git(repo, "ls-remote", "origin", "refs/heads/feature/example") == ""


def test_dirty_pr_is_rejected_before_authentication(repo, monkeypatch):
    feature(repo)
    (repo / "pending.md").write_text("not committed")
    workflow = publishing(repo, monkeypatch)
    monkeypatch.setattr(workflow, "authenticate", lambda: pytest.fail("must reject before auth"))
    with pytest.raises(dev.WorkflowError, match="Commit or save"):
        workflow.pr(None, None, False)


def test_changed_head_during_checks_is_not_pushed(repo, monkeypatch):
    feature(repo)
    workflow = publishing(repo, monkeypatch)

    def change():
        git(repo, "commit", "--allow-empty", "-m", "Concurrent change")

    monkeypatch.setattr(workflow, "check", change)
    with pytest.raises(dev.WorkflowError, match="branch changed"):
        workflow.pr(None, None, False)
    assert git(repo, "ls-remote", "origin", "refs/heads/feature/example") == ""


def test_pr_pushes_correct_branch_and_reuses_existing_pr(repo, monkeypatch):
    feature(repo)
    workflow = publishing(repo, monkeypatch)
    original = workflow.run
    calls = []
    existing = False

    def run(*args, **kwargs):
        nonlocal existing
        if args[0] != "gh":
            return original(*args, **kwargs)
        calls.append(args)
        if args[1:3] == ("pr", "list"):
            return (
                '[{"url":"https://github.com/example/toolkit/pull/1","isCrossRepository":false}]'
                if existing
                else "[]"
            )
        assert args[1:3] == ("pr", "create")
        assert args[args.index("--base") + 1] == "dev"
        assert args[args.index("--head") + 1] == "feature/example"
        assert "--draft" in args
        assert "Local verification" in Path(args[args.index("--body-file") + 1]).read_text()
        existing = True
        return "https://github.com/example/toolkit/pull/1"

    monkeypatch.setattr(workflow, "run", run)
    assert workflow.pr("Example", None, True) == workflow.pr("Example", None, True)
    assert sum(call[1:3] == ("pr", "create") for call in calls) == 1
    assert git(repo, "ls-remote", "origin", "refs/heads/feature/example").startswith(
        git(repo, "rev-parse", "HEAD")
    )


def test_promote_uses_remote_dev_without_pushing_local_feature(repo, monkeypatch):
    feature(repo)
    git(repo, "push", "origin", "HEAD:dev")
    workflow = publishing(repo, monkeypatch)
    observed = []
    monkeypatch.setattr(workflow, "open_pr", lambda *args: observed.append(args) or "url")
    assert workflow.promote(None, False) == "url"
    assert observed[0][1:3] == ("dev", "main")
    assert git(repo, "ls-remote", "origin", "refs/heads/feature/example") == ""


def test_promote_refuses_dev_behind_main(repo, monkeypatch):
    feature(repo)
    git(repo, "push", "origin", "HEAD:main")
    workflow = publishing(repo, monkeypatch)
    monkeypatch.setattr(workflow, "open_pr", lambda *args: pytest.fail("must not open PR"))
    with pytest.raises(dev.WorkflowError, match="Sync main"):
        workflow.promote(None, False)


@pytest.mark.parametrize(
    "remote", ["https://github.com/example/toolkit.git", "git@github.com:example/toolkit.git"]
)
def test_repository_is_derived_from_origin(repo, remote):
    git(repo, "remote", "set-url", "origin", remote)
    assert dev.Workflow(repo).repository() == "example/toolkit"


def test_setup_preserves_custom_hooks(repo, monkeypatch):
    git(repo, "config", "core.hooksPath", "custom-hooks")
    workflow = dev.Workflow(repo)
    monkeypatch.setattr(workflow, "configure_uv", lambda: None)
    with pytest.raises(dev.WorkflowError, match="Custom Git hooks"):
        workflow.setup()
    assert git(repo, "config", "--get", "core.hooksPath") == "custom-hooks"


def test_repository_rejects_different_push_destination(repo):
    git(repo, "remote", "set-url", "origin", "https://github.com/example/toolkit.git")
    git(repo, "remote", "set-url", "--push", "origin", "https://github.com/other/toolkit.git")
    with pytest.raises(dev.WorkflowError, match="destinations differ"):
        dev.Workflow(repo).repository()


def test_repository_rejects_multiple_push_destinations(repo):
    git(repo, "remote", "set-url", "origin", "https://github.com/example/toolkit.git")
    git(
        repo,
        "remote",
        "set-url",
        "--add",
        "--push",
        "origin",
        "https://github.com/example/toolkit.git",
    )
    git(
        repo,
        "remote",
        "set-url",
        "--add",
        "--push",
        "origin",
        "https://github.com/other/toolkit.git",
    )
    with pytest.raises(dev.WorkflowError, match="standard github.com origin"):
        dev.Workflow(repo).repository()


def test_pr_requires_updated_dev_before_checks_or_push(repo, monkeypatch):
    feature(repo)
    git(repo, "switch", "dev")
    git(repo, "commit", "--allow-empty", "-m", "Updated dev")
    git(repo, "push", "origin", "dev")
    git(repo, "switch", "feature/example")
    workflow = publishing(repo, monkeypatch)
    monkeypatch.setattr(workflow, "check", lambda: pytest.fail("must stop before checks"))
    with pytest.raises(dev.WorkflowError, match="Dev has advanced"):
        workflow.pr(None, None, False)
    assert git(repo, "ls-remote", "origin", "refs/heads/feature/example") == ""


def test_start_refuses_existing_remote_branch(repo):
    git(repo, "push", "origin", "HEAD:feature/help")
    with pytest.raises(dev.WorkflowError, match="branch already exists"):
        dev.Workflow(repo).start("help", "feature")
    assert not (repo.parent / "toolkit-feature-help").exists()


def test_start_requires_helper_on_dev_before_creating_worktree(repo):
    git(repo, "switch", "dev")
    git(repo, "rm", "scripts/dev.py")
    git(repo, "commit", "-m", "Old dev without helper")
    git(repo, "push", "origin", "dev")
    with pytest.raises(dev.WorkflowError, match="Merge the developer helper"):
        dev.Workflow(repo).start("help", "feature")
    assert not (repo.parent / "toolkit-feature-help").exists()


def test_setup_preserves_default_directory_hooks(repo, monkeypatch):
    hooks = repo / ".git/hooks/pre-commit"
    hooks.write_text("#!/bin/sh\nexit 0\n")
    (repo / ".githooks").mkdir()
    (repo / ".githooks/pre-commit").write_text("#!/bin/sh\nexit 0\n")
    workflow = dev.Workflow(repo)
    monkeypatch.setattr(workflow, "configure_uv", lambda: None)
    with pytest.raises(dev.WorkflowError, match="default directory"):
        workflow.setup()
    assert hooks.read_text() == "#!/bin/sh\nexit 0\n"
    assert git(repo, "config", "--get-regexp", "^core\\.").find("hookspath") == -1


def test_cli_propagates_failure_without_running_publication(repo, monkeypatch, capsys):
    monkeypatch.setattr(dev, "ROOT", repo)
    assert dev.main(["pr"]) == 1
    assert "Feature PRs" in capsys.readouterr().err
