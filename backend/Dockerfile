FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY contracts/examples ./contracts/examples

# Run as a non-root user; case data goes to a mountable volume.
# AWS credentials come from the task/instance IAM role, never from this image.
RUN useradd --system --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser /data
USER appuser
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
