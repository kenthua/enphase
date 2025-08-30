FROM python:3.13.7-slim

RUN apt-get update && \
    apt-get -y --no-install-recommends install wget gnupg && \
    wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo tee /etc/apt/trusted.gpg.d/google.asc >/dev/null && \
    echo "deb http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list && \
    apt-get update && \
    apt-get -y --no-install-recommends install python3-dev gcc python3-pip git google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /

RUN pip3 install --no-cache-dir -r /requirements.txt

COPY full_backup.py self_consumption.py web.py /

CMD python3 /web.py
