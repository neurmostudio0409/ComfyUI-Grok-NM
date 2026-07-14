"""
xAI Grok ComfyUI 節點
分類:
  AI/Grok/chat   — GrokChatNode
  AI/Grok/vision — GrokVisionNode
  AI/Grok/image  — GrokImageGenNode
  AI/Grok/video  — GrokVideoGenNode
  AI/Grok/utils  — GrokListModelsNode
"""

import os

from ..config.settings import (
    ASPECT_RATIOS,
    CATEGORY_CHAT,
    CATEGORY_IMAGE,
    CATEGORY_UTILS,
    CATEGORY_VIDEO,
    CATEGORY_VISION,
    DEFAULT_CHAT_MODELS,
    IMAGE_MODELS,
    MAX_IMAGES_PER_REQUEST,
    MAX_VIDEO_DURATION_SEC,
    VIDEO_MODELS,
    VIDEO_POLL_TIMEOUT,
    VIDEO_RESOLUTIONS,
)
from .grok_api import GrokAPI, GrokAPIError
from . import media_utils

# 全域變數:快取 chat 模型列表(避免每次開節點都打 API)
_CACHED_CHAT_MODELS = None


def get_chat_model_list():
    """從 GET /models 取得 chat 模型(排除 imagine 生成模型),失敗用 fallback"""
    global _CACHED_CHAT_MODELS

    if _CACHED_CHAT_MODELS is not None:
        return _CACHED_CHAT_MODELS

    try:
        api = GrokAPI()
        models = [m for m in api.get_models() if "imagine" not in m]
        if models:
            _CACHED_CHAT_MODELS = models
            print(f"✅ 已載入 {len(models)} 個 Grok chat 模型")
            return models
    except Exception as e:
        print(f"⚠️ 無法取得 Grok 模型列表: {e}")

    _CACHED_CHAT_MODELS = DEFAULT_CHAT_MODELS
    print(f"⚠️ 使用預設模型列表 ({len(DEFAULT_CHAT_MODELS)} 個)")
    return DEFAULT_CHAT_MODELS


def _print_api_key_help():
    print("\n請確保:")
    print("1. 複製 config/.env.example 為 config/.env")
    print("2. 在 config/.env 中設定 XAI_API_KEY(https://console.x.ai → API Keys)")
    print("3. 重啟 ComfyUI")


def _common_llm_options():
    return {
        "system_prompt": ("STRING", {
            "default": "",
            "multiline": True,
            "tooltip": "系統提示(留空則不送 system role)",
        }),
        "temperature": ("FLOAT", {
            "default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05,
            "tooltip": "隨機性 0~2,越高越發散",
        }),
        "max_tokens": ("INT", {
            "default": 0, "min": 0, "max": 131072,
            "tooltip": "輸出 token 上限(0 = 不限制)",
        }),
        "seed": ("INT", {
            "default": 0, "min": 0, "max": 2**31 - 1,
            "tooltip": "隨機種子(0 = 不指定)",
        }),
    }


# ======================
# Chat / Vision 節點
# ======================

class GrokChatNode:
    """ComfyUI 節點:Grok 文字對話(chat completions)"""

    @classmethod
    def INPUT_TYPES(cls):
        models = get_chat_model_list()
        return {
            "required": {
                "prompt": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "使用者提示詞",
                }),
                "model": (models, {
                    "default": models[0] if models else "grok-4.5",
                    "tooltip": "chat 模型(從 xAI API 動態載入)",
                }),
            },
            "optional": _common_llm_options(),
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "generate"
    CATEGORY = CATEGORY_CHAT

    def generate(self, prompt, model, system_prompt="", temperature=1.0,
                 max_tokens=0, seed=0):
        try:
            api = GrokAPI()
            text = api.chat_text(
                prompt, model,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                seed=seed,
            )
            print(f"✅ Grok 回應 {len(text)} 字元")
            return (text,)
        except ValueError as e:
            _print_api_key_help()
            raise RuntimeError(str(e)) from e
        except GrokAPIError as e:
            raise RuntimeError(str(e)) from e


