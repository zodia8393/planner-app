FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir "fastapi>=0.115,<1" "uvicorn[standard]>=0.34,<1" "python-multipart>=0.0.18,<1" "jinja2>=3.1,<4" "aiofiles>=24,<25" "httpx>=0.27,<1" "openpyxl>=3.1,<4"

COPY common/ common/
COPY main.py .
COPY templates/ templates/
COPY static/ static/

RUN mkdir -p data uploads

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
