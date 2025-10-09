from .config import settings
import httpx
from fastapi import APIRouter, FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from textblob import TextBlob

import os
import re
import json
import time
import tempfile
import subprocess
from urllib.parse import urlparse

import yt_dlp

import whisper
print("whisper module loaded")


app = FastAPI(title=settings.API_TITLE, version=settings.API_VERSION)


class SentimentRequest(BaseModel):
    text: str


class SentimentResponse(BaseModel):
    polarity: float
    subjectivity: float


api_router = APIRouter(prefix="/api", tags=["core"])


@api_router.get("/health")
def healthcheck() -> dict:
    """Punto de entrada mínimo para comprobar que la API responde."""
    return {"status": "ok", "version": settings.API_VERSION}


@api_router.post("/sentiment", response_model=SentimentResponse)
def analyze_sentiment(payload: SentimentRequest) -> SentimentResponse:
    blob = TextBlob(payload.text)
    sentiment = blob.sentiment
    return SentimentResponse(
        polarity=sentiment.polarity,
        subjectivity=sentiment.subjectivity,
    )


# --- VideoTranscriber / RecipeAnalyzer adapted from previous Flask version ---


class RecipeAnalyzer:
    def __init__(self):
        """Recipe analyzer that optionally uses a DeepSeek/OpenAI-like client.

        The client is optional: if `DEEPSEEK_API_KEY` is not set, analyze_recipe
        will return an explanatory error instead of raising at init time.
        """
        api_key = os.getenv("DEEPSEEK_API_KEY")
        api_base = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")

        self.client = None
        if api_key:
            try:
                # Lazy create an httpx client wrapper similar to the original
                transport = httpx.HTTPTransport(retries=3)
                self.client = httpx.Client(transport=transport, timeout=60.0)
                # Note: integration with a specific OpenAI/DeepSeek SDK can be
                # added here when available.
                self._api_key = api_key
                self._api_base = api_base
            except Exception:
                self.client = None

    def analyze_recipe(self, transcription_data: dict) -> dict:
        transcription = transcription_data.get("transcription", "")
        metadata = transcription_data.get("metadata", {})

        if not transcription:
            return {"success": False, "error": "Empty transcription"}

        # If no client available, return a helpful error so caller can decide
        if not self.client:
            return {"success": False, "error": "DEEPSEEK_API_KEY not configured; recipe analysis unavailable"}

        # Build prompt (kept simple to avoid external SDK dependency)
        context = (
            f"Título del video: {metadata.get('title', 'Sin título')}\n"
            f"Descripción: {metadata.get('description', 'Sin descripción')}\n"
            f"Transcripción: {transcription}"
        )

        # For now, call a hypothetical endpoint or return error (placeholder)
        # A real implementation would call the external chat/completion API.
        return {"success": False, "error": "Recipe analysis not implemented on this instance (missing external API integration)"}


