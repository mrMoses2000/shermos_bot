FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYOPENGL_PLATFORM=egl

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      libegl1 \
      libgl1 \
      libglib2.0-0 \
      libgomp1 \
      libosmesa6 \
      libsm6 \
      libxext6 \
      libxrender1 \
      git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 88

CMD ["python", "run_webhook.py"]
