from src.analysis.budget import PRICES
from src.analysis.evidence import output_schema
from src.analysis.models import ANALYSIS_VERSION, PROMPT_VERSION

from .models import digest


def policy_hash(config):
    return digest({'policy':'conservative-text-first-v1','stt':config.STT_MODEL,'extractor':config.RECIPE_EXTRACTOR_MODEL,
                   'visual':config.VISUAL_MODEL,'visual_enabled':config.ENABLE_VISUAL_FALLBACK,
                   'prompt':PROMPT_VERSION,'schema':ANALYSIS_VERSION,'output_schema':output_schema(),
                   'pricing':PRICES,'input_limit':config.AI_MAX_INPUT_BYTES,'output_limit':config.AI_MAX_OUTPUT_TOKENS,
                   'duration_limit':config.IMPORT_MAX_DURATION_SECONDS,'media_limit':config.IMPORT_MAX_MEDIA_BYTES})
