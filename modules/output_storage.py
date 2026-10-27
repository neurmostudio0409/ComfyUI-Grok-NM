"""
影片輸出儲存(Zero Data Retention 專用)

ZDR(Zero Data Retention)團隊帳號下 xAI 不保存生成結果,影片不會有代管的
下載網址,必須由呼叫方先提供一個 presigned 上傳網址,xAI 再以 HTTP PUT 把
成品直接推進該位置,自己不留副本。

本模組負責「每次生成各自產生一組一次性網址」:
  upload_url — 交給 xAI 寫入(PUT)
  fetch_url  — 本機取回影片用(GET)

未設定任何儲存時 get_upload_target() 回傳 None,呼叫端即維持原本
「xAI 代管下載網址」的流程,所以非 ZDR 帳號的行為完全不變。

SigV4 簽章以標準庫 hmac / hashlib 實作,刻意不為此引入 boto3:
ComfyUI 外掛應避免拖進重量級依賴。

安全注意:presigned 網址本身就是該物件的通行證(含簽章),列印到主控台前
務必先用 mask_url() 去掉 query string。S3 金鑰只從 .env 讀,不會送往 xAI。
"""

import datetime
import hashlib
import hmac
import re
import urllib.parse
import uuid

from ..config.settings import (
    OUTPUT_S3_DEFAULT_KEY_PREFIX,
    OUTPUT_S3_EXPIRES_DEFAULT,
    OUTPUT_S3_EXPIRES_MAX,
    OUTPUT_S3_EXPIRES_MIN,
    get_output_storage_mode,
    get_output_static_urls,
    get_output_s3_config,
)

_ALGORITHM = "AWS4-HMAC-SHA256"
_UNSIGNED_PAYLOAD = "UNSIGNED-PAYLOAD"
_SERVICE = "s3"

# RFC 3986 unreserved,SigV4 要求其餘字元一律 percent-encode
_UNRESERVED = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
               "abcdefghijklmnopqrstuvwxyz"
               "0123456789-._~")


class OutputStorageError(Exception):
    """輸出儲存設定或簽章錯誤"""


class UploadTarget:
    """一次性的上傳 / 取回網址組合"""

    def __init__(self, upload_url: str, fetch_url: str, label: str):
        self.upload_url = upload_url
        self.fetch_url = fetch_url
        # label 是可安全列印的位置描述(如 s3://bucket/key),不含簽章
        self.label = label


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------
def mask_url(url: str) -> str:
    """去掉 query string 後的網址,可安全寫進 log / 主控台"""
    if not url:
        return ""
    base = url.split("?", 1)[0]
    return f"{base}?<已遮蔽簽章>" if "?" in url else base


# 任意文字中的簽章 / 憑證參數(requests 的例外訊息會自己帶上完整網址)
_SECRET_PARAM_RE = re.compile(
    r"\b(X-Amz-Signature|X-Amz-Credential|Signature|sig|token)=[^&\s\"'\\]+",
    re.IGNORECASE)


def scrub(text: str) -> str:
    """遮蔽任意文字裡的簽章 / 憑證參數,供錯誤訊息與 log 使用"""
    if not text:
        return ""
    return _SECRET_PARAM_RE.sub(lambda m: f"{m.group(1)}=<已遮蔽>", text)


def _uri_encode(text: str, encode_slash: bool = True) -> str:
    out = []
    for ch in text:
        if ch in _UNRESERVED:
            out.append(ch)
        elif ch == "/" and not encode_slash:
            out.append("/")
        else:
            out.extend("%%%02X" % b for b in ch.encode("utf-8"))
    return "".join(out)


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, date_stamp: str, region: str) -> bytes:
    k = _sign(("AWS4" + secret).encode("utf-8"), date_stamp)
    k = _sign(k, region)
    k = _sign(k, _SERVICE)
    return _sign(k, "aws4_request")


