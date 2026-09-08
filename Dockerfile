# Same immutable image for web and durable worker. Build is owner-operated only.
FROM python:3.14.0-slim-bookworm@sha256:d13fa0424035d290decef3d575cea23d1b7d5952cdf429df8f5542c71e961576
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TMPDIR=/tmp
# Fixed Debian archive freezes FFmpeg and its dependency resolution.
RUN rm -f /etc/apt/sources.list.d/debian.sources \
 && printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20260901T000000Z bookworm main\n' > /etc/apt/sources.list \
 && apt-get -o Acquire::Check-Valid-Until=false update \
 && apt-get install -y --no-install-recommends ffmpeg=7:5.1.9-0+deb12u1 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 foodiefy \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin foodiefy
WORKDIR /app
COPY requirements.lock ./
RUN python -m pip install --no-deps --only-binary=:all: -r requirements.lock \
 && python -m pip check
COPY src ./src
COPY scripts/web.py scripts/container_verify.py ./scripts/
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "scripts.web"]
