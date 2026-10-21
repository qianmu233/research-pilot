FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
ARG REQUIREMENTS=requirements.lock
COPY requirements.lock requirements-vector.lock requirements-chinese.lock ./
RUN pip install --no-cache-dir -r ${REQUIREMENTS}
COPY pyproject.toml README.md ./
COPY research_pilot ./research_pilot
COPY LICENSE THIRD_PARTY_NOTICES.md ./
RUN pip install --no-cache-dir --no-deps .
RUN useradd -u 10001 -m appuser && mkdir -p /app/data && chown appuser:appuser /app/data
USER appuser
EXPOSE 8010
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=10 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/health', timeout=2)"]
CMD ["uvicorn", "research_pilot.api:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1"]
