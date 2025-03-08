# Use an official Python 3.10 image as the base
FROM python:3.12-slim


# Set the working directory inside the container
WORKDIR /bot

# Update system packages and install necessary tools
RUN apt-get update && apt-get -y upgrade && apt-get install -y \
    build-essential \
    procps \
    bash \
    vim \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y redis-tools

# Download and install websocat
RUN apt-get update && apt-get install -y \
    curl \
    && curl -sSL https://github.com/vi/websocat/releases/download/v1.7.1/websocat_amd64-linux -o /usr/local/bin/websocat \
    && chmod +x /usr/local/bin/websocat

# Install pip and venv
RUN python3 -m pip install --upgrade pip setuptools wheel

# Copy requirements.txt into the container
COPY requirements.txt .

# Create a virtual environment and install dependencies
RUN python3 -m venv .venv && \
    /bot/.venv/bin/pip install --no-cache-dir -r requirements.txt

# Copy all files from the local project to the container
COPY . .

# Set the virtual environment as the default for all commands
ENV PATH="/bot/.venv/bin:$PATH"

# Expose the port your application listens on (e.g., 5000) and Redis (6379)
EXPOSE 5000 6379

# Set the default command to run the Python script
CMD ["bash"]
#CMD ["python", "bot/main.py"]
#CMD ["python", "-m", "bot.main"]
# CMD ["PYTHONPATH=/", "python", "main.py"]
# CMD ["bash", "-c", "PYTHONPATH=/ python main.py"]
WORKDIR /
ENV PYTHONPATH=/
#CMD ["python", "bot/main.py"]
#CMD ["bash", "-c", "python bot/main.py 2>&1 | tee /bot/tax_collector_bot.log"]
