# Mighty Pilates cash-flow portal — Cloud Run image. empirica_core is vendored
# at the repo root, so the build needs no token and no private registry access.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app
COPY dashboard/requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# Non-root; owns /app because the app writes committed_actuals.json at runtime
# (durability = the GitHub sync, since Cloud Run's filesystem is ephemeral).
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

# Entry point is dashboard/app.py; it adds the repo root (where empirica_core is
# vendored) to sys.path. The Snowflake live-pull is optional — committed_actuals
# is the source of truth, so the image ships no warehouse credentials.
EXPOSE 8080
CMD ["sh", "-c", "exec streamlit run dashboard/app.py --server.port=${PORT:-8080} --server.address=0.0.0.0"]
