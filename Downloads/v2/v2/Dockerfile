FROM python:3.11-slim

# Set working directory inside the container
WORKDIR /app

# Install system-level dependencies including SSH and FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/run/sshd

# Set environment variables
ENV PORT=10000
ENV NOTVISIBLE="in users profile"
ENV PYTHONUNBUFFERED=1

# Copy app files
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create SSH directory and configure (optional security improvement)
RUN mkdir -p /var/run/sshd && \
    echo "PermitRootLogin yes" >> /etc/ssh/sshd_config

# Expose ports for SSH and Flask/Gunicorn web service
EXPOSE 22
EXPOSE 10000

# Define default start command
CMD service ssh start && \
    gunicorn -k eventlet -w 1 --bind 0.0.0.0:$PORT main:app
