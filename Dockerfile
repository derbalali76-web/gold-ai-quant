# GOLD AI QUANT — cloud web service (Render free tier or any Docker host)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GOLDQUANT_DATA_DIR=/tmp/goldquant
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir openpyxl
COPY backend/goldquant /app/goldquant
RUN useradd -m app && mkdir -p /tmp/goldquant && chown -R app /tmp/goldquant
USER app
EXPOSE 10000
CMD ["sh", "-c", "uvicorn --factory goldquant.api:create_app --host 0.0.0.0 --port ${PORT:-10000}"]
