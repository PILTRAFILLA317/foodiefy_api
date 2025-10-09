from fastapi import APIRouter, FastAPI
from pydantic import BaseModel
from textblob import TextBlob

from .config import settings

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
    """Analiza el sentimiento de un texto utilizando TextBlob."""
    blob = TextBlob(payload.text)
    sentiment = blob.sentiment
    return SentimentResponse(
        polarity=sentiment.polarity,
        subjectivity=sentiment.subjectivity,
    )


app.include_router(api_router)