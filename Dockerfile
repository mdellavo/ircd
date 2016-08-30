FROM ubuntu
MAINTAINER Marc DellaVolpe "marc.dellavolpe@gmail.com"

ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update && apt-get install -y python python-dev git python-setuptools
RUN easy_install pip

COPY requirements.txt /tmp/
RUN pip install -r /tmp/requirements.txt
RUN rm /tmp/requirements.txt

RUN mkdir /site
RUN chmod -R a+r /site

RUN useradd -ms /bin/bash ircd

USER ircd
ENV HOME /home/ircd
WORKDIR /site/ircd

CMD ["/usr/bin/python", "/site/ircd/ircd.py"]