# --- Base Image ---
# Use a specific, stable Python version for reproducibility.
FROM python:3.11-slim

# --- Environment Variables ---
# Prevents Python from writing .pyc files to disk
ENV PYTHONDONTWRITEBYTECODE 1
# Prevents Python from buffering stdout and stderr, crucial for logging
ENV PYTHONUNBUFFERED 1
# Set the container port. Cloud Run will provide this automatically.
ENV PORT 8080

# --- Working Directory ---
# Set the working directory inside the container.
WORKDIR /app

# --- Install System Dependencies ---
# This is the CRITICAL fix for the "ffprobe not found" error.
# --no-install-recommends keeps the image size smaller.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# --- Install Python Dependencies ---
# Copy requirements first to leverage Docker's layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# --- Setup Non-Root User and Permissions ---
# Create a non-root user and group for security.
# Then create the directories the app needs and give the user ownership.
RUN groupadd --system --gid 1000 www-data && \
    useradd --system --uid 1000 --gid www-data www-data && \
    mkdir -p /app/app_logs /app/uploads && \
    chown -R www-data:www-data /app/app_logs /app/uploads

# --- Copy Application Code ---
# Copy the code after setting up users and directories.
COPY . .
# Ensure the copied code is also owned by the non-root user.
RUN chown -R www-data:www-data /app

# Switch to the non-root user for running the application.
USER www-data

# --- Expose Port ---
# Inform Docker that the container listens on this port.
# This uses the ENV variable defined above.
EXPOSE ${PORT}

# --- Run Command (Optimized for Production) ---
# Use 'exec' to ensure Gunicorn is the main process (PID 1) for proper signal handling.
# Bind to the $PORT variable provided by the environment.
# Increased workers for better performance.
CMD exec gunicorn --bind :${PORT} --workers 2 --threads 4 --log-level=info "app:app"