# Raccourcis de développement. Les commandes `flask translate …` fonctionnent aussi sans make.
VENV  ?= .venv
PY    := $(VENV)/bin/python
FLASK := $(VENV)/bin/flask

.PHONY: help install db seed run test extract update compile translations init-lang

help:
	@echo "install       crée le venv, installe les dépendances et compile les traductions"
	@echo "db            applique les migrations (flask db upgrade)"
	@echo "seed          crée l'utilisateur de démo et ses voyages"
	@echo "run           lance le serveur de développement"
	@echo "test          lance la suite pytest"
	@echo "extract       extrait les chaînes vers app/translations/messages.pot"
	@echo "update        extract + fusion dans chaque .po"
	@echo "compile       compile les .po en .mo"
	@echo "translations  update + compile"
	@echo "init-lang     crée une langue : make init-lang LOCALE=pt"

$(VENV):
	python3 -m venv $(VENV)

install: $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt
	$(FLASK) translate compile

db:
	$(FLASK) db upgrade

seed:
	$(FLASK) seed

run:
	$(FLASK) run --debug

test:
	$(PY) -m pytest

extract:
	$(FLASK) translate extract

update:
	$(FLASK) translate update

compile:
	$(FLASK) translate compile

translations: update compile

init-lang:
	@test -n "$(LOCALE)" || (echo "Usage : make init-lang LOCALE=pt" && exit 1)
	$(FLASK) translate init $(LOCALE)
