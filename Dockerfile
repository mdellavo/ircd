FROM ubuntu
MAINTAINER Marc DellaVolpe "marc.dellavolpe@gmail.com"

VOLUME /home/ircd

ENV DEBIAN_FRONTEND noninteractive
ENV HOME /home/ircd
WORKDIR /home/ircd

RUN apt-get update
RUN apt-get dist-upgrade -y
RUN apt-get install -y software-properties-common

RUN add-apt-repository ppa:deadsnakes/ppa
RUN apt-get update
RUN apt-get install -y python3.8 python3.8-dev python3-pip python3.8-distutils
COPY requirements.txt /tmp
RUN python3.8 -m pip install -r /tmp/requirements.txt
RUN rm /tmp/requirements.txt

RUN apt-get purge -y software-properties-common
RUN apt-get -y autoremove

# RUN openssl req -x509 -newkey rsa:2048 -out /site/cert.pem -keyout /site/cert.pem -nodes -subj '/CN=localhost'

RUN useradd -ms /bin/bash ircd
USER ircd

CMD python3.8 -m ircd