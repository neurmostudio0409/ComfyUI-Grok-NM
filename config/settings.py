"""
ComfyUI-Grok-NM 集中設定
所有常數、環境變數載入、節點分類都定義在這裡
"""

import os
import sys

# Windows 主控台可能是 cp950,emoji/中文輸出前先切 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ----------------------------------------------------------------------
# 路徑
# ----------------------------------------------------------------------
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(CONFIG_DIR)

# .env 搜尋順序:config/.env 優先,其次套件根目錄 .env
ENV_PATHS = [
    os.path.join(CONFIG_DIR, ".env"),
    os.path.join(PLUGIN_DIR, ".env"),
]

# ----------------------------------------------------------------------
# API Server 設定
# ----------------------------------------------------------------------
# xAI API(OpenAI 相容)。API key 從 https://console.x.ai → API Keys 取得
DEFAULT_BASE_URL = "https://api.x.ai/v1"

# 一般請求逾時(秒);影片輪詢另有專屬設定
REQUEST_TIMEOUT = 120

# ----------------------------------------------------------------------
# ComfyUI 節點分類
# ----------------------------------------------------------------------
CATEGORY_CHAT = "AI/Grok/chat"
CATEGORY_VISION = "AI/Grok/vision"
CATEGORY_IMAGE = "AI/Grok/image"
CATEGORY_VIDEO = "AI/Grok/video"
CATEGORY_AUDIO = "AI/Grok/audio"
CATEGORY_UTILS = "AI/Grok/utils"

# ----------------------------------------------------------------------
# 模型
# ----------------------------------------------------------------------
# GET /models 查詢失敗時的 fallback(2026-07 docs.x.ai/docs/models)
DEFAULT_CHAT_MODELS = [
    "grok-4.5",
    "grok-4.3",
    "grok-4.20-0309-reasoning",
    "grok-4.20-0309-non-reasoning",
    "grok-build-0.1",
]

# Grok Imagine 圖片生成(flat per-image 計價)
IMAGE_MODELS = [
    "grok-imagine-image",          # $0.02/張
    "grok-imagine-image-quality",  # $0.05/張
]

# Grok Imagine 影片生成(per-second 計價,非同步 + 輪詢)
VIDEO_MODELS = [
    "grok-imagine-video-1.5",  # $0.08/秒
    "grok-imagine-video",      # $0.05/秒,支援參考圖工作流
]

# ----------------------------------------------------------------------
# TTS(Voice API,POST /tts 回傳原始音訊 bytes)
# ----------------------------------------------------------------------
TTS_VOICES = ["eve", "ara", "leo", "rex", "sal"]  # 內建聲音,custom voice 填自訂欄位
MAX_TTS_TEXT_LENGTH = 15000
TTS_SPEED_MIN = 0.7
TTS_SPEED_MAX = 1.5

# 要求 WAV 方便在記憶體直接解碼成 AUDIO tensor(不落地)。
# 若 API 回 400/422 表示欄位名稱有異動,依 docs.x.ai TTS output_format 章節調整。
TTS_OUTPUT_FORMAT = {"codec": "wav", "sample_rate": 24000}

# ----------------------------------------------------------------------
# 限制(送出前就在本地擋下,不浪費 API 呼叫)
# ----------------------------------------------------------------------
MAX_IMAGES_PER_REQUEST = 10        # /images/generations 單次上限
MAX_VIDEO_DURATION_SEC = 15        # 影片長度上限(秒)
MAX_REFERENCE_IMAGES = 8           # 參考圖生影片軟上限(官方未明訂,範例最多 3)
MAX_EDIT_IMAGES = 3                # /images/edits 來源圖上限(官方明訂最多 3)
MAX_IMAGE_INPUT_BYTES = 20 * 1024 * 1024  # 視覺輸入單張上限 20 MiB

ASPECT_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]
VIDEO_RESOLUTIONS = ["720p", "480p", "1080p"]

# 影片非同步輪詢
VIDEO_POLL_INTERVAL = 5.0    # 秒
VIDEO_POLL_TIMEOUT = 600.0   # 秒

# ----------------------------------------------------------------------
# 影片輸出儲存(Zero Data Retention 團隊帳號用)
# ----------------------------------------------------------------------
# ZDR 團隊下 xAI 不保存生成結果,影片必須 PUT 到呼叫方自備的 presigned
# 網址。未設定時維持原本「xAI 代管下載網址」流程,非 ZDR 帳號不受影響。
OUTPUT_STORAGE_MODES = ["off", "s3", "static"]
OUTPUT_S3_DEFAULT_KEY_PREFIX = "grok-video/"
OUTPUT_S3_DEFAULT_REGION = "auto"      # R2 用 auto;AWS S3 要填實際 region
OUTPUT_S3_EXPIRES_DEFAULT = 900        # 秒,與 xAI 官方 Grok Build 預設一致
OUTPUT_S3_EXPIRES_MIN = 60
OUTPUT_S3_EXPIRES_MAX = 3600