def presign(method: str, endpoint: str, bucket: str, key: str, region: str,
            access_key: str, secret_key: str, expires: int,
            force_path_style: bool = True, now=None) -> str:
    """
    產生 SigV4 query-string presigned 網址(S3 / R2 / MinIO 通用)

    只簽 host 與 UNSIGNED-PAYLOAD,刻意不簽 Content-Type —— xAI PUT 上來時
    帶什麼 Content-Type 官方未公開,簽進去會讓簽章失效。
    now 僅供測試注入固定時間。
    """
    if not endpoint:
        raise OutputStorageError("S3 endpoint 未設定")
    if not bucket:
        raise OutputStorageError("S3 bucket 未設定")
    if not access_key or not secret_key:
        raise OutputStorageError("S3 存取金鑰未設定")

    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    parsed = urllib.parse.urlsplit(endpoint)
    if not parsed.netloc:
        raise OutputStorageError(
            f"S3 endpoint 必須是完整網址(含 https://),收到 {endpoint!r}")
    scheme = parsed.scheme or "https"
    host = parsed.netloc
    base_path = parsed.path.rstrip("/")

    enc_key = _uri_encode(key, encode_slash=False)
    if force_path_style:
        canonical_uri = f"{base_path}/{_uri_encode(bucket)}/{enc_key}"
    else:
        host = f"{bucket}.{host}"
        canonical_uri = f"{base_path}/{enc_key}"

    credential_scope = f"{date_stamp}/{region}/{_SERVICE}/aws4_request"
    params = {
        "X-Amz-Algorithm": _ALGORITHM,
        "X-Amz-Credential": f"{access_key}/{credential_scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(int(expires)),
        "X-Amz-SignedHeaders": "host",
    }
    canonical_qs = "&".join(
        f"{_uri_encode(k)}={_uri_encode(v)}"
        for k, v in sorted(params.items()))

    canonical_request = "\n".join([
        method.upper(),
        canonical_uri,
        canonical_qs,
        f"host:{host}\n",
        "host",
        _UNSIGNED_PAYLOAD,
    ])
    string_to_sign = "\n".join([
        _ALGORITHM,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    signature = hmac.new(
        _signing_key(secret_key, date_stamp, region),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return (f"{scheme}://{host}{canonical_uri}"
            f"?{canonical_qs}&X-Amz-Signature={signature}")


# ----------------------------------------------------------------------
# 對外介面
# ----------------------------------------------------------------------
def is_configured() -> bool:
    """是否已設定自備輸出儲存"""
    return get_output_storage_mode() in ("s3", "static")


def describe() -> str:
    """設定摘要,只含非機密資訊,供錯誤訊息引用"""
    mode = get_output_storage_mode()
    if mode == "s3":
        cfg = get_output_s3_config()
        return (f"s3(endpoint={cfg['endpoint'] or '未設定'}, "
                f"bucket={cfg['bucket'] or '未設定'}, "
                f"region={cfg['region']})")
    if mode == "static":
        upload, fetch = get_output_static_urls()
        return (f"static(upload={mask_url(upload) or '未設定'}, "
                f"fetch={mask_url(fetch) or '未設定'})")
    return "off(未設定自備儲存)"


def _normalize_expires(raw) -> int:
    try:
        secs = int(raw)
    except (TypeError, ValueError):
        secs = OUTPUT_S3_EXPIRES_DEFAULT
    return max(OUTPUT_S3_EXPIRES_MIN, min(OUTPUT_S3_EXPIRES_MAX, secs))


def get_upload_target(ext: str = "mp4") -> UploadTarget:
    """
    產生這次生成專用的上傳 / 取回網址;未設定自備儲存則回傳 None

    每次呼叫都產生新的 object key(含 uuid4),所以 presigned PUT 無法
    覆蓋任何既有檔案。
    """
    mode = get_output_storage_mode()

    if mode == "static":
        upload, fetch = get_output_static_urls()
        if not upload:
            raise OutputStorageError(
                "XAI_OUTPUT_STORAGE=static 但 XAI_OUTPUT_UPLOAD_URL 未設定")
        # static 模式是單次測試用:同一個網址重複使用會互相覆蓋
        return UploadTarget(upload, fetch or upload, mask_url(upload))

    if mode != "s3":
        return None

    cfg = get_output_s3_config()
    prefix = (cfg["key_prefix"] or OUTPUT_S3_DEFAULT_KEY_PREFIX).lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    key = f"{prefix}{stamp}/{uuid.uuid4().hex}.{ext.lstrip('.')}"

    expires = _normalize_expires(cfg["expires_secs"])
    common = dict(
        endpoint=cfg["endpoint"],
        bucket=cfg["bucket"],
        key=key,
        region=cfg["region"],
        access_key=cfg["access_key_id"],
        secret_key=cfg["secret_access_key"],
        expires=expires,
        force_path_style=cfg["force_path_style"],
    )
    return UploadTarget(
        upload_url=presign("PUT", **common),
        fetch_url=presign("GET", **common),
        label=f"s3://{cfg['bucket']}/{key}",
    )


def zdr_setup_hint() -> str:
    """ZDR 擋下請求但未設定儲存時,給使用者的可行動指引"""
    return (
        "這個 xAI 團隊帳號開了 Zero Data Retention(ZDR),xAI 不會保存生成的\n"
        "影片,必須由你提供一個可寫入的 presigned 網址讓它 PUT 上去。\n"
        "ZDR 是 team 層級設定,無法只對單一 API key 關閉。\n"
        "\n"
        "二選一:\n"
        "  (A) 到 https://console.x.ai 關閉該 team 的 ZDR —— 不必改任何設定\n"
        "  (B) 自備 S3 相容儲存(AWS S3 / Cloudflare R2 / MinIO),在 .env 填:\n"
        "        XAI_OUTPUT_STORAGE=s3\n"
        "        XAI_OUTPUT_S3_ENDPOINT=https://<帳號>.r2.cloudflarestorage.com\n"
        "        XAI_OUTPUT_S3_BUCKET=<bucket 名稱>\n"
        "        XAI_OUTPUT_S3_REGION=auto\n"
        "        XAI_OUTPUT_S3_ACCESS_KEY_ID=<access key>\n"
        "        XAI_OUTPUT_S3_SECRET_ACCESS_KEY=<secret key>\n"
        "      填好後重啟 ComfyUI。詳見 README「ZDR 團隊帳號」章節。\n"
        f"\n目前設定:{describe()}"
    )
