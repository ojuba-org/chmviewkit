POTFILE=$(shell cat POTFILES.in)
SOURCES=$(addprefix ../, $(POTFILE))
POFILES=$(wildcard *.po)
MOFILES=$(patsubst %.po,%.mo,$(POFILES))

all: chmviewkit.pot $(MOFILES)

chmviewkit.pot: $(SOURCES)
	intltool-update -g chmviewkit -p

%.mo: %.po
	msgfmt $*.po -o $*.mo
	mkdir -p ../locale/$*/LC_MESSAGES/ || :
	cp $*.mo ../locale/$*/LC_MESSAGES/chmviewkit.mo

%.po: chmviewkit.pot
	intltool-update -g chmviewkit -d $*

