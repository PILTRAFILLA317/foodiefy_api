import whisper
import yt_dlp
from .config import settings
import httpx
try:
    from google import genai
    _HAS_GENAI = True
except Exception:
    genai = None
    _HAS_GENAI = False
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
from dotenv import load_dotenv
import signal
load_dotenv()

print("whisper module loaded")


app = FastAPI(title=settings.API_TITLE, version=settings.API_VERSION)
api_router = APIRouter(prefix="/api", tags=["core"])


class RecipeAnalyzer:
    def __init__(self):
        # Only Gemini with model gemini-2.0-flash is supported
        self.gemini_key = os.getenv('GEMINI_API_KEY') or getattr(
            settings, 'GEMINI_API_KEY', None)
        # Use the requested default model
        self.model_name = 'gemini-2.0-flash'
        # httpx client kept for any low-level needs, but we won't use HTTP fallback
        try:
            transport = httpx.HTTPTransport(retries=3)
            self.client = httpx.Client(transport=transport, timeout=60.0)
        except Exception:
            self.client = None

    def analyze_recipe(self, transcription_data: dict) -> dict:
        transcription = transcription_data.get('transcription', '')
        metadata = transcription_data.get('metadata', {})

        title_val = metadata.get('title') or transcription_data.get(
            'title') or 'Sin título'
        description_val = metadata.get('description') or transcription_data.get(
            'description') or 'Sin descripción'
        uploader_val = metadata.get('uploader') or transcription_data.get(
            'uploader') or 'Desconocido'
        platform_val = metadata.get('platform') or transcription_data.get(
            'platform') or 'Desconocida'
        thumbnail_val = metadata.get('thumbnail') or transcription_data.get(
            'thumbnail') or ''

        if not transcription:
            return {'success': False, 'error': 'Empty transcription'}

        # Build prompt/context
        context = (
            f"Título del video: {title_val}\n"
            f"Descripción: {description_val}\n"
            f"Plataforma: {platform_val}\n"
            f"Creador: {uploader_val}\n"
            f"Miniatura: {thumbnail_val}\n"
            f"Transcripción: {transcription}"
        )

        def _parse_model_text_to_json(text: str):
            if not text:
                return None, 'Empty model response'
            text = text.strip()
            if text.startswith('```json'):
                text = text[7:]
            if text.startswith('```'):
                text = text[3:]
            if text.endswith('```'):
                text = text[:-3]
            text = text.strip()
            try:
                return json.loads(text), None
            except Exception as e:
                return None, f'JSON decode error: {e}. Raw: {text[:1000]}'

        if not self.gemini_key:
            return {'success': False, 'error': 'GEMINI_API_KEY must be configured'}

        prompt = (
            "Eres un experto nutricionista y chef profesional. Analiza el JSON de contexto (título, descripción y transcripción) y genera un JSON válido con el siguiente formato exacto:\n"
            "{\n"
            "  \"titulo\": \"Título corto amigable para la receta\",\n"
            "  \"descripcion\": \"Texto describiendo la receta basándote en la información disponible\",\n"
            "  \"ingredientes\": [\"Ingrediente con cantidades\", \"Ingrediente\", ...],\n"
            "  \"pasos\": [\"Paso detallado\", \"Paso detallado\", ...],\n"
            "  \"tiempo_preparacion\": \"Tiempo aproximado en minutos\",\n"
            "  \"cantidad_final\": \"Rendimiento (porciones, peso o volumen)\",\n"
            "  \"macronutrientes\": {\n"
            "    \"kcal_totales\": numero,\n"
            "    \"carbohidratos_gramos\": numero,\n"
            "    \"proteinas_gramos\": numero,\n"
            "    \"grasas_gramos\": numero,\n"
            "    \"carbohidratos_porcentaje\": numero,\n"
            "    \"proteinas_porcentaje\": numero,\n"
            "    \"grasas_porcentaje\": numero\n"
            "  }\n"
            "}\n"
            "Solo puedes responder con JSON válido. Calcula cantidades y porcentajes aproximados cuando no tengas datos exactos. Usa listas sin numerar (\"1.\", \"2.\") en ingredientes y pasos. Aunque la receta se separe en varias partes (galleta y relleno por ejemplo) no separes los ingredientes, devuelve la liste de todos los ingredientes seguidos. El vídeo no es una receta o no incluye los datos mínimos para esta tarea, devuelve un error \n\n"
            + context
        )

        # Require google.genai client to be installed and GEMINI_API_KEY present.
        if not _HAS_GENAI or genai is None:
            return {'success': False, 'error': 'google.genai library not installed; please pip install google-genai'}

        try:
            client = genai.Client()
            # Use the fixed model name
            model_name = self.model_name

            # Verify model is present and supports generateContent
            supports_generate = False
            try:
                for m in client.models.list():
                    # m.name may be like 'models/gemini-2.5-flash'
                    m_name = (getattr(m, 'name', '') or '')
                    display = (getattr(m, 'display_name', '') or '')
                    # Normalize the candidate name pieces
                    base_name = m_name.split(
                        '/')[-1] if '/' in m_name else m_name
                    # Accept if the base name equals our model_name or display matches
                    if base_name == model_name or model_name == m_name or model_name in display:
                        actions = getattr(m, 'supported_actions', []) or []
                        if 'generateContent' in actions:
                            supports_generate = True
                            break
            except Exception:
                # if listing fails, we'll attempt generate and surface any error
                supports_generate = True

            if not supports_generate:
                return {'success': False, 'error': f'Model {model_name} not available or does not support generateContent for this account'}

            print('Using model:', model_name)
            model_text = None
            # Preferred streaming API (google-genai): client.models.generate_content_stream(...)
            model_text = None
            models_api = getattr(client, 'models', None)
            if models_api is not None and hasattr(models_api, 'generate_content_stream'):
                # Use the streaming content generator when available
                try:
                    print('Using generate_content_stream...')
                    stream = models_api.generate_content_stream(
                        model=model_name, contents=prompt)
                    parts = []
                    for event in stream:
                        # event shape may vary; try several common attributes
                        if event is None:
                            continue
                        if isinstance(event, str):
                            parts.append(event)
                            continue
                        piece = None
                        piece = getattr(event, 'text', None) or getattr(
                            event, 'content', None)
                        if piece is None:
                            delta = getattr(event, 'delta', None)
                            if delta is not None:
                                piece = getattr(delta, 'content', None) or getattr(
                                    delta, 'text', None)
                                if hasattr(piece, 'text'):
                                    piece = getattr(piece, 'text')
                        if piece is None and hasattr(event, 'candidates') and event.candidates:
                            c0 = event.candidates[0]
                            piece = getattr(c0, 'text', None) or getattr(
                                c0, 'content', None) or getattr(c0, 'message', None)
                        if piece is None:
                            try:
                                parts.append(str(event))
                            except Exception:
                                pass
                        else:
                            parts.append(piece)
                    model_text = ''.join([p for p in parts if p])
                except Exception as se:
                    # Streaming failed: fall back to other APIs below
                    print('generate_content_stream error:', se)

            # Fallbacks: prefer direct generate if available, then chat APIs
            # if not model_text and hasattr(client, 'generate'):
            #     try:
            #         resp = client.generate(model=model_name, prompt="Say this is a test")
            #         print('resp:', resp)
            #         model_text = getattr(resp, 'text', None) or getattr(resp, 'content', None) or str(resp)
            #     except Exception as e:
            #         print('client.generate failed:', e)
            # elif not model_text and hasattr(client, 'chat'):
            #     chat = getattr(client, 'chat')
            #     if hasattr(chat, 'create'):
            #         try:
            #             r = chat.create(model=model_name, messages=[{'role': 'user', 'content': "Say this is a test"}])
            #             model_text = getattr(r, 'message', None) or getattr(r, 'text', None) or str(r)
            #         except Exception as e:
            #             print('chat.create failed:', e)
            #     elif hasattr(chat, 'generate'):
            #         try:
            #             r = chat.generate(model=model_name, messages=[{'author': 'user', 'content': {'text': "Say this is a test"}}])
            #             if hasattr(r, 'candidates') and r.candidates:
            #                 c0 = r.candidates[0]
            #                 model_text = getattr(c0, 'content', None) or getattr(c0, 'message', None) or str(c0)
            #             else:
            #                 model_text = str(r)
            #         except Exception as e:
            #             print('chat.generate failed:', e)

            if model_text and not isinstance(model_text, str):
                try:
                    model_text = json.dumps(model_text)
                except Exception:
                    model_text = str(model_text)

            parsed, perr = _parse_model_text_to_json(model_text)
            if parsed is None:
                return {'success': False, 'error': perr or 'Failed to parse Gemini output to JSON'}

            recipe_data = parsed
            required_fields = ['titulo', 'descripcion', 'ingredientes', 'pasos',
                               'tiempo_preparacion', 'cantidad_final', 'macronutrientes']
            missing_fields = [
                field for field in required_fields if field not in recipe_data]
            # print('recipe_data:', recipe_data)
            if missing_fields:
                return {'success': False, 'error': f'La respuesta de la IA no contiene los campos requeridos: {", ".join(missing_fields)}'}

            # Attach original metadata for traceability
            recipe_data['uploader'] = uploader_val
            recipe_data['platform'] = platform_val
            if thumbnail_val:
                recipe_data['thumbnail'] = thumbnail_val

            return {'success': True, 'recipe': recipe_data}
        except Exception as e:
            return {'success': False, 'error': f'Gemini client call failed: {e}'}

        # No HTTP fallback: we require google.genai Client and model to be used.


