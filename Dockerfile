FROM ubuntu
MAINTAINER Marc DellaVolpe "marc.dellavolpe@gmail.com"

ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update && apt-get install -y python3 python3-dev python3-pip

COPY requirements.txt /tmp/
RUN pip3 install -r /tmp/requirements.txt
RUN rm /tmp/requirements.txt

RUN useradd -ms /bin/bash ircd
# RUN openssl req -x509 -newkey rsa:2048 -out /site/cert.pem -keyout /site/cert.pem -nodes -subj '/CN=localhost'

USER ircd
ENV HOME /home/ircd
WORKDIR /home/ircd
