# CineWhy runtime image: the code and the web page, nothing else.
#
# The artifacts (catalogue, similarity matrix, polarity model; 365 MB for build v3) are NOT baked in.
# They come from the real data, which is neither committed nor redistributable, and rebuilding them
# takes hours (README, "Build from raw data"). The container reads them from $CINEWHY_ARTIFACTS,
# which is /app/artifacts: mount a folder there, or have the host download one before start
# (Phase J of docs/ROADMAP-2026-10-27.md). The server verifies every file against the manifest
# before it serves anything, so a missing or edited artifact stops the container instead of
# serving wrong answers.
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
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'])"
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
