# CineWhy runtime image: the code and the web page, nothing else.
#
# The artifacts (catalogue, similarity matrix, polarity model; 365 MB for build v3) are NOT baked in.
# They come from the real data, which is neither committed nor redistributable, and rebuilding them
# takes hours (README, "Build from raw data"). The container reads them from $CINEWHY_ARTIFACTS,
# which is /app/artifacts: mount a folder there, or set CINEWHY_ARTIFACTS_URL (https) and
# CINEWHY_ARTIFACTS_SHA256 and the container downloads, hash-checks and unpacks the zip itself on
# first start (cinewhy/artifacts/download.py). The server verifies every file against the manifest
# before it serves anything, so a missing or edited artifact stops the container instead of
# serving wrong answers.
#
# Behind a host's reverse proxy every request arrives from the proxy's address, so the per-client rate
# limit (120 POSTs a minute) would be one budget shared by every visitor. uvicorn reads the real
# address from X-Forwarded-For for peers named in FORWARDED_ALLOW_IPS (default 127.0.0.1 only). On a
# host where the container is reachable ONLY through its proxy (Hugging Face Spaces, Render) set
# FORWARDED_ALLOW_IPS=*; never set it when the container is also exposed directly, because a client
# could then send its own header and dodge the limit.
#
# Verified by the CI job "docker" (.github/workflows/ci.yml): it builds this image, boots it on the
# small synthetic artifact set from tests/smoke_artifacts.py, and probes /health, /recommend and /.
# That job has not run against this file yet when it is first committed: treat it as unverified
# until the job is green.

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1 \
    CINEWHY_ARTIFACTS=/app/artifacts PORT=7860
WORKDIR /app
COPY requirements-serve.txt ./
RUN pip install -r requirements-serve.txt && useradd -m -u 1000 app
COPY cinewhy ./cinewhy
COPY api ./api
COPY web ./web
USER app
EXPOSE 7860
# /health returns the manifest hash only after boot-time verification succeeded.
# The first start may download the artifact set (365 MB) and then verify about 560 MB of files, so the
# health check is given five minutes before it counts failures.
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s \
  CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'])"
# Put the artifacts in place if they are not there (set CINEWHY_ARTIFACTS_URL and
# CINEWHY_ARTIFACTS_SHA256; a mounted folder needs neither), then serve. If the fetch fails the
# container stops with the reason, rather than serving nothing or something unverified.
CMD ["sh", "-c", "python -m cinewhy.artifacts.download && exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
