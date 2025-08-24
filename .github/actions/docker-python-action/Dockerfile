FROM postgres:latest

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the current directory contents into the container at /usr/src/app
COPY . .

# Copy entrypoint script and make it executable
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN apt update && apt install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-protobuf \
    libprotobuf-dev \
    protobuf-compiler \
    build-essential \
    libpq-dev \
    make \
    redis-server \
    redis-tools \
    protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

# Set the entrypoint script to run when the container starts
ENTRYPOINT ["/entrypoint.sh"]
