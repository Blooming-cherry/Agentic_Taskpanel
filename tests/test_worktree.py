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


def test_cleanup_keeps_active_worktree(tmp_path):
    """cleanup(active) 必须保留 active 集合内的 worktree,只清理未被引用的
    stale worktree(超出 max_retained 的部分)(终审 Important 5)。"""
    import time
    repo = _make_repo(tmp_path)
    mgr = WorktreeManager(base_dir=tmp_path / "wt", max_retained=1)
    wt_active = mgr.create(str(repo))
    time.sleep(0.05)  # 保证 mtime 可区分,旧实现会按 mtime 删最老的
    wt_s1 = mgr.create(str(repo))
    wt_s2 = mgr.create(str(repo))

    removed = mgr.cleanup({wt_active})

    assert Path(wt_active).exists(), "active worktree 不得被清理"
    assert removed == 1, "stale 超出 max_retained 的部分应被清理"
    # 只剩 active + max_retained 个保留的 stale
    remaining = [p for p in (tmp_path / "wt").iterdir()]
    assert len(remaining) == 2


def test_cleanup_removes_all_stale_when_max_retained_zero(tmp_path):
    repo = _make_repo(tmp_path)
    mgr = WorktreeManager(base_dir=tmp_path / "wt", max_retained=0)
    wt_active = mgr.create(str(repo))
    wt_stale = mgr.create(str(repo))

    removed = mgr.cleanup({wt_active})

    assert Path(wt_active).exists()
    assert not Path(wt_stale).exists()
    assert removed == 1
