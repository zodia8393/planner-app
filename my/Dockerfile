FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    "fastapi>=0.115,<1" \
    "uvicorn[standard]>=0.34,<1" \
    "jinja2>=3.1,<4" \
    "python-multipart>=0.0.18,<1" \
    "markupsafe>=3,<4" \
    "openpyxl>=3.1,<4" \
    "httpx>=0.27,<1"

ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

ARG CACHE_BUST=1
COPY common/ common/
COPY main.py .
COPY templates/ templates/
COPY static/ static/

RUN mkdir -p /app/data/shared

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
