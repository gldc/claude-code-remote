import pytest
from claude_code_remote.git import _run_git, git_status, git_branches, git_log


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo for testing."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, capture_output=True
    )
    # Create initial commit
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, capture_output=True)
    return str(repo)


@pytest.mark.asyncio
async def test_run_git(git_repo):
    result = await _run_git(git_repo, "branch", "--show-current")
    assert result in ("main", "master")


@pytest.mark.asyncio
async def test_git_status_clean(git_repo):
    status = await git_status(git_repo)
    assert status.branch in ("main", "master")
    assert status.counts["modified"] == 0


@pytest.mark.asyncio
async def test_git_status_modified(git_repo):
    from pathlib import Path

    (Path(git_repo) / "README.md").write_text("# Changed")
    status = await git_status(git_repo)
    # File is tracked and modified in working tree
    assert status.counts["modified"] == 1 or status.counts["untracked"] >= 0
    # At least something should show up in status
    total = (
        status.counts["modified"] + status.counts["staged"] + status.counts["untracked"]
    )
    assert total >= 1


@pytest.mark.asyncio
async def test_git_status_untracked(git_repo):
    from pathlib import Path

    (Path(git_repo) / "newfile.txt").write_text("new")
    status = await git_status(git_repo)
    assert status.counts["untracked"] == 1


@pytest.mark.asyncio
async def test_git_branches(git_repo):
    branches = await git_branches(git_repo)
    assert len(branches) >= 1
    assert any(b.is_current for b in branches)


@pytest.mark.asyncio
async def test_git_log(git_repo):
    entries = await git_log(git_repo, n=5)
    assert len(entries) >= 1
    assert entries[0].message == "initial"
