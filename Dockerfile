# CineWhy image. NOT YET BUILT ON THE DEVELOPMENT MACHINE (no Docker there): the CI job
# "docker" in .github/workflows/ci.yml builds and boots it, which is what turns this from a
# plan into a verified deployment. Treat it as unverified until that job has gone green.
#
# Two stages. The data (aclImdb, MovieLens) is neither committed nor redistributable, so
# the first stage fetches it (hash-checked), trains the polarity model, and builds the
# artifact set; only the finished artifacts and the code reach the final image.

FROM python:3.13-slim AS build
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements-serve.txt ./
RUN pip install -r requirements-serve.txt pandas==3.0.2
COPY cinewhy ./cinewhy
COPY tests/data ./tests/data
RUN python -m cinewhy.data.fetch --dir /data \
 && python -m cinewhy.absa.polarity --archive /data/aclImdb_v1.tar.gz --out /app/artifacts/polarity.joblib \
 && python -m cinewhy.build --acl /data/aclImdb_v1.tar.gz --ml /data/ml-25m.zip --out /app/artifacts

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1 \
    CINEWHY_ARTIFACTS=/app/artifacts PORT=7860
WORKDIR /app
COPY requirements-serve.txt ./
RUN pip install -r requirements-serve.txt && useradd -m -u 1000 app
COPY cinewhy ./cinewhy
COPY api ./api
COPY web ./web
COPY --from=build /app/artifacts ./artifacts
USER app
EXPOSE 7860
# /health returns the manifest hash only after boot-time verification succeeded.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'])"
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
