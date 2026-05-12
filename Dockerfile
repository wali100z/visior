# Base image with Node.js
FROM node:22-slim

# Install Python, ffmpeg and dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install yt-dlp
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp \
    && chmod a+rx /usr/local/bin/yt-dlp

# Install Python packages
RUN pip3 install --break-system-packages \
    opencv-python-headless \
    numpy \
    requests

# Set working directory
WORKDIR /app

# Copy package files and install Node dependencies
COPY package*.json ./
RUN npm ci

# Copy all project files
COPY . .

# Start the server
CMD ["npm", "start"]