class GrokVisionNode:
    """ComfyUI 節點:Grok 視覺理解(IMAGE + 提示詞 → 文字)"""

    @classmethod
    def INPUT_TYPES(cls):
        models = get_chat_model_list()
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "要分析的圖片(batch 最多送 8 張)"}),
                "prompt": ("STRING", {
                    "default": "描述這張圖片。",
                    "multiline": True,
                    "tooltip": "對圖片的提問",
                }),
                "model": (models, {
                    "default": models[0] if models else "grok-4.5",
                    "tooltip": "支援影像輸入的 chat 模型",
                }),
            },
            "optional": {
                "detail": (["auto", "high", "low"], {
                    "default": "auto",
                    "tooltip": "影像解析細節等級",
                }),
                **_common_llm_options(),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "analyze"
    CATEGORY = CATEGORY_VISION

    def analyze(self, image, prompt, model, detail="auto", system_prompt="",
                temperature=1.0, max_tokens=0, seed=0):
        try:
            b64_list = media_utils.batch_to_png_b64_list(image)
            api = GrokAPI()
            text = api.chat_vision(
                prompt, b64_list, model,
                system_prompt=system_prompt,
                detail=detail,
                temperature=temperature,
                max_tokens=max_tokens,
                seed=seed,
            )
            print(f"✅ Grok 視覺分析完成({len(b64_list)} 張圖)")
            return (text,)
        except ValueError as e:
            _print_api_key_help()
            raise RuntimeError(str(e)) from e
        except GrokAPIError as e:
            raise RuntimeError(str(e)) from e


# ======================
# 圖片生成節點
# ======================

class GrokImageGenNode:
    """ComfyUI 節點:Grok Imagine 文生圖"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "圖片描述提示詞",
                }),
                "model": (IMAGE_MODELS, {
                    "default": IMAGE_MODELS[0],
                    "tooltip": "grok-imagine-image($0.02/張)或 -quality($0.05/張)",
                }),
                "n": ("INT", {
                    "default": 1, "min": 1, "max": MAX_IMAGES_PER_REQUEST,
                    "tooltip": f"一次生成張數(上限 {MAX_IMAGES_PER_REQUEST})",
                }),
            },
            "optional": {
                "aspect_ratio": (["(預設)"] + ASPECT_RATIOS, {
                    "default": "(預設)",
                    "tooltip": "長寬比,(預設) = 交給 API 決定",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "generate"
    CATEGORY = CATEGORY_IMAGE

    def generate(self, prompt, model, n=1, aspect_ratio="(預設)"):
        try:
            api = GrokAPI()
            ar = "" if aspect_ratio.startswith("(") else aspect_ratio
            items = api.generate_images(
                prompt, model, n=n, aspect_ratio=ar, response_format="b64_json")
            batch = media_utils.items_to_image_batch(items)
            print("=" * 60)
            print(f"✅ Grok Imagine 生成 {batch.shape[0]} 張圖片")
            print("=" * 60)
            return (batch,)
        except ValueError as e:
            _print_api_key_help()
            raise RuntimeError(str(e)) from e
        except GrokAPIError as e:
            raise RuntimeError(str(e)) from e


# ======================
# 影片生成節點
# ======================

class GrokVideoGenNode:
    """ComfyUI 節點:Grok Imagine 文生影片 / 圖生影片(非同步 + 輪詢)"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "影片內容描述",
                }),
                "model": (VIDEO_MODELS, {
                    "default": VIDEO_MODELS[0],
                    "tooltip": "grok-imagine-video-1.5($0.08/秒)或 grok-imagine-video($0.05/秒,支援參考圖)",
                }),
                "duration": ("INT", {
                    "default": 6, "min": 1, "max": MAX_VIDEO_DURATION_SEC,
                    "tooltip": f"影片長度(秒,上限 {MAX_VIDEO_DURATION_SEC})",
                }),
            },
            "optional": {
                "first_frame": ("IMAGE", {
                    "tooltip": "圖生影片的參考圖(取 batch 第一張)",
                }),
                "aspect_ratio": (["(預設)"] + ASPECT_RATIOS, {
                    "default": "(預設)",
                }),
                "resolution": (["(預設)"] + VIDEO_RESOLUTIONS, {
                    "default": "(預設)",
                }),
                "poll_timeout": ("FLOAT", {
                    "default": VIDEO_POLL_TIMEOUT, "min": 60.0, "max": 3600.0,
                    "tooltip": "輪詢逾時(秒)",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_path", "video_url")
    FUNCTION = "generate"
    CATEGORY = CATEGORY_VIDEO
    OUTPUT_NODE = True

    def generate(self, prompt, model, duration=6, first_frame=None,
                 aspect_ratio="(預設)", resolution="(預設)",
                 poll_timeout=VIDEO_POLL_TIMEOUT):
        try:
            api = GrokAPI()

            image_data_url = ""
            if first_frame is not None:
                b64 = media_utils.tensor_to_png_b64(first_frame, 0)
                image_data_url = f"data:image/png;base64,{b64}"
                print("🖼️ 使用參考圖進行圖生影片")

            ar = "" if aspect_ratio.startswith("(") else aspect_ratio
            res = "" if resolution.startswith("(") else resolution

            request_id = api.submit_video(
                prompt, model,
                image_data_url=image_data_url,
                duration=duration,
                aspect_ratio=ar,
                resolution=res,
            )
            print(f"🚀 影片任務已送出 request_id={request_id}")

            url = api.poll_video(request_id, timeout=poll_timeout)
            dest = media_utils.make_video_path()
            api.download(url, dest)

            print("=" * 60)
            print("✅ 影片生成完成!")
            print(f"📁 輸出: {dest}")
            print("=" * 60)
            return (dest, url)
        except ValueError as e:
            _print_api_key_help()
            raise RuntimeError(str(e)) from e
        except GrokAPIError as e:
            raise RuntimeError(str(e)) from e


# ======================
# 工具節點
# ======================

class GrokListModelsNode:
    """ComfyUI 節點:查詢帳戶可用的 xAI 模型列表"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "refresh": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "重新從 API 抓取(同時更新 chat 節點的下拉快取)",
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("models",)
    FUNCTION = "list_models"
    CATEGORY = CATEGORY_UTILS

    def list_models(self, refresh=False):
        global _CACHED_CHAT_MODELS
        try:
            api = GrokAPI()
            models = api.get_models()
            if refresh:
                _CACHED_CHAT_MODELS = None
            text = "\n".join(models)
            print(f"✅ 帳戶共有 {len(models)} 個模型")
            return (text,)
        except ValueError as e:
            _print_api_key_help()
            raise RuntimeError(str(e)) from e
        except GrokAPIError as e:
            raise RuntimeError(str(e)) from e


# ======================
# 節點註冊
# ======================

NODE_CLASS_MAPPINGS = {
    "GrokChatNode": GrokChatNode,
    "GrokVisionNode": GrokVisionNode,
    "GrokImageGenNode": GrokImageGenNode,
    "GrokVideoGenNode": GrokVideoGenNode,
    "GrokListModelsNode": GrokListModelsNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "GrokChatNode": "Grok Chat 文字對話 (xAI)",
    "GrokVisionNode": "Grok Vision 視覺理解 (xAI)",
    "GrokImageGenNode": "Grok Imagine 圖片生成 (xAI)",
    "GrokVideoGenNode": "Grok Imagine 影片生成 (xAI)",
    "GrokListModelsNode": "Grok 模型列表 (xAI)",
}
