"""Local, owned benchmark media use the same isolated preparation as remote acquisition."""
from contextlib import contextmanager

from src.acquisition.jobs import job_directory, run_worker
from src.acquisition.models import AcquisitionError, Limits
from src.acquisition.social import verify_sandbox
from src.analysis.models import AudioEvidence, VisualEvidence
from src.analysis.pipeline import SourceMedia

from .contracts import read_json, resolve_path


class BenchmarkMedia(SourceMedia):
    def __init__(self, settings, case, base, *, variant='frames', allow_network=False, allow_local_social=False):
        super().__init__(settings, source_url=case.url, audio_url=case.audio_url, video_url=case.video_url,
                         allow_local_social=allow_local_social, variant=variant)
        self.case, self.base, self.allow_network = case, base, allow_network

    @contextmanager
    def _local(self, value, action):
        path = resolve_path(self.base, value)
        limits = Limits()
        if path.stat().st_size > limits.media_bytes:
            raise AcquisitionError('local_media_too_large')
        with job_directory() as job:
            verify_sandbox(job, limits)
            # Bounded read protects against a file growing after stat.
            with path.open('rb') as stream:
                data = stream.read(limits.media_bytes + 1)
            if len(data) > limits.media_bytes:
                raise AcquisitionError('local_media_too_large')
            (job / 'input.bin').write_bytes(data)
            run_worker(action, {'limits': limits.model_dump(), 'variant': self.variant}, job, limits, sandbox=True)
            output = read_json(job / 'result.json')
            if 'error' in output:
                raise AcquisitionError(output['error'])
            yield job, output

    @contextmanager
    def audio(self, evidence):
        local = self.case.audio_path
        if not local and self.case.local_path and resolve_path(self.base, self.case.local_path).suffix.lower() in {'.mp4', '.webm', '.mov', '.mp3', '.wav', '.m4a', '.ogg'}:
            local = self.case.local_path
        if local:
            with self._local(local, 'media') as (job, output):
                ref = output['media'][0]
                yield AudioEvidence(job / ref['filename'], ref['duration_seconds'], ref['mime_type'])
        else:
            if not self.allow_network:
                raise AcquisitionError('network_not_authorized')
            with super().audio(evidence) as audio:
                yield audio

    @contextmanager
    def visual(self, evidence):
        local = self.case.video_path
        if not local and self.case.local_path and resolve_path(self.base, self.case.local_path).suffix.lower() in {'.mp4', '.webm', '.mov'}:
            local = self.case.local_path
        if local:
            with self._local(local, 'visual') as (job, output):
                yield VisualEvidence(evidence, tuple(job / name for name in output['files']), self.variant,
                                     output['duration_seconds'], tuple(output['timestamps']))
        else:
            if not self.allow_network:
                raise AcquisitionError('network_not_authorized')
            with super().visual(evidence) as visual:
                yield visual
