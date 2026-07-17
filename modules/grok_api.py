"""
xAI Grok API 客戶端(OpenAI 相容)
端點:
  POST /chat/completions     — 文字 / 視覺對話
  POST /images/generations   — Grok Imagine 圖片生成
  POST /videos/generations   — Grok Imagine 影片生成(非同步)
  GET  /videos/{request_id}  — 影片狀態輪詢
  POST /tts                  — Voice API 文字轉語音(回傳原始音訊 bytes)
  GET  /models               — 模型列表
"""

import time

import requests

from ..config.settings import (
    HTTP_STATUS_HINTS,
    MAX_IMAGES_PER_REQUEST,
    MAX_TTS_TEXT_LENGTH,
    MAX_VIDEO_DURATION_SEC,
    REQUEST_TIMEOUT,
    TTS_OUTPUT_FORMAT,
    TTS_SPEED_MAX,
    TTS_SPEED_MIN,
    VIDEO_POLL_INTERVAL,
    VIDEO_POLL_TIMEOUT,
    get_api_key,
    get_base_url,
)


class GrokAPIError(Exception):
    """API 錯誤,附 HTTP 狀態碼提示"""

    def __init__(self, message: str, status: int = None):
        self.status = status
        hint = HTTP_STATUS_HINTS.get(status)
        if hint:
            message = f"{message}(HTTP {status}: {hint})"
        elif status:
            message = f"{message}(HTTP {status})"
        super().__init__(message)


