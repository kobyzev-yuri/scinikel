FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src ./src
COPY data ./data
COPY frontend ./frontend
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["scinikel"]
