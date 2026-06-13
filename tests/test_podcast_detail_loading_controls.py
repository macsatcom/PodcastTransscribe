from pathlib import Path


def test_podcast_detail_has_stop_loading_control_and_state_flag():
    template_path = Path(__file__).resolve().parents[1] / "app/templates/podcast_detail.html"
    source = template_path.read_text(encoding="utf-8")

    assert "Stop loading older episodes" in source
    assert "@click=\"stopLoading()\"" in source
    assert "_stopLoadingRequested" in source
    assert "if (this._stopLoadingRequested)" in source
    assert "Resume loading older episodes" in source
    assert "@click=\"resumeLoading()\"" in source
    assert "resumeLoading()" in source
    assert "_nextOffset" in source