class VideoTranscriber:
    def __init__(self):
        # Load Whisper model at initialization (same behaviour as previous Flask app)
        # This will raise if whisper or torch are missing so failures surface early.
        try:
            # Load with a watchdog timeout (seconds configurable via WHISPER_LOAD_TIMEOUT env, default 30)
            print("Loading Whisper model...")
            timeout_sec = int(os.getenv('WHISPER_LOAD_TIMEOUT', '30'))

            def _whisper_timeout_handler(signum, frame):
                raise TimeoutError(
                    f"Whisper model load timed out after {timeout_sec} seconds")

            prev_handler = signal.signal(
                signal.SIGALRM, _whisper_timeout_handler)
            try:
                signal.alarm(timeout_sec)
                self.whisper_model = whisper.load_model("tiny", device="cpu")
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, prev_handler)
        except Exception as e:
            # Re-raise with clearer message
            raise RuntimeError(f"Failed to load Whisper model: {e}")

    def _ensure_whisper(self):
        if whisper is None:
            raise RuntimeError(
                "whisper package is not installed in the environment")
        if self.whisper_model is None:
            print("Whisper debug.")
            # load model lazily; use cpu by default
            # Load with a watchdog timeout (seconds configurable via WHISPER_LOAD_TIMEOUT env, default 30)
            timeout_sec = int(os.getenv('WHISPER_LOAD_TIMEOUT', '30'))

            def _whisper_timeout_handler(signum, frame):
                raise TimeoutError(
                    f"Whisper model load timed out after {timeout_sec} seconds")

            prev_handler = signal.signal(
                signal.SIGALRM, _whisper_timeout_handler)
            try:
                signal.alarm(timeout_sec)
                self.whisper_model = whisper.load_model("tiny", device="cpu")
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, prev_handler)
        print("Whisper debug 2")

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

    def _extract_thumbnail(self, info: dict):
        if not info:
            return None
        thumb = info.get('thumbnail')
        if thumb:
            return thumb
        thumbs = info.get('thumbnails') or []
        if isinstance(thumbs, list) and thumbs:
            # pick highest resolution available
            sorted_thumbs = sorted(
                [t for t in thumbs if isinstance(t, dict) and t.get('url')],
                key=lambda t: (t.get('width', 0) or 0) * (t.get('height', 0) or 0),
                reverse=True
            )
            if sorted_thumbs:
                return sorted_thumbs[0].get('url')
        return None

    def preprocess_audio(self, audio_path: str, temp_dir: str):
        try:
            target_path = os.path.join(temp_dir, "preprocessed_audio.wav")
            max_duration = int(os.getenv('AUDIO_MAX_DURATION', '90'))
            cmd = [
                "ffmpeg", "-y", "-i", audio_path,
                "-ar", "16000",
                "-ac", "1",
                "-acodec", "pcm_s16le",
                "-loglevel", "error"
            ]
            if max_duration > 0:
                # Insert duration limit before output file
                cmd.extend(["-t", str(max_duration)])
            cmd.append(target_path)
            subprocess.run(cmd, check=True, capture_output=True)
            return target_path if os.path.exists(target_path) else audio_path
        except Exception as e:
            print(f"Audio preprocessing failed: {e}")
            return audio_path

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

            # Pre-process audio to reduce workload (duration cap + resample)
            audio_file = self.preprocess_audio(audio_file, temp_dir)

            # Transcribe using whisper (lazy load)
            print("Transcribing audio with Whisper...")
            self._ensure_whisper()
            print("Whisper debug 3")
            result = self.whisper_model.transcribe(
                audio_file,
                fp16=False,
                beam_size=1,
                best_of=1,
                condition_on_previous_text=False,
                temperature=0.0
            )
            print("Transcription completed.")

            return {
                'transcription': result.get('text', '').strip(),
                'title': info.get('title', ''),
                'description': info.get('description', ''),
                # 'duration': info.get('duration', 0),
                'uploader': info.get('uploader', ''),
                'thumbnail': self._extract_thumbnail(info),
                # 'view_count': info.get('view_count', 0),
                'platform': platform
            }


