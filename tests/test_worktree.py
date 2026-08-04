import subprocess
from pathlib import Path
from taskpanel.store.worktree import WorktreeManager


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "a.txt").write_text("v1")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def test_create_and_remove(tmp_path):
    repo = _make_repo(tmp_path)
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    wt = mgr.create(str(repo))
    assert Path(wt).exists()
    assert (Path(wt) / "a.txt").read_text() == "v1"
    mgr.remove(wt)
    assert not Path(wt).exists()
