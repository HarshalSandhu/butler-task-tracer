FROM python:3.12-slim

# openssh-client: this is what app/ssh/executor.py actually shells out to.
# No SSH server, no key material baked into the image - see README.md
# "SSH access model".
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
COPY app ./app
RUN pip install --no-cache-dir -e .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
