DESTDIR?=/
datadir?=$(DESTDIR)/usr/share
INSTALL=install

SOURCES=$(wildcard *.desktop.in)
TARGETS=${SOURCES:.in=}

all: $(TARGETS) icons

icons:
	for i in 96 72 64 48 36 32 24 22 16; do \
		convert -background none chmviewkit.svg -resize $${i}x$${i} chmviewkit-$${i}.png; \
	done
pos:
	make -C po all

install: all
	python setup.py install -O2 --root $(DESTDIR)
	$(INSTALL) -d $(datadir)/applications/
	$(INSTALL) -m 0644 chmviewkit.desktop $(datadir)/applications/
	$(INSTALL) -m 0644 -D chmviewkit.svg $(datadir)/icons/hicolor/scalable/apps/chmviewkit.svg;
	for i in 96 72 64 48 36 32 24 22 16; do \
		install -d $(datadir)/icons/hicolor/$${i}x$${i}/apps; \
		$(INSTALL) -m 0644 -D chmviewkit-$${i}.png $(datadir)/icons/hicolor/$${i}x$${i}/apps/chmviewkit.png; \
	done

%.desktop: %.desktop.in pos
	intltool-merge -d po $< $@

clean:
	rm -f $(TARGETS)
	for i in 96 72 64 48 36 32 24 22 16; do \
		rm -f chmviewkit-$${i}.png; \
	done

