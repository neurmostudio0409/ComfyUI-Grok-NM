"""
影片輸出儲存(ZDR)單元測試
不需 torch / ComfyUI / boto3,不打網路
"""

import datetime
import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_NAME = "comfyui_grok_nm"

# 所有本模組會讀的環境變數,每個測試前都清乾淨,避免被本機 .env 汙染
_ENV_KEYS = [
    "XAI_OUTPUT_STORAGE",
    "XAI_OUTPUT_UPLOAD_URL",
    "XAI_OUTPUT_FETCH_URL",
    "XAI_OUTPUT_S3_ENDPOINT",
    "XAI_OUTPUT_S3_BUCKET",
    "XAI_OUTPUT_S3_REGION",
    "XAI_OUTPUT_S3_ACCESS_KEY_ID",
    "XAI_OUTPUT_S3_SECRET_ACCESS_KEY",
    "XAI_OUTPUT_S3_KEY_PREFIX",
    "XAI_OUTPUT_S3_EXPIRES_SECS",
    "XAI_OUTPUT_S3_FORCE_PATH_STYLE",
]


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


@pytest.fixture
def storage():
    _load_package()
    for k in _ENV_KEYS:
        os.environ.pop(k, None)
    yield sys.modules[f"{PKG_NAME}.modules.output_storage"]
    for k in _ENV_KEYS:
        os.environ.pop(k, None)


def _set_s3(**over):
    cfg = {
        "XAI_OUTPUT_STORAGE": "s3",
        "XAI_OUTPUT_S3_ENDPOINT": "https://acct.r2.cloudflarestorage.com",
        "XAI_OUTPUT_S3_BUCKET": "grok-out",
        "XAI_OUTPUT_S3_REGION": "auto",
        "XAI_OUTPUT_S3_ACCESS_KEY_ID": "AKIATESTTESTTESTTEST",
        "XAI_OUTPUT_S3_SECRET_ACCESS_KEY": "secret-test-key",
    }
    cfg.update(over)
    os.environ.update(cfg)


# ----------------------------------------------------------------------
# SigV4 簽章正確性
# ----------------------------------------------------------------------

def test_presign_matches_aws_documented_vector(storage):
    """
    對上 AWS 官方文件的 SigV4 query-string 範例(GET Object)

    這是整個模組唯一無法靠自己驗證的部分 —— 簽章算錯的話 xAI 會 PUT 失敗,
    但我們要等到真的有 ZDR 帳號才看得到。所以用官方公開向量釘住。
    """
    url = storage.presign(
        "GET",
        endpoint="https://s3.amazonaws.com",
        bucket="examplebucket",
        key="test.txt",
        region="us-east-1",
        access_key="AKIAIOSFODNN7EXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        expires=86400,
        force_path_style=False,
        now=datetime.datetime(2013, 5, 24, tzinfo=datetime.timezone.utc),
    )
    assert url.startswith("https://examplebucket.s3.amazonaws.com/test.txt?")
    assert ("X-Amz-Signature="
            "aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"
            ) in url


def test_presign_signs_only_host(storage):
    """不簽 Content-Type:xAI PUT 上來帶什麼 Content-Type 官方未公開"""
    url = storage.presign(
        "PUT", endpoint="https://s3.example.com", bucket="b", key="k.mp4",
        region="auto", access_key="ak", secret_key="sk", expires=900)
    assert "X-Amz-SignedHeaders=host" in url
    assert "content-type" not in url.lower()


def test_presign_path_style_vs_virtual_host(storage):
    common = dict(endpoint="https://s3.example.com", bucket="buck",
                  key="a/b.mp4", region="auto", access_key="ak",
                  secret_key="sk", expires=900)
    path_style = storage.presign("PUT", force_path_style=True, **common)
    virtual = storage.presign("PUT", force_path_style=False, **common)
    assert path_style.startswith("https://s3.example.com/buck/a/b.mp4?")
    assert virtual.startswith("https://buck.s3.example.com/a/b.mp4?")


def test_presign_key_slashes_not_encoded(storage):
    """key 的 / 必須保留為路徑分隔,其餘字元才 percent-encode"""
    url = storage.presign(
        "PUT", endpoint="https://s3.example.com", bucket="b",
        key="pre fix/影片.mp4", region="auto", access_key="ak",
        secret_key="sk", expires=900)
    assert "/b/pre%20fix/%E5%BD%B1%E7%89%87.mp4?" in url


def test_presign_rejects_incomplete_config(storage):
    base = dict(bucket="b", key="k", region="auto", access_key="ak",
                secret_key="sk", expires=900)
    with pytest.raises(storage.OutputStorageError):
        storage.presign("PUT", endpoint="", **base)
    with pytest.raises(storage.OutputStorageError):
        storage.presign("PUT", endpoint="s3.example.com", **base)  # 沒有 scheme
    with pytest.raises(storage.OutputStorageError):
        storage.presign("PUT", endpoint="https://s3.example.com",
                        **{**base, "secret_key": ""})


