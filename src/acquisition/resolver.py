import json
import re
import time
from urllib.parse import urlsplit

from .jobs import job_directory, run_worker
from .models import AcquisitionError, EvidenceBundle, Limits
from .network import SafeFetcher, public_url, validate_url
from .parsing import finalize
from .social import extract_metadata, populate_social


def platform_for(url):
    host = urlsplit(url).hostname or ""
    for platform, domains in {"youtube": ("youtube.com", "youtu.be"), "tiktok": ("tiktok.com",),
                              "instagram": ("instagram.com",), "facebook": ("facebook.com", "fb.watch")}.items():
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return platform
    return "web"


class SourceResolver:
    def __init__(self, limits: Limits | None = None, *, environment="production", allow_local_social=False, on_stage=None):
        self.limits = limits or Limits()
        self.fetcher = SafeFetcher(self.limits)
        self.environment, self.allow_local_social = environment, allow_local_social
        self.on_stage = on_stage

    def resolve(self, url: str) -> EvidenceBundle:
        start = time.monotonic()
        canonical = public_url(url) or ""
        platform = platform_for(canonical)
        bundle = EvidenceBundle(canonical_url=canonical, platform=platform,
                                source_type="webpage" if platform == "web" else "social_video")
        try:
            validate_url(url)
            if canonical != url:
                bundle.warnings.append("canonical_url_normalized")
            if platform == "web":
                result = self.fetcher.fetch(url)
                bundle.timings_ms["html_fetch"] = round((time.monotonic() - start) * 1000, 3)
                bundle.sizes.update(html_wire_bytes=result.wire_bytes, html_decompressed_bytes=len(result.body))
                if result.status != 200:
                    raise AcquisitionError("html_http_error")
                mime = result.headers.get("content-type", "").split(";")[0].lower()
                if mime not in {"text/html", "application/xhtml+xml"} or not re.search(rb"<(?:!doctype\s+html|html|head|body|main|article|script)\b", result.body[:4096], re.I):
                    raise AcquisitionError("unexpected_html_mime")
                bundle.canonical_url = public_url(result.url) or canonical
                bundle.platform = platform_for(bundle.canonical_url)
                if bundle.platform != "web":
                    bundle.warnings.append("social_redirect_html_only")
                parse_start = time.monotonic()
                if self.on_stage:
                    self.on_stage("extracting_metadata")
                with job_directory() as job:
                    (job / "html.bin").write_bytes(result.body)
                    run_worker("parse_html", {"bundle": bundle.model_dump(mode="json")}, job, self.limits)
                    parsed = json.loads((job / "result.json").read_text())
                    if "error" in parsed:
                        raise AcquisitionError(parsed["error"])
                    bundle = EvidenceBundle(**parsed)
                bundle.timings_ms["html_parse"] = round((time.monotonic() - parse_start) * 1000, 3)
            else:
                if self.on_stage:
                    self.on_stage("extracting_metadata")
                metadata = extract_metadata(url, self.limits, environment=self.environment, allow_local=self.allow_local_social)
                bundle.timings_ms["metadata"] = round((time.monotonic() - start) * 1000, 3)
                populate_social(bundle, metadata, self.fetcher, self.limits)
        except AcquisitionError as exc:
            bundle.status = "blocked" if exc.code in {"unsafe_url", "non_public_address", "social_extractor_disabled", "extractor_network_isolation_unavailable"} else "error"
            bundle.warnings.append(exc.code)
        except Exception:
            bundle.status = "error"
            bundle.warnings.append("acquisition_failed")
        finalize(bundle)
        bundle.timings_ms["total"] = round((time.monotonic() - start) * 1000, 3)
        return bundle
