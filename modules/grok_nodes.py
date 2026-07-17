"""
xAI Grok ComfyUI 節點
分類:
  AI/Grok/chat   — GrokChatNode
  AI/Grok/vision — GrokVisionNode
  AI/Grok/image  — GrokImageGenNode
  AI/Grok/video  — GrokVideoGenNode
  AI/Grok/audio  — GrokTTSNode
  AI/Grok/utils  — GrokListModelsNode

設計原則:生成節點一律輸出型別(IMAGE / VIDEO / AUDIO),不自行寫檔——
保存交給下游 Save Image / Save Video / Save Audio,避免重複落地。
"""

import os

from ..config.settings import (
    ASPECT_RATIOS,
    CATEGORY_AUDIO,
    CATEGORY_CHAT,
    CATEGORY_IMAGE,
    CATEGORY_UTILS,
    CATEGORY_VIDEO,
    CATEGORY_VISION,
    DEFAULT_CHAT_MODELS,
    IMAGE_MODELS,
    MAX_IMAGES_PER_REQUEST,
    MAX_REFERENCE_IMAGES,
    MAX_TTS_TEXT_LENGTH,
    MAX_VIDEO_DURATION_SEC,
    TTS_SPEED_MAX,
    TTS_SPEED_MIN,
    TTS_VOICES,
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

    # 只輸出 VIDEO 交給下游 Save Video / Preview Video,本節點不寫 output/
    RETURN_TYPES = ("VIDEO", "STRING")
    RETURN_NAMES = ("video", "video_url")
    FUNCTION = "generate"
    CATEGORY = CATEGORY_VIDEO

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
            dest = media_utils.make_video_temp_path()
            api.download(url, dest)
            video = media_utils.wrap_video(dest)

            print("=" * 60)
            print("✅ 影片生成完成!")
            print(f"📁 暫存: {dest}(保存請接 Save Video 節點)")
            print("=" * 60)
            return (video, url)
        except ValueError as e:
            _print_api_key_help()
            raise RuntimeError(str(e)) from e
        except GrokAPIError as e:
            raise RuntimeError(str(e)) from e


class GrokVideoRefsNode:
    """
    ComfyUI 節點:Grok Imagine 參考圖影片(多張參考圖,官方 reference_images)
    參考圖影響風格與內容但不強制第一幀;僅 grok-imagine-video 支援
    """

    # 單一孔位吃多圖:INPUT_IS_LIST 讓 reference_images 以「list」進來——
    # 上游是同尺寸 batch 時 list 只有一個 tensor(取全部幀);
    # 上游是 image list(GrokImageListNode / Impact Make Image List 等
    # OUTPUT_IS_LIST 節點)時,list 內多個 tensor 尺寸可各自不同。
    INPUT_IS_LIST = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "reference_images": ("IMAGE", {
                    "tooltip": "參考圖(單一孔位):同尺寸 batch 直接接;"
                               "不同尺寸多圖請經「Grok 參考圖打包」或 "
                               f"Make Image List 打包後接入(總上限 {MAX_REFERENCE_IMAGES} 張)",
                }),
                "prompt": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "影片內容描述",
                }),
                "duration": ("INT", {
                    "default": 6, "min": 1, "max": MAX_VIDEO_DURATION_SEC,
                    "tooltip": f"影片長度(秒,上限 {MAX_VIDEO_DURATION_SEC})",
                }),
            },
            "optional": {
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

    # 模型固定 grok-imagine-video(1.5 不支援 reference_images)
    RETURN_TYPES = ("VIDEO", "STRING")
    RETURN_NAMES = ("video", "video_url")
    FUNCTION = "generate"
    CATEGORY = CATEGORY_VIDEO

    def generate(self, reference_images, prompt, duration,
                 aspect_ratio=None, resolution=None, poll_timeout=None):
        # INPUT_IS_LIST:所有參數都以 list 進來,純量參數取第一個
        prompt = prompt[0]
        duration = duration[0]
        aspect_ratio = (aspect_ratio or ["(預設)"])[0]
        resolution = (resolution or ["(預設)"])[0]
        poll_timeout = (poll_timeout or [VIDEO_POLL_TIMEOUT])[0]

        try:
            api = GrokAPI()

            # reference_images 是 tensor list(各項尺寸可不同,各項本身是 batch)
            b64_list = []
            for idx, tensor in enumerate(reference_images or [], 1):
                if tensor is None:
                    continue
                if float(tensor.max()) == 0.0:
                    print(f"⚠️ 第 {idx} 項參考圖是全黑圖(疑似上游合批失敗的"
                          f" zero tensor),仍照送但請檢查上游")
                remain = MAX_REFERENCE_IMAGES - len(b64_list)
                if remain <= 0:
                    print(f"⚠️ 參考圖超過 {MAX_REFERENCE_IMAGES} 張上限,其餘略過")
                    break
                b64_list += media_utils.batch_to_png_b64_list(tensor, limit=remain)
            if not b64_list:
                raise RuntimeError("沒有任何參考圖:reference_images 是空的")

            ref_urls = [f"data:image/png;base64,{b}" for b in b64_list]
            print(f"🖼️ 參考圖 {len(ref_urls)} 張(reference_images,不強制第一幀)")

            ar = "" if aspect_ratio.startswith("(") else aspect_ratio
            res = "" if resolution.startswith("(") else resolution

            request_id = api.submit_video(
                prompt, "grok-imagine-video",
                duration=duration,
                aspect_ratio=ar,
                resolution=res,
                reference_image_urls=ref_urls,
            )
            print(f"🚀 影片任務已送出 request_id={request_id}")

            url = api.poll_video(request_id, timeout=poll_timeout)
            dest = media_utils.make_video_temp_path(prefix="grok_refs_video")
            api.download(url, dest)
            video = media_utils.wrap_video(dest)

            print("=" * 60)
            print("✅ 參考圖影片生成完成!")
            print(f"📁 暫存: {dest}(保存請接 Save Video 節點)")
            print("=" * 60)
            return (video, url)
        except ValueError as e:
            _print_api_key_help()
            raise RuntimeError(str(e)) from e
        except GrokAPIError as e:
            raise RuntimeError(str(e)) from e


class GrokMultiImageNode:
    """
    ComfyUI 節點:Grok 多圖上傳——介面仿 MultiImageLoader
    (Upload Images / Remove All / 編號縮圖),輸出跨尺寸 image list,
    一條線接「參考圖影片・多圖」的 reference_images 孔位
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_paths": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "(由前端維護)每行一個 input 目錄相對路徑",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("image_list", "count")
    OUTPUT_IS_LIST = (True, False)
    FUNCTION = "load"
    CATEGORY = CATEGORY_UTILS

    def load(self, image_paths):
        rels = [p.strip() for p in (image_paths or "").splitlines() if p.strip()]
        tensors = media_utils.load_image_list(rels)
        if not tensors:
            raise RuntimeError("沒有可載入的圖片:請用節點上的「Upload Images」上傳")
        print(f"🖼️ Grok 多圖上傳:載入 {len(tensors)} 張(各自原尺寸)")
        return (tensors, len(tensors))


class GrokImageListNode:
    """
    ComfyUI 節點:參考圖打包——多張不同尺寸的圖打包成 image list,
    一條線接進參考圖影片節點的單一孔位(OUTPUT_IS_LIST)
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_1": ("IMAGE", {"tooltip": "第 1 張(尺寸不限)"}),
            },
            "optional": {
                f"image_{i}": ("IMAGE", {"tooltip": f"第 {i} 張(尺寸不限)"})
                for i in range(2, MAX_REFERENCE_IMAGES + 1)
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image_list",)
    OUTPUT_IS_LIST = (True,)
    FUNCTION = "collect"
    CATEGORY = CATEGORY_UTILS

    def collect(self, image_1, **kwargs):
        images = [image_1]
        for i in range(2, MAX_REFERENCE_IMAGES + 1):
            img = kwargs.get(f"image_{i}")
            if img is not None:
                images.append(img)
        print(f"📦 參考圖打包:{len(images)} 張(尺寸可各自不同)")
        return (images,)


# ======================
# 音訊節點
# ======================

class GrokTTSNode:
    """ComfyUI 節點:Grok Voice 文字轉語音(記憶體解碼,不落地)"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": f"要合成的文字(上限 {MAX_TTS_TEXT_LENGTH} 字元,可含 speech tags)",
                }),
                "voice_id": (TTS_VOICES, {
                    "default": "eve",
                    "tooltip": "內建聲音;要用 custom voice 請填下方 custom_voice_id",
                }),
            },
            "optional": {
                "custom_voice_id": ("STRING", {
                    "default": "",
                    "tooltip": "自訂聲音 id(留空則用上方下拉選單)",
                }),
                "language": ("STRING", {
                    "default": "auto",
                    "tooltip": "BCP-47 語言代碼,auto = 自動偵測(中文可用 zh-TW)",
                }),
                "speed": ("FLOAT", {
                    "default": 1.0, "min": TTS_SPEED_MIN, "max": TTS_SPEED_MAX,
                    "step": 0.05,
                    "tooltip": f"語速 {TTS_SPEED_MIN}~{TTS_SPEED_MAX}",
                }),
            },
        }

    # 只輸出 AUDIO 交給下游 Save Audio / Preview Audio,本節點不寫檔
    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "synthesize"
    CATEGORY = CATEGORY_AUDIO

    def synthesize(self, text, voice_id, custom_voice_id="", language="auto",
                   speed=1.0):
        try:
            api = GrokAPI()
            data = api.tts(
                text,
                voice_id=custom_voice_id.strip() or voice_id,
                language=language,
                speed=speed,
            )
            audio = media_utils.audio_bytes_to_comfyui(data)
            dur = audio["waveform"].shape[-1] / audio["sample_rate"]
            print(f"✅ TTS 完成({dur:.1f} 秒,保存請接 Save Audio 節點)")
            return (audio,)
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
    "GrokVideoRefsNode": GrokVideoRefsNode,
    "GrokMultiImageNode": GrokMultiImageNode,
    "GrokImageListNode": GrokImageListNode,
    "GrokTTSNode": GrokTTSNode,
    "GrokListModelsNode": GrokListModelsNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "GrokChatNode": "Grok Chat 文字對話 (xAI)",
    "GrokVisionNode": "Grok Vision 視覺理解 (xAI)",
    "GrokImageGenNode": "Grok Imagine 圖片生成 (xAI)",
    "GrokVideoGenNode": "Grok Imagine 影片生成 (xAI)",
    "GrokVideoRefsNode": "Grok Imagine 參考圖影片・多圖 (xAI)",
    "GrokMultiImageNode": "Grok 多圖上傳 (Multi Image)",
    "GrokImageListNode": "Grok 參考圖打包 (Image List)",
    "GrokTTSNode": "Grok Voice 文字轉語音 (xAI)",
    "GrokListModelsNode": "Grok 模型列表 (xAI)",
}
