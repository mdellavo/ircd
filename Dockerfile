FROM ubuntu:14.04
MAINTAINER Marc DellaVolpe "marc.dellavolpe@gmail.com"

ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update && apt-get install -y python python-dev git python-setuptools
RUN easy_install pip

RUN mkdir /site
RUN git clone https://github.com/mdellavo/ircd.git /site/ircd
RUN chmod -R a+r /site
RUN pip install -r /site/ircd/requirements.txt

RUN useradd -ms /bin/bash ircd

USER ircd
ENV HOME /home/ircd
WORKDIR /home/ircd

CMD ["/usr/bin/python", "/site/ircd/ircd.py"]