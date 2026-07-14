"""
ComfyUI-Grok-NM 單元測試
不需要 torch / ComfyUI,可在 CI 直接跑(不打網路)
"""

import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_NAME = "comfyui_grok_nm"


def _load_package():
    if PKG_NAME in sys.modules:
        return sys.modules[PKG_NAME]
    spec = importlib.util.spec_from_file_location(
        PKG_NAME,
        os.path.join(ROOT, "__init__.py"),
        submodule_search_locations=[ROOT],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[PKG_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pkg():
    # 確保測試不受本機 .env 影響
    os.environ.pop("XAI_API_KEY", None)
    return _load_package()


def _api_module():
    return sys.modules[f"{PKG_NAME}.modules.grok_api"]


def _media_module():
    return sys.modules[f"{PKG_NAME}.modules.media_utils"]


# ----------------------------------------------------------------------
# 節點註冊
# ----------------------------------------------------------------------

def test_node_mappings(pkg):
    assert set(pkg.NODE_CLASS_MAPPINGS) == {
        "GrokChatNode", "GrokVisionNode", "GrokImageGenNode",
        "GrokVideoGenNode", "GrokListModelsNode",
    }
    assert set(pkg.NODE_DISPLAY_NAME_MAPPINGS) == set(pkg.NODE_CLASS_MAPPINGS)


def test_input_types_fallback_without_key(pkg):
    """無 API key 時 INPUT_TYPES 應 fallback 預設模型,不能拋例外"""
    it = pkg.NODE_CLASS_MAPPINGS["GrokChatNode"].INPUT_TYPES()
    models = it["required"]["model"][0]
    assert isinstance(models, list) and len(models) > 0


def test_categories(pkg):
    cats = {c.CATEGORY for c in pkg.NODE_CLASS_MAPPINGS.values()}
    assert cats == {
        "AI/Grok/chat", "AI/Grok/vision", "AI/Grok/image",
        "AI/Grok/video", "AI/Grok/utils",
    }


# ----------------------------------------------------------------------
# API 客戶端(不打網路)
# ----------------------------------------------------------------------

def test_api_requires_key(pkg):
    api = _api_module()
    with pytest.raises(ValueError):
        api.GrokAPI(api_key=None)


def test_generate_images_rejects_bad_n(pkg):
    """超過 10 張須在送出前就拋 GrokAPIError(不打網路)"""
    api = _api_module()
    client = api.GrokAPI(api_key="dummy-key")
    with pytest.raises(api.GrokAPIError):
        client.generate_images("test", "grok-imagine-image", n=11)
    with pytest.raises(api.GrokAPIError):
        client.generate_images("test", "grok-imagine-image", n=0)


def test_submit_video_rejects_bad_duration(pkg):
    """超過 15 秒須在送出前就拋 GrokAPIError(不打網路)"""
    api = _api_module()
    client = api.GrokAPI(api_key="dummy-key")
    with pytest.raises(api.GrokAPIError):
        client.submit_video("test", "grok-imagine-video-1.5", duration=16)


def test_error_status_hint(pkg):
    api = _api_module()
    err = api.GrokAPIError("測試", status=401)
    assert "XAI_API_KEY 無效或未設定" in str(err)


def test_base_url_default(pkg):
    api = _api_module()
    client = api.GrokAPI(api_key="dummy-key")
    assert client.base_url == "https://api.x.ai/v1"


# ----------------------------------------------------------------------
# 媒體工具(純字串部分)
# ----------------------------------------------------------------------

def test_strip_data_url(pkg):
    media = _media_module()
    assert media.strip_data_url("data:image/png;base64,QUJD") == "QUJD"
    assert media.strip_data_url("QUJD") == "QUJD"
    assert media.strip_data_url("https://example.com/a.png") == "https://example.com/a.png"


def test_tensor_roundtrip():
    """torch 環境才跑:tensor → b64 → tensor 往返"""
    torch = pytest.importorskip("torch")
    pytest.importorskip("PIL")
    _load_package()
    media = _media_module()

    img = torch.rand(1, 32, 48, 3)
    b64 = media.tensor_to_png_b64(img, 0)
    back = media.b64_or_url_to_tensor(b64)
    assert back.shape == (1, 32, 48, 3)
    assert (back - img).abs().max().item() < 0.01