# ----------------------------------------------------------------------
# 模式切換
# ----------------------------------------------------------------------

def test_off_by_default_keeps_legacy_path(storage):
    """未設定 → None,非 ZDR 帳號行為完全不變"""
    assert storage.get_upload_target() is None
    assert storage.is_configured() is False


def test_unknown_mode_falls_back_to_off(storage):
    os.environ["XAI_OUTPUT_STORAGE"] = "dropbox"
    assert storage.get_upload_target() is None
    assert storage.is_configured() is False


def test_s3_target_has_both_urls(storage):
    _set_s3()
    target = storage.get_upload_target()
    assert "X-Amz-Signature=" in target.upload_url
    assert "X-Amz-Signature=" in target.fetch_url
    assert target.upload_url != target.fetch_url   # PUT 與 GET 簽章不同
    assert target.label.startswith("s3://grok-out/grok-video/")
    assert "X-Amz" not in target.label             # label 可安全列印


def test_s3_key_is_unique_per_call(storage):
    """每次都是新 key,presigned PUT 不可能覆蓋既有檔案"""
    _set_s3()
    keys = {storage.get_upload_target().label for _ in range(5)}
    assert len(keys) == 5


def test_s3_expires_clamped(storage):
    _set_s3(XAI_OUTPUT_S3_EXPIRES_SECS="999999")
    assert "X-Amz-Expires=3600" in storage.get_upload_target().upload_url
    _set_s3(XAI_OUTPUT_S3_EXPIRES_SECS="1")
    assert "X-Amz-Expires=60" in storage.get_upload_target().upload_url
    _set_s3(XAI_OUTPUT_S3_EXPIRES_SECS="abc")
    assert "X-Amz-Expires=900" in storage.get_upload_target().upload_url


def test_static_mode(storage):
    os.environ.update({
        "XAI_OUTPUT_STORAGE": "static",
        "XAI_OUTPUT_UPLOAD_URL": "https://x.example.com/put?sig=abc",
        "XAI_OUTPUT_FETCH_URL": "https://x.example.com/get?sig=def",
    })
    target = storage.get_upload_target()
    assert target.upload_url == "https://x.example.com/put?sig=abc"
    assert target.fetch_url == "https://x.example.com/get?sig=def"
    assert "sig=abc" not in target.label


def test_static_mode_without_url_raises(storage):
    os.environ["XAI_OUTPUT_STORAGE"] = "static"
    with pytest.raises(storage.OutputStorageError):
        storage.get_upload_target()


# ----------------------------------------------------------------------
# 不洩漏機密
# ----------------------------------------------------------------------

def test_mask_url_strips_signature(storage):
    masked = storage.mask_url("https://h/k.mp4?X-Amz-Signature=deadbeef")
    assert "deadbeef" not in masked
    assert masked.startswith("https://h/k.mp4")
    assert storage.mask_url("") == ""
    assert storage.mask_url("https://h/k.mp4") == "https://h/k.mp4"


def test_scrub_removes_signature_params(storage):
    text = ("HTTPSConnectionPool: PUT https://h/k.mp4?X-Amz-Algorithm=AWS4"
            "&X-Amz-Credential=AKIALEAK%2F20261021&X-Amz-Signature=deadbeef1234")
    out = storage.scrub(text)
    assert "deadbeef1234" not in out
    assert "AKIALEAK" not in out
    assert "X-Amz-Algorithm=AWS4" in out   # 非機密參數保留,仍可除錯
    assert storage.scrub("") == ""


def test_download_error_does_not_leak_signature(storage):
    """requests 的例外訊息會自己帶完整網址,不可原封不動進 log"""
    api_mod = sys.modules[f"{PKG_NAME}.modules.grok_api"]
    requests_mod = sys.modules["requests"]
    url = "https://h/k.mp4?X-Amz-Signature=deadbeef1234"

    class Boom(api_mod.GrokAPI):
        def __init__(self):
            self.timeout = 1

    def fake_get(*a, **kw):
        raise requests_mod.RequestException(f"Max retries exceeded with url: {url}")

    orig = requests_mod.get
    requests_mod.get = fake_get
    try:
        with pytest.raises(api_mod.GrokAPIError) as got:
            Boom().download(url, "nowhere.mp4")
    finally:
        requests_mod.get = orig
    assert "deadbeef1234" not in str(got.value)


