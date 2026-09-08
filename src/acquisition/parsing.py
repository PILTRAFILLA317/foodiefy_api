import hashlib
import json
import re
import time

from bs4 import BeautifulSoup

from .models import (
    AcquisitionError,
    EvidenceBundle,
    Fragment,
    RecipeEvidence,
    Signals,
    Step,
)
from .network import public_url


def fragment(kind, text, language=None):
    return Fragment(source_kind=kind, text=text, language=language, original_chars=len(text))


def string(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def type_is(value, kind):
    types = value.get("@type", [])
    return any(t.rsplit("/", 1)[-1] == kind for t in ([types] if isinstance(types, str) else types) if isinstance(t, str))


def recipe_nodes(value, depth=0):
    if depth > 30:
        raise AcquisitionError("json_ld_depth_limit")
    if isinstance(value, list):
        for item in value:
            yield from recipe_nodes(item, depth + 1)
    elif isinstance(value, dict):
        if type_is(value, "Recipe"):
            yield value
        else:
            for item in value.values():
                if isinstance(item, (dict, list)):
                    yield from recipe_nodes(item, depth + 1)


def steps(value, section=None, depth=0):
    if depth > 30:
        raise AcquisitionError("json_ld_steps_depth_limit")
    if isinstance(value, str):
        text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
        return [Step(text=text, section=section)] if text else []
    if isinstance(value, list):
        return [step for item in value for step in steps(item, section, depth + 1)]
    if isinstance(value, dict):
        if type_is(value, "HowToSection"):
            return steps(value.get("itemListElement"), string(value.get("name")), depth + 1)
        return steps(value.get("text") or value.get("itemListElement") or value.get("name"), section, depth + 1)
    return []


def scrub_urls(value):
    if isinstance(value, dict):
        return {k: scrub_urls(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_urls(v) for v in value]
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        return public_url(value)
    return value


def normalize_recipe(raw):
    durations, seconds = {}, {}
    for key in ("prepTime", "cookTime", "totalTime"):
        value = string(raw.get(key))
        if value:
            durations[key] = value
            match = re.fullmatch(r"P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?", value)
            if match and any(match.groups()):
                seconds[key] = sum(float(n or 0) * unit for n, unit in zip(match.groups(), (86400, 3600, 60, 1)))
    ingredients = raw.get("recipeIngredient", [])
    ingredients = [ingredients] if isinstance(ingredients, str) else ingredients
    yield_value = raw.get("recipeYield")
    if isinstance(yield_value, (int, float)):
        yield_value = str(yield_value)
    if not isinstance(yield_value, (str, list, dict)):
        yield_value = None
    nutrition = raw.get("nutrition")
    return RecipeEvidence(name=string(raw.get("name")), description=string(raw.get("description")),
                          ingredients=[v for v in ingredients if isinstance(v, str)] if isinstance(ingredients, list) else [],
                          instructions=steps(raw.get("recipeInstructions")), recipe_yield=yield_value,
                          durations_iso8601=durations, durations_seconds=seconds,
                          nutrition=scrub_urls(nutrition) if isinstance(nutrition, dict) else {}, raw=scrub_urls(raw))


def parse_html(body: bytes, bundle: EvidenceBundle):
    soup = BeautifulSoup(body, "html.parser")
    def meta(*names):
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and string(tag.get("content")):
                return tag["content"]
        return None
    bundle.title = meta("og:title") or (soup.title.get_text(" ", strip=True) if soup.title else None)
    description = meta("og:description", "description")
    bundle.description = fragment("description", description) if description else None
    bundle.author = meta("author", "article:author")
    bundle.thumbnail = public_url(meta("og:image"))
    bundle.language = string(soup.html.get("lang")) if soup.html else None
    bundle.language_basis = "source" if bundle.language else None
    for script in soup.find_all("script", attrs={"type": re.compile(r"^application/ld\+json", re.I)}):
        try:
            raw = json.loads(script.string or script.get_text(), parse_constant=lambda _: None)
            for node in recipe_nodes(raw):
                try:
                    bundle.recipes.append(normalize_recipe(node))
                except (ValueError, TypeError, RecursionError):
                    bundle.warnings.append("invalid_recipe_json_ld")
                    bundle.status = "partial"
        except AcquisitionError as exc:
            bundle.warnings.append(exc.code)
            bundle.status = "partial"
        except (ValueError, TypeError, RecursionError):
            bundle.warnings.append("invalid_json_ld")
            bundle.status = "partial"
    for tag in soup.select("script, style, noscript, nav, header, footer, aside, form, svg, iframe, [hidden], [aria-hidden=true], [role=navigation], [role=banner], [role=complementary]"):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        if tag.attrs and re.search(r"(?:^|[\s_-])(ads?|advertisement|advert|menu|cookie|social-share)(?:$|[\s_-])", " ".join(tag.get("class", [])) + " " + str(tag.get("id", "")), re.I):
            tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text("\n", strip=True)
    bundle.html = fragment("html", text, bundle.language) if text else None
    if not bundle.recipes:
        bundle.warnings.append("no_recipe_json_ld")
    if len(bundle.recipes) > 1:
        bundle.warnings.append("multiple_recipes_select_before_mapping")


def calculate_signals(bundle):
    text = bundle.description.text if bundle.description else ""
    lower = text.casefold()
    hints = {
        "quantity_unit": bool(re.search(r"(?<![\d.,/])\d{1,12}(?:[.,/]\d{1,6})?\s{0,4}(?:kg|mg|g|ml|cl|l|oz|lb|cups?|tbsp|tsp|cucharadas?|cucharaditas?|tazas?)\b", lower)),
        "list_structure": len(re.findall(r"(?m)^\s*(?:[-•*]|\d+[.)])\s+", text)) >= 2,
        "cooking_verbs": bool(re.search(r"\b(?:mix|bake|boil|fry|stir|chop|mezclar?|hornear?|hervir|freír|cortar?)\b", lower)),
        "ingredient_step_structure": bool(re.search(r"\b(?:ingredients?|ingredientes?)\b", lower) and re.search(r"\b(?:steps?|instructions?|preparación|pasos?)\b", lower)),
    }
    visual = []
    candidates = [("metadata", bundle.title or "")]
    candidates += [(f.source_kind, f.text) for f in [bundle.description, *bundle.manual_subtitles, *bundle.auto_subtitles] if f]
    pattern = r"(?:cantidades en pantalla|ingredientes aquí|ingredientes en pantalla|quantities on screen|ingredients on screen|see (?:the )?screen)"
    for kind, candidate in candidates:
        if re.search(pattern, candidate, re.I) and kind not in visual:
            visual.append(kind)
    return Signals(has_existing_transcript=any(f.text.strip() for f in [*bundle.manual_subtitles, *bundle.auto_subtitles]),
                   description_recipe_signals=hints,
                   json_ld_completeness=[{"name": bool(r.name), "ingredients": bool(r.ingredients), "instructions": bool(r.instructions), "yield": r.recipe_yield is not None, "nutrition": bool(r.nutrition)} for r in bundle.recipes],
                   visual_dependency_hints=visual)


def finalize(bundle):
    started = time.monotonic()
    bundle.signals = calculate_signals(bundle)
    exported = bundle.model_dump(mode="json")
    for field in ("description", "html", "manual_subtitles", "auto_subtitles", "recipes", "media"):
        value = exported[field]
        bundle.sizes[field + "_serialized_bytes"] = len(json.dumps(value, ensure_ascii=False).encode())
    bundle.sizes["media_acquired_bytes"] = sum(item.size_bytes for item in bundle.media)
    stable = bundle.model_dump(mode="json", exclude={"content_hash", "timings_ms", "warnings", "status", "sizes"})
    bundle.content_hash = hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    bundle.timings_ms["evidence_finalize"] = round((time.monotonic() - started) * 1000, 3)
    return bundle


def context_view(bundle: EvidenceBundle, max_chars: int) -> dict:
    """Separate bounded DATA records; never construct an AI message or prompt here."""
    remaining = max(0, max_chars)
    records = []
    fragments = [fragment("metadata", bundle.title)] if bundle.title else []
    fragments += [bundle.description, *[fragment("json_ld", r.model_dump_json(exclude={"raw"})) for r in bundle.recipes],
                  bundle.html, *bundle.manual_subtitles, *bundle.auto_subtitles]
    for item in fragments:
        if item is None:
            continue
        kept = item.text[:remaining]
        remaining -= len(kept)
        records.append({"source_kind": item.source_kind, "text": kept, "language": item.language,
                        "original_chars": len(item.text), "truncated": len(kept) < len(item.text)})
    return {"trust": "untrusted_source_data", "max_chars": max_chars, "fragments": records,
            "warnings": ["context_truncated"] if any(r["truncated"] for r in records) else []}
