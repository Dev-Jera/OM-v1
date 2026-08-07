FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements-prod.txt ./
RUN pip install --prefer-binary -r requirements-prod.txt

COPY . .
RUN chmod +x scripts/container_start.sh

EXPOSE 8000

CMD ["sh", "scripts/container_start.sh"]