def test_api_error_detail_is_scrubbed(storage):
    """xAI 回拋我們送出的 upload_url 時也要遮蔽"""
    api_mod = sys.modules[f"{PKG_NAME}.modules.grok_api"]
    requests_mod = sys.modules["requests"]

    class Resp:
        status_code = 400

        def json(self):
            return {"error": {"message": "bad output.upload_url=https://h/k"
                                         "?X-Amz-Signature=deadbeef1234"}}

    orig = requests_mod.request
    requests_mod.request = lambda *a, **kw: Resp()
    try:
        api = api_mod.GrokAPI.__new__(api_mod.GrokAPI)
        api.api_key, api.base_url, api.timeout = "k", "https://api.x.ai/v1", 1
        with pytest.raises(api_mod.GrokAPIError) as got:
            api._request("POST", "/videos/generations", {})
    finally:
        requests_mod.request = orig
    assert "deadbeef1234" not in str(got.value)


def test_describe_hides_secrets(storage):
    _set_s3(XAI_OUTPUT_S3_SECRET_ACCESS_KEY="super-secret-value")
    text = storage.describe()
    assert "super-secret-value" not in text
    assert "AKIATESTTESTTESTTEST" not in text
    assert "grok-out" in text


def test_zdr_hint_is_actionable_and_clean(storage):
    _set_s3(XAI_OUTPUT_S3_SECRET_ACCESS_KEY="super-secret-value")
    hint = storage.zdr_setup_hint()
    assert "super-secret-value" not in hint
    assert "console.x.ai" in hint
    assert "XAI_OUTPUT_STORAGE=s3" in hint


# ----------------------------------------------------------------------
# API 層串接
# ----------------------------------------------------------------------

def test_submit_video_adds_output_only_when_given(storage):
    api_mod = sys.modules[f"{PKG_NAME}.modules.grok_api"]
    sent = {}

    class FakeAPI(api_mod.GrokAPI):
        def __init__(self):
            pass

        def _request(self, method, path, payload=None, timeout=None):
            sent["payload"] = payload
            return {"request_id": "req-1"}

    FakeAPI().submit_video("p", "m", duration=6)
    assert "output" not in sent["payload"]

    FakeAPI().submit_video("p", "m", duration=6,
                           upload_url="https://h/k.mp4?sig=1")
    assert sent["payload"]["output"] == {"upload_url": "https://h/k.mp4?sig=1"}


def test_poll_video_tolerates_missing_url_only_in_upload_mode(storage):
    api_mod = sys.modules[f"{PKG_NAME}.modules.grok_api"]

    class FakeAPI(api_mod.GrokAPI):
        def __init__(self):
            pass

        def _request(self, method, path, payload=None, timeout=None):
            return {"status": "done"}

    assert FakeAPI().poll_video("req-1", expect_upload=True) == ""
    with pytest.raises(api_mod.GrokAPIError):
        FakeAPI().poll_video("req-1", expect_upload=False)


def test_zdr_400_without_storage_gets_actionable_error(storage, capsys):
    """未設定儲存時,xAI 的原始訊息要被換成可行動的指引"""
    api_mod = sys.modules[f"{PKG_NAME}.modules.grok_api"]

    class FakeAPI(api_mod.GrokAPI):
        def __init__(self):
            pass

        def _request(self, method, path, payload=None, timeout=None):
            raise api_mod.GrokAPIError(
                "POST /videos/generations 失敗: Zero Data Retention teams "
                "must provide output.upload_url for video generation.",
                status=400)

    with pytest.raises(api_mod.GrokAPIError) as got:
        FakeAPI().submit_video("p", "m", duration=6)
    msg = str(got.value)
    # 例外訊息要一行講完:多行指引放進例外,節點那層再包一次、ComfyUI
    # 又印一遍鏈結 traceback,同一段會洗三遍(#5)
    assert len(msg.splitlines()) == 1, msg
    assert "console.x.ai" in msg
    assert "XAI_OUTPUT_STORAGE" in msg
    # 完整指引只印一次到主控台
    out = capsys.readouterr().out
    assert out.count("console.x.ai") == 1
    assert "XAI_OUTPUT_STORAGE=s3" in out


def test_non_zdr_400_is_not_rewritten(storage):
    """其他 400 不可被誤判成 ZDR"""
    api_mod = sys.modules[f"{PKG_NAME}.modules.grok_api"]

    class FakeAPI(api_mod.GrokAPI):
        def __init__(self):
            pass

        def _request(self, method, path, payload=None, timeout=None):
            raise api_mod.GrokAPIError("POST /videos/generations 失敗: "
                                       "unknown field 'foo'", status=400)

    with pytest.raises(api_mod.GrokAPIError) as got:
        FakeAPI().submit_video("p", "m", duration=6)
    assert "console.x.ai" not in str(got.value)
    assert "unknown field" in str(got.value)
