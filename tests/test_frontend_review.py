import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src"


def _read(name):
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_api_exports_run_review():
    """api.js 必须导出 runReview,且以 POST /api/tasks/{id}/review 实现
    (终审 Important 7)。修复前没有 runReview,此断言失败。"""
    src = _read("api.js")
    m = re.search(
        r"export const runReview\s*=\s*\(id\)\s*=>\s*jsonFetch\(`/api/tasks/\$\{id\}/review`,\s*\{\s*method:\s*'POST'\s*\}\)",
        src)
    assert m, "runReview 必须以 POST /api/tasks/{id}/review 定义"


def test_review_pane_renders_run_button():
    """ReviewPane 必须导入 runReview 并渲染『运行 Review』按钮,点击后 POST
    再重新拉取 review(终审 Important 7)。修复前没有按钮,此断言失败。"""
    src = _read("components/ReviewPane.jsx")
    assert "runReview" in src, "ReviewPane 必须导入 runReview"
    assert "await runReview(task.id)" in src, "按钮回调必须 POST runReview"
    assert "getReview(task.id)" in src, "POST 后必须重新拉取 review"
    assert "运行 Review" in src, "ReviewPane 必须渲染『运行 Review』按钮"
