"""
ComfyUI xAI Grok API 整合模組
支援 Grok chat / 視覺理解 / Grok Imagine 圖片與影片生成

結構:
  config/   — 集中設定(settings.py、.env)
  modules/  — API 客戶端、節點、影像工具
"""

# pytest 等工具可能把本檔當「頂層模組」匯入(無父套件),
# 此時相對匯入不可用,跳過 ComfyUI 節點註冊即可。
if __package__:
    from .config.settings import load_env
    from .modules.grok_nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

    # 註冊自訂 API 路由
    try:
        from aiohttp import web
        from server import PromptServer

        @PromptServer.instance.routes.get("/grok/models")
        async def get_grok_models(request):
            """GET /grok/models - 取得帳戶可用模型列表"""
            try:
                from .modules.grok_api import GrokAPI
                api = GrokAPI()
                models = api.get_models()
                return web.json_response({"success": True, "data": models})
            except Exception as e:
                return web.json_response({"success": False, "error": str(e)}, status=500)

        print("✅ 已註冊 API 路由: GET /grok/models")
    except Exception as e:
        print(f"⚠️ 無法註冊 API 路由(可能不在 ComfyUI 環境中): {e}")

    # 模組載入時載入 API key
    load_env(verbose=True)

    print("=" * 70)
    print("🤖 ComfyUI xAI Grok - chat / vision / image / video v1.0")
    print("=" * 70)
    print("📦 支援的功能:")
    print("   💬 Grok Chat 文字對話(system prompt / temperature / seed)")
    print("   👁️ Grok Vision 視覺理解(IMAGE batch 最多 8 張)")
    print("   🎨 Grok Imagine 圖片生成(單次最多 10 張)")
    print("   🎬 Grok Imagine 影片生成(文生/圖生影片,最長 15 秒)")
    print("   🎙️ Grok Voice 文字轉語音(eve/ara/leo/rex/sal + custom voice)")
    print("   📋 模型列表查詢")
    print("=" * 70)
    print("✨ 特色:")
    print("   💾 生成節點輸出 IMAGE/VIDEO/AUDIO 型別,不自行寫檔——")
    print("      保存交給下游 Save Image / Save Video / Save Audio,不重複落地")
    print("   🔄 影片非同步輪詢,下載到 temp 後包成 VIDEO 型別")
    print("   🧩 模型下拉選單從 GET /models 動態載入(含快取與 fallback)")
    print("   ⚙️ .env 管理 XAI_API_KEY,本地先驗證參數再打 API")
    print("=" * 70)
else:
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}

# ComfyUI 相容性
__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
