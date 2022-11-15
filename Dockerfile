FROM python:3.10

COPY ./requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip3 install -r /tmp/requirements.txt && pip cache purge

COPY ./process_exporter.py /usr/bin/process_exporter


ENTRYPOINT [ "process_exporter" ]