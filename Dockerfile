# Bridge-Client Docker image
# Uses the official Playwright Python image to avoid Chromium dependency issues.
FROM mcr.microsoft.com/playwright/python:v1.51.0-noble

WORKDIR /app

# Install Python dependencies.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code.
COPY . /app

# Ensure CLI wrapper is executable.
RUN chmod +x /app/bin/bridge-cli

# Default environment values.
ENV PORT=8000
ENV HOST=0.0.0.0
ENV PYTHONPATH=/app

EXPOSE 8000

# Healthcheck.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()" || exit 1

CMD ["python", "client/client.py"]
