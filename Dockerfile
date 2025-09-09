FROM python:3.13-slim

# Evita buffers no stdout
ENV PYTHONUNBUFFERED=1

# Instala dependências do sistema
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Define diretório de trabalho no container
WORKDIR /app

# Copia requirements.txt (que está junto do Dockerfile)
COPY requirements.txt /app/

# Instala dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copia TODO o projeto para dentro do container
COPY . /app/

# Expõe a porta do Django
EXPOSE 8000

# Comando padrão
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