# ----------------------------------------------------------------------
# HTTP 狀態碼提示
# ----------------------------------------------------------------------
HTTP_STATUS_HINTS = {
    400: "請求格式錯誤(參數名稱或值不被接受)",
    401: "XAI_API_KEY 無效或未設定",
    403: "沒有使用此 model 的權限,或帳戶額度不足",
    404: "找不到資源,URL 錯誤或 request_id 不存在",
    422: "參數驗證失敗",
    429: "超過 rate limit,請稍後再試",
    500: "xAI 伺服器發生未知錯誤",
    503: "xAI 伺服器目前無法處理請求",
}

_PLACEHOLDER = "<paste-your-key-here>"


# ----------------------------------------------------------------------
# 環境變數載入
# ----------------------------------------------------------------------
def load_env(verbose: bool = False) -> bool:
    """
    從 ENV_PATHS 載入 XAI_API_KEY / XAI_API_URL 到環境變數。
    優先使用 python-dotenv,無則手動解析。

    Returns:
        bool: 是否成功取得 XAI_API_KEY
    """
    try:
        from dotenv import load_dotenv
        for path in ENV_PATHS:
            if os.path.exists(path):
                load_dotenv(path)
    except ImportError:
        for path in ENV_PATHS:
            _parse_env_file(path)

    key = os.environ.get("XAI_API_KEY", "")
    if key == _PLACEHOLDER:
        os.environ.pop("XAI_API_KEY", None)
        key = ""

    if verbose:
        if key:
            print("✅ 已載入 xAI API key")
        else:
            print("⚠️ XAI_API_KEY 未配置")
            print("   請複製 config/.env.example 為 config/.env 並設定 XAI_API_KEY")
    return bool(key)


def _parse_env_file(path: str):
    """簡易 .env 解析(python-dotenv 不可用時的保底)"""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("\"'")
                if value and value != _PLACEHOLDER:
                    os.environ.setdefault(key, value)
    except Exception as e:
        print(f"❌ 解析 {path} 時發生錯誤: {e}")


def get_api_key() -> str:
    """取得 API Key(空字串表示未設定)"""
    return os.environ.get("XAI_API_KEY", "")


def get_base_url() -> str:
    """取得 API Server 位置"""
    return (os.environ.get("XAI_API_URL") or DEFAULT_BASE_URL).rstrip("/")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def get_output_storage_mode() -> str:
    """
    影片輸出儲存模式:off / s3 / static

    未設定或填了不認得的值一律當 off(走 xAI 代管下載網址的原路徑)。
    """
    mode = (os.environ.get("XAI_OUTPUT_STORAGE") or "off").strip().lower()
    return mode if mode in OUTPUT_STORAGE_MODES else "off"


def get_output_s3_config() -> dict:
    """S3 相容儲存設定(AWS S3 / Cloudflare R2 / MinIO)"""
    return {
        "endpoint": (os.environ.get("XAI_OUTPUT_S3_ENDPOINT") or "").strip().rstrip("/"),
        "bucket": (os.environ.get("XAI_OUTPUT_S3_BUCKET") or "").strip(),
        "region": (os.environ.get("XAI_OUTPUT_S3_REGION") or "").strip()
                  or OUTPUT_S3_DEFAULT_REGION,
        "access_key_id": (os.environ.get("XAI_OUTPUT_S3_ACCESS_KEY_ID") or "").strip(),
        "secret_access_key": os.environ.get("XAI_OUTPUT_S3_SECRET_ACCESS_KEY") or "",
        "key_prefix": (os.environ.get("XAI_OUTPUT_S3_KEY_PREFIX") or "").strip()
                      or OUTPUT_S3_DEFAULT_KEY_PREFIX,
        "expires_secs": os.environ.get("XAI_OUTPUT_S3_EXPIRES_SECS")
                        or OUTPUT_S3_EXPIRES_DEFAULT,
        # R2 / MinIO 走 path-style;AWS S3 要 virtual-host 時設為 false
        "force_path_style": _env_bool("XAI_OUTPUT_S3_FORCE_PATH_STYLE", True),
    }


def get_output_static_urls() -> tuple:
    """
    固定 presigned 網址(單次測試用),回傳 (upload_url, fetch_url)

    同一組網址重複使用會互相覆蓋,正式用途請走 s3 模式。
    """
    return (
        (os.environ.get("XAI_OUTPUT_UPLOAD_URL") or "").strip(),
        (os.environ.get("XAI_OUTPUT_FETCH_URL") or "").strip(),
    )
