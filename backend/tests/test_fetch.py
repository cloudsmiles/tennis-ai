"""视频链接白名单校验（不触网；下载本身需 yt-dlp + 网络，不在单测范围）。"""
from app.fetch import is_allowed_url


def test_allows_bilibili_domains():
    assert is_allowed_url("https://www.bilibili.com/video/BV1xx411c7mD")
    assert is_allowed_url("https://bilibili.com/video/BV1xx")
    assert is_allowed_url("https://b23.tv/abc123")
    assert is_allowed_url("https://m.bilibili.com/video/BV1xx")


def test_rejects_non_bilibili_and_garbage():
    assert not is_allowed_url("https://www.youtube.com/watch?v=abc")
    assert not is_allowed_url("https://bilibili.com.evil.com/x")
    assert not is_allowed_url("https://evilbilibili.com/x")
    assert not is_allowed_url("not a url")
    assert not is_allowed_url("")
