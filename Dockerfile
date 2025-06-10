# 1. Use an official Python runtime as a parent image
FROM python:3.11-slim

# 2. Set the working directory in the container
WORKDIR /app

# 3. Install system dependencies required by your app
# - Install ffmpeg for pydub audio processing
# - Use --no-install-recommends to keep the image slim
# - Clean up apt cache to reduce final image size
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 4. Copy the requirements file and install Python dependencies
# This is done in a separate step to leverage Docker layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of your application's code into the container
COPY . .

# 6. Define the command to run your app using a production-grade WSGI server
# - Cloud Run automatically sets the PORT environment variable. Gunicorn will listen on it.
# - Use 'exec' to ensure signals are passed correctly.
# - The timeout is set to 0 (disabled) to handle long-running transcription jobs.
# - The number of workers and threads can be tuned for performance.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app