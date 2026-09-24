FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn httpx
COPY . .
EXPOSE 8057
CMD ["python", "main.py"]
