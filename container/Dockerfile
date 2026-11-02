# The console as a container for Google Cloud Run, while the models, gateway and ledger stay on AWS.
# Built by scripts/deploy_cloudrun.py, which copies emerald/, web/ and the passages next to this file.
FROM python:3.13-slim

RUN useradd --create-home --uid 1000 user
WORKDIR /home/user/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user emerald emerald
COPY --chown=user web web
COPY --chown=user sources sources
USER user

ENV EMERALD_PUBLIC=1 EMERALD_HOST=0.0.0.0 EMERALD_PORT=8080 EMERALD_DATA=/tmp/emerald EMERALD_DEVICE=hosted-demo \
    AWS_REGION=us-east-1 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "-m", "emerald.server"]