transcriber = VideoTranscriber()
recipe_analyzer = RecipeAnalyzer()


@api_router.post('/analyze-recipe')
async def analyze_recipe_endpoint(request: Request):
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
        print('Downloading and transcribing from URL')
        result = transcriber.download_audio(url)
        print('Transcription result obtained')
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
            'thumbnail': result.get('thumbnail', ''),
            # 'view_count': result.get('view_count', 0)
        }

    if analyze_recipe_flag:
        print('Analyzing recipe with Gemini...')
        analysis_data = {
            'transcription': result['transcription'],
            'metadata': {
                'title': result.get('title', ''),
                'description': result.get('description', ''),
                'thumbnail': result.get('thumbnail', ''),
                'uploader': result.get('uploader', ''),
                'platform': result.get('platform', '')
            }
        }
        recipe_result = recipe_analyzer.analyze_recipe(analysis_data)
        response['recipe_analysis'] = recipe_result
        return JSONResponse(result)

    # print('analysis_data:', analysis_data)
    print('Response:', response)
    result = recipe_analyzer.analyze_recipe(result)
    return JSONResponse(result)


@api_router.get('/health')
def health_check():
    return JSONResponse({
        'status': 'healthy',
        'service': 'Video Transcription API',
        'whisper_model': 'base' if whisper is not None else 'not-available'
    })


app.include_router(api_router)
