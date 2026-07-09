FROM python:3.12-slim

# Non-root from the start — no reason for a Discord bot to run as root
RUN useradd --create-home --shell /usr/sbin/nologin bot
WORKDIR /app

# Dependency layer cached independently of code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY graphql/ graphql/
COPY bot/ bot/

USER bot
CMD ["python", "-m", "bot.main"]
