# Imagen base de Python
FROM python:3.11-slim

# Establecer el directorio de trabajo
WORKDIR /app

# Copiar el archivo de dependencias primero para aprovechar el caché
COPY requirements.txt .

# Instalar las dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código de la aplicación
COPY . .

# Exponer el puerto si es necesario (opcional para este bot)
# EXPOSE 8080

# Comando para ejecutar el bot
CMD ["python", "api_telegran.py"]
