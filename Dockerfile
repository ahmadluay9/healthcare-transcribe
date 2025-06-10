# --- Stage 1: The Builder ---
# This stage installs all dependencies into a virtual environment.
FROM python:3.11-slim as builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

# Upgrade pip and create a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install them into the virtual environment
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# --- Stage 2: The Final Production Image ---
# Start from a clean base image.
FROM python:3.11-slim

# Set the same environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PORT 8080

WORKDIR /app

# Install only necessary system dependencies (not build tools)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Copy the virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Create the non-root user and grant permissions
RUN groupadd --system --gid 1000 www-data && \
    useradd --system --uid 1000 --gid www-data www-data && \
    mkdir -p /app/app_logs /app/uploads && \
    chown -R www-data:www-data /app/app_logs /app/uploads

# Copy the application code
COPY . .
RUN chown -R www-data:www-data /app

# Switch to the non-root user
USER www-data

# Set the PATH to include the virtual environment's binaries
ENV PATH="/opt/venv/bin:$PATH"

# Expose the port
EXPOSE ${PORT}

# Run the application
CMD exec gunicorn --bind :${PORT} --workers 2 --threads 4 --log-level=info "app:app"