class GrokAPI:
    """xAI API 客戶端。api_key 不給則讀環境變數 XAI_API_KEY"""

    def __init__(self, api_key: str = None, base_url: str = None,
                 timeout: float = REQUEST_TIMEOUT):
        self.api_key = api_key if api_key else get_api_key()
        if not self.api_key:
            raise ValueError(
                "XAI_API_KEY 未設定。請複製 config/.env.example 為 config/.env "
                "並填入 https://console.x.ai 取得的 API Key"
            )
        self.base_url = (base_url or get_base_url()).rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # 低階請求
    # ------------------------------------------------------------------
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, payload: dict = None,
                 timeout: float = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            resp = requests.request(
                method, url,
                headers=self._headers(),
                json=payload,
                timeout=timeout or self.timeout,
            )
        except requests.RequestException as e:
            raise GrokAPIError(f"連線 xAI API 失敗: {e}")

        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                err = body.get("error", body)
                detail = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            except Exception:
                detail = resp.text[:300]
            raise GrokAPIError(f"{method} {path} 失敗: {detail}", status=resp.status_code)

        try:
            return resp.json()
        except ValueError:
            raise GrokAPIError(f"{method} {path} 回傳非 JSON 內容")

    # ------------------------------------------------------------------
    # Chat / Vision
    # ------------------------------------------------------------------
    def chat(self, messages: list, model: str, temperature: float = 1.0,
             max_tokens: int = 0, seed: int = 0) -> str:
        """送出 chat completion,回傳第一個 choice 的文字內容"""
        payload = {"model": model, "messages": messages, "temperature": temperature}
        if max_tokens > 0:
            payload["max_completion_tokens"] = max_tokens
        if seed > 0:
            payload["seed"] = seed

        data = self._request("POST", "/chat/completions", payload)
        choices = data.get("choices") or []
        if not choices:
            raise GrokAPIError(f"chat 回應沒有 choices: {data}")
        content = (choices[0].get("message") or {}).get("content") or ""

        usage = data.get("usage") or {}
        if usage:
            print(f"📊 tokens: prompt={usage.get('prompt_tokens')} "
                  f"completion={usage.get('completion_tokens')}")
        return content

    def chat_text(self, prompt: str, model: str, system_prompt: str = "",
                  **kwargs) -> str:
        """純文字對話"""
        messages = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, model, **kwargs)

    def chat_vision(self, prompt: str, image_b64_list: list, model: str,
                    system_prompt: str = "", detail: str = "auto",
                    **kwargs) -> str:
        """視覺對話:多張 PNG base64 + 文字提示"""
        content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}", "detail": detail},
            }
            for b64 in image_b64_list
        ]
        content.append({"type": "text", "text": prompt})

        messages = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content})
        return self.chat(messages, model, **kwargs)

    # ------------------------------------------------------------------
    # 圖片生成(Grok Imagine)
    # ------------------------------------------------------------------
    def generate_images(self, prompt: str, model: str, n: int = 1,
                        aspect_ratio: str = "", response_format: str = "b64_json") -> list:
        """
        產生 n 張圖,回傳 list(b64_json 字串或 URL,依 response_format)
        """
        if not 1 <= n <= MAX_IMAGES_PER_REQUEST:
            raise GrokAPIError(f"n 必須介於 1~{MAX_IMAGES_PER_REQUEST},收到 {n}")

        payload = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "response_format": response_format,
        }
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio

        data = self._request("POST", "/images/generations", payload)
        items = data.get("data") or []
        results = []
        for item in items:
            results.append(item.get("b64_json") or item.get("url") or "")
        if not results:
            raise GrokAPIError(f"圖片生成回應沒有 data: {data}")
        return results

    # ------------------------------------------------------------------
    # 影片生成(Grok Imagine,非同步 + 輪詢)
    # ------------------------------------------------------------------
    def submit_video(self, prompt: str, model: str, image_data_url: str = "",
                     duration: int = 6, aspect_ratio: str = "",
                     resolution: str = "",
                     reference_image_urls: list = None) -> str:
        """
        送出影片生成請求,回傳 request_id
        image_data_url:單張 i2v(強制第一幀);
        reference_image_urls:多張參考圖(影響風格,不強制第一幀,
        僅 grok-imagine-video 支援)
        """
        if not 1 <= duration <= MAX_VIDEO_DURATION_SEC:
            raise GrokAPIError(
                f"duration 必須介於 1~{MAX_VIDEO_DURATION_SEC} 秒,收到 {duration}")

        payload = {"model": model, "prompt": prompt, "duration": duration}
        if image_data_url:
            # xAI 要求 ImageUrl 結構(2026-07-17 實測 422:
            # "expected struct ImageUrl"),不能送純字串
            payload["image"] = {"url": image_data_url}
        if reference_image_urls:
            payload["reference_images"] = [
                {"url": u} for u in reference_image_urls]
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if resolution:
            payload["resolution"] = resolution

        data = self._request("POST", "/videos/generations", payload)
        request_id = data.get("request_id") or data.get("id")
        if not request_id:
            raise GrokAPIError(f"影片生成回應沒有 request_id: {data}")
        return request_id

    def poll_video(self, request_id: str, timeout: float = VIDEO_POLL_TIMEOUT,
                   interval: float = VIDEO_POLL_INTERVAL) -> str:
        """輪詢直到 done,回傳影片 URL;failed/expired/逾時則拋錯"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = self._request("GET", f"/videos/{request_id}")
            status = str(data.get("status") or "").lower()

            if status in ("done", "succeeded", "completed"):
                video = data.get("video") or {}
                url = video.get("url") if isinstance(video, dict) else None
                url = url or data.get("url") or ""
                if not url:
                    raise GrokAPIError(f"影片完成但回應沒有 video.url: {data}")
                return url
            if status in ("failed", "expired"):
                raise GrokAPIError(f"影片生成 {status}: {data.get('error') or data}")

            print(f"⏳ 影片生成中({status or 'pending'})…")
            time.sleep(interval)

        raise GrokAPIError(f"影片生成輪詢逾時({timeout:.0f}s),request_id={request_id}")

    def download(self, url: str, dest_path: str):
        """串流下載檔案(影片 URL 不需 Authorization)"""
        try:
            with requests.get(url, stream=True, timeout=self.timeout) as resp:
                resp.raise_for_status()
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
        except requests.RequestException as e:
            raise GrokAPIError(f"下載 {url} 失敗: {e}")

    # ------------------------------------------------------------------
    # TTS(Voice API)
    # ------------------------------------------------------------------
    def tts(self, text: str, voice_id: str = "eve", language: str = "auto",
            speed: float = 1.0, output_format: dict = None) -> bytes:
        """文字轉語音,回傳原始音訊 bytes(不落地,由呼叫端決定去向)"""
        if len(text) > MAX_TTS_TEXT_LENGTH:
            raise GrokAPIError(
                f"TTS 文字 {len(text)} 字元,超過上限 {MAX_TTS_TEXT_LENGTH}")
        if not TTS_SPEED_MIN <= speed <= TTS_SPEED_MAX:
            raise GrokAPIError(
                f"speed 必須介於 {TTS_SPEED_MIN}~{TTS_SPEED_MAX},收到 {speed}")

        payload = {
            "text": text,
            "voice_id": voice_id,
            "language": language,
            "speed": speed,
            "output_format": output_format or TTS_OUTPUT_FORMAT,
        }
        url = f"{self.base_url}/tts"
        try:
            resp = requests.post(url, headers=self._headers(), json=payload,
                                 timeout=self.timeout)
        except requests.RequestException as e:
            raise GrokAPIError(f"連線 xAI TTS 失敗: {e}")

        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                err = body.get("error", body)
                detail = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            except Exception:
                detail = resp.text[:300]
            raise GrokAPIError(f"POST /tts 失敗: {detail}", status=resp.status_code)

        if not resp.content:
            raise GrokAPIError("TTS 回應為空")
        return resp.content

    # ------------------------------------------------------------------
    # 模型列表
    # ------------------------------------------------------------------
    def get_models(self) -> list:
        """GET /models,回傳模型 id 列表"""
        data = self._request("GET", "/models")
        items = data.get("data") or []
        ids = []
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
        return ids