class VideoTranscriber:
    def __init__(self):
        # Load Whisper model at initialization (same behaviour as previous Flask app)
        # This will raise if whisper or torch are missing so failures surface early.
        try:
            self.whisper_model = whisper.load_model("base", device="cpu")
        except Exception as e:
            # Re-raise with clearer message
            raise RuntimeError(f"Failed to load Whisper model: {e}")

    def _ensure_whisper(self):
        if whisper is None:
            raise RuntimeError(
                "whisper package is not installed in the environment")
        if self.whisper_model is None:
            # load model lazily; use cpu by default
            self.whisper_model = whisper.load_model("base", device="cpu")

    def extract_platform(self, url: str) -> str:
        domain = urlparse(url).netloc.lower()
        if "youtube.com" in domain or "youtu.be" in domain:
            return "youtube"
        elif "tiktok.com" in domain:
            return "tiktok"
        elif "instagram.com" in domain:
            return "instagram"
        elif "facebook.com" in domain or "fb.watch" in domain or "m.facebook.com" in domain:
            return "facebook"
        else:
            return "unknown"

    def get_facebook_ydl_opts(self, temp_dir: str) -> dict:
        return {
            "format": "best[height<=720]/best",
            "outtmpl": os.path.join(temp_dir, "%(id)s.%(ext)s"),
            "quiet": False,
            "no_warnings": False,
            "writeinfojson": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }],
            "http_headers": {
                "User-Agent": "Mozilla/5.0",
            },
            "extractor_args": {"facebook": {"skip_dash_manifest": True}},
            "nocheckcertificate": True,
            "ignoreerrors": False,
        }

    def get_tiktok_ydl_opts(self, temp_dir: str) -> dict:
        return {
            "format": "best[ext=mp4]/best",
            "outtmpl": os.path.join(temp_dir, "%(id)s.%(ext)s"),
            "quiet": False,
            "no_warnings": False,
            "writeinfojson": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }],
            "http_headers": {"User-Agent": "Mozilla/5.0"},
            "extractor_args": {"tiktok": {"webpage_url_basename": "video"}},
        }

    def get_default_ydl_opts(self, temp_dir: str) -> dict:
        return {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(temp_dir, "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }],
        }

    def find_audio_file(self, temp_dir: str):
        audio_extensions = [".wav", ".mp3", ".m4a", ".webm", ".aac", ".ogg"]
        for file in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, file)
            if os.path.isfile(file_path):
                _, ext = os.path.splitext(file.lower())
                if ext in audio_extensions:
                    return file_path
        return None

    def extract_audio_from_video(self, video_file: str, temp_dir: str):
        try:
            audio_file = os.path.join(temp_dir, "extracted_audio.wav")
            cmd = [
                "ffmpeg", "-i", video_file,
                "-vn", "-acodec", "pcm_s16le",
                "-ar", "16000", "-ac", "1",
                audio_file, "-y", "-loglevel", "error"
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            return audio_file if os.path.exists(audio_file) else None
        except subprocess.CalledProcessError as e:
            raise Exception(f"FFmpeg extraction failed: {e}")

    def download_audio(self, url: str) -> dict:
        platform = self.extract_platform(url)

        if platform == 'facebook':
            url = url.replace('m.facebook.com', 'www.facebook.com')

        if yt_dlp is None:
            raise RuntimeError("yt_dlp is not installed in the environment")

        with tempfile.TemporaryDirectory() as temp_dir:
            # Choose options
            if platform == 'facebook':
                ydl_opts = self.get_facebook_ydl_opts(temp_dir)
            elif platform == 'tiktok':
                ydl_opts = self.get_tiktok_ydl_opts(temp_dir)
            else:
                ydl_opts = self.get_default_ydl_opts(temp_dir)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

            # Find audio file
            audio_file = self.find_audio_file(temp_dir)

            if not audio_file:
                # Try to extract audio from any video file
                media_files = [os.path.join(temp_dir, f) for f in os.listdir(
                    temp_dir) if f.endswith(('.mp4', '.webm', '.mkv', '.avi', '.mov'))]
                if media_files:
                    audio_file = self.extract_audio_from_video(
                        media_files[0], temp_dir)

            if not audio_file or not os.path.exists(audio_file):
                raise Exception("No audio file found after download")

            # Transcribe using whisper (lazy load)
            self._ensure_whisper()
            result = self.whisper_model.transcribe(audio_file, fp16=False)

            return {
                'transcription': result.get('text', '').strip(),
                'title': info.get('title', ''),
                'description': info.get('description', ''),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', ''),
                'view_count': info.get('view_count', 0),
                'platform': platform
            }


transcriber = VideoTranscriber()
recipe_analyzer = RecipeAnalyzer()


@api_router.post('/transcribe')
async def transcribe_video(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = None

    if not data or 'url' not in data:
        raise HTTPException(
            status_code=400, detail='Missing required parameter: url')

    url = data['url']
    include_metadata = data.get('include_metadata', True)
    analyze_recipe_flag = data.get('analyze_recipe', False)

    if not re.match(r'^https?://', url):
        raise HTTPException(status_code=400, detail='Invalid URL format')

    try:
        result = transcriber.download_audio(url)
    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    response = {
        'success': True,
        'transcription': result['transcription'],
        'platform': result['platform']
    }

    if include_metadata:
        response['metadata'] = {
            'title': result.get('title', ''),
            'description': result.get('description', ''),
            # 'duration': result.get('duration', 0),
            'uploader': result.get('uploader', ''),
            # 'view_count': result.get('view_count', 0)
        }

    if analyze_recipe_flag:
        analysis_data = {
            'transcription': result['transcription'],
            'metadata': {
                'title': result.get('title', ''),
                'description': result.get('description', '')
            }
        }
        recipe_result = recipe_analyzer.analyze_recipe(analysis_data)
        response['recipe_analysis'] = recipe_result

    return JSONResponse(response)


@api_router.post('/analyze-recipe')
async def analyze_recipe_endpoint(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = None

    if not data:
        raise HTTPException(status_code=400, detail='No data provided')

    transcription = data.get('transcription', '')
    metadata = data.get('metadata', {})

    if not transcription:
        raise HTTPException(
            status_code=400, detail='Missing required field: transcription')

    analysis_data = {
        'transcription': transcription,
        'metadata': metadata
    }

    result = recipe_analyzer.analyze_recipe(analysis_data)
    return JSONResponse(result)


@api_router.post('/debug-platform')
async def debug_platform(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = None

    if not data or 'url' not in data:
        raise HTTPException(status_code=400, detail='Missing url')

    url = data['url']
    platform = transcriber.extract_platform(url)

    if yt_dlp is None:
        return JSONResponse({'success': False, 'error': 'yt_dlp not installed'}, status_code=500)

    with tempfile.TemporaryDirectory() as temp_dir:
        if platform == 'facebook':
            ydl_opts = transcriber.get_facebook_ydl_opts(temp_dir)
        elif platform == 'tiktok':
            ydl_opts = transcriber.get_tiktok_ydl_opts(temp_dir)
        else:
            ydl_opts = transcriber.get_default_ydl_opts(temp_dir)

        # Remove postprocessors for debug
        ydl_opts.pop('postprocessors', None)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        return JSONResponse({
            'success': True,
            'platform': platform,
            'title': info.get('title'),
            'duration': info.get('duration'),
            'uploader': info.get('uploader')
        })


@api_router.get('/supported-platforms')
def supported_platforms():
    return JSONResponse({
        'supported_platforms': [
            'YouTube Shorts',
            'TikTok',
            'Instagram Reels',
            'Facebook Videos and Reels'
        ],
        'supported_urls': {
            'youtube': [
                'https://www.youtube.com/shorts/VIDEO_ID',
                'https://youtu.be/VIDEO_ID'
            ],
            'tiktok': [
                'https://www.tiktok.com/@user/video/VIDEO_ID'
            ],
            'instagram': [
                'https://www.instagram.com/reel/REEL_ID/',
                'https://www.instagram.com/p/POST_ID/'
            ],
            'facebook': [
                'https://www.facebook.com/watch/?v=VIDEO_ID',
                'https://www.facebook.com/reel/REEL_ID',
                'https://fb.watch/VIDEO_ID'
            ]
        },
        'note': 'API supports any platform compatible with yt-dlp'
    })


@api_router.get('/health')
def health_check():
    return JSONResponse({
        'status': 'healthy',
        'service': 'Video Transcription API',
        'whisper_model': 'base' if whisper is not None else 'not-available'
    })


app.include_router(api_router